import os
import sys
import pandas as pd
import numpy as np

# Load 3y cached BTCUSDT M15 data
df_15m = pd.read_csv("cache_BTC_USDT_15m_3y.csv")
df_15m['datetime'] = pd.to_datetime(df_15m['timestamp'], unit='ms')
df_15m.set_index('datetime', inplace=True)

# Khung M15, M30, H4
df_30m = df_15m.resample('30min').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}).dropna()
df_4h = df_15m.resample('4h').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'}).dropna()

# 1. Cản EMA20 trên khung M30
df_30m['ema20_m30'] = df_30m['close'].ewm(span=20, adjust=False).mean()
df_30m['ema50_m30'] = df_30m['close'].ewm(span=50, adjust=False).mean()

# 2. Xu hướng khung lớn H4 (H4 3N / H4 Trend)
df_4h['ema20_h4'] = df_4h['close'].ewm(span=20, adjust=False).mean()
df_4h['ema50_h4'] = df_4h['close'].ewm(span=50, adjust=False).mean()
df_30m['h4_bull'] = df_30m.index.floor('4h').map((df_4h['ema20_h4'] > df_4h['ema50_h4']).astype(int).shift(1))

# Engine backtest hệ thống ALA Trading chuẩn channel:
# - Setup 1: Chạm/Hồi về Cản EMA20 của M30
# - Setup 2: Nến M15/M30 Full Lực (Momentum bar) hoặc 3N (3 nến tiếp diễn / đảo chiều tại cản)
# - Setup 3: SL ngoài cản EMA20 (+buffer), TP1 = 1.0R (chốt bớt / dời BE), TP2 = 1.8R, TP3 = 2.5R
def test_ala_ema20_3n_backtest(tp1_r=1.0, tp2_r=2.0):
    bars = df_30m.dropna().reset_index()
    trades = []
    in_trade = False
    active_trade = None
    pad = 40.0
    
    for i in range(3, len(bars)):
        row = bars.iloc[i]
        c1 = bars.iloc[i-1] # Nến vừa đóng
        c2 = bars.iloc[i-2]
        c3 = bars.iloc[i-3]
        
        # Quản lý lệnh đang chạy
        if in_trade:
            t = active_trade
            c_high = row['high']
            c_low = row['low']
            
            if t['side'] == 'BUY':
                if c_low <= t['curr_sl']:
                    t['pnl_r'] += (t['curr_sl'] - t['entry']) / t['sl_dist'] * t['remaining_vol']
                    t['exit_reason'] = 'SL_BE' if t['tp1_hit'] else 'SL'
                    trades.append(t)
                    in_trade = False
                    continue
                if not t['tp1_hit'] and c_high >= t['tp1']:
                    t['tp1_hit'] = True
                    t['pnl_r'] += tp1_r * 0.5
                    t['remaining_vol'] = 0.5
                    t['curr_sl'] = t['entry'] # Kéo SL về Entry (chuẩn lệnh msg 15)
                if t['tp1_hit'] and c_high >= t['tp2']:
                    t['pnl_r'] += tp2_r * 0.5
                    t['exit_reason'] = 'TP2'
                    trades.append(t)
                    in_trade = False
                    continue
            elif t['side'] == 'SELL':
                if c_high >= t['curr_sl']:
                    t['pnl_r'] += (t['entry'] - t['curr_sl']) / t['sl_dist'] * t['remaining_vol']
                    t['exit_reason'] = 'SL_BE' if t['tp1_hit'] else 'SL'
                    trades.append(t)
                    in_trade = False
                    continue
                if not t['tp1_hit'] and c_low <= t['tp1']:
                    t['tp1_hit'] = True
                    t['pnl_r'] += tp1_r * 0.5
                    t['remaining_vol'] = 0.5
                    t['curr_sl'] = t['entry']
                if t['tp1_hit'] and c_low <= t['tp2']:
                    t['pnl_r'] += tp2_r * 0.5
                    t['exit_reason'] = 'TP2'
                    trades.append(t)
                    in_trade = False
                    continue
            continue

        # Tín hiệu vào lệnh ALA Trading:
        # Cản EMA20 M30
        ema20 = c1['ema20_m30']
        o1, h1, l1, cl1 = c1['open'], c1['high'], c1['low'], c1['close']
        body1 = abs(cl1 - o1)
        lower_wick1 = min(o1, cl1) - l1
        upper_wick1 = h1 - max(o1, cl1)
        
        # Nến Full Lực (Thân nến lớn >= 65% toàn dải nến) hoặc Nến rút râu tại cản EMA20
        is_bull_full_force = (cl1 > o1) and (body1 >= 0.60 * (h1 - l1)) and (l1 <= ema20 <= cl1 or abs(l1 - ema20)/ema20 < 0.003)
        is_bull_3n = (c1['close'] > c2['close'] > c3['close']) and (c2['low'] <= ema20 or c3['low'] <= ema20)
        
        is_bear_full_force = (cl1 < o1) and (body1 >= 0.60 * (h1 - l1)) and (h1 >= ema20 >= cl1 or abs(h1 - ema20)/ema20 < 0.003)
        is_bear_3n = (c1['close'] < c2['close'] < c3['close']) and (c2['high'] >= ema20 or c3['high'] >= ema20)
        
        h4_bull = c1['h4_bull']
        
        # BUY Setup: H4 Trend Tăng + Retest cản EMA20 M30 + Nến M30 Full lực / 3N bứt phá
        if h4_bull == 1 and (is_bull_full_force or is_bull_3n):
            entry = cl1
            sl = min(l1, ema20) - pad
            dist = entry - sl
            if dist > 0:
                active_trade = {
                    'side': 'BUY', 'entry': entry, 'sl': sl, 'curr_sl': sl, 'sl_dist': dist,
                    'tp1': entry + tp1_r * dist, 'tp2': entry + tp2_r * dist,
                    'tp1_hit': False, 'remaining_vol': 1.0, 'pnl_r': 0.0,
                    'type': 'Full Lực EMA20' if is_bull_full_force else 'Mô hình 3N'
                }
                in_trade = True
                continue
                
        # SELL Setup: H4 Trend Giảm + Retest cản EMA20 M30 + Nến M30 Full lực đỏ / 3N đạp
        elif h4_bull == 0 and (is_bear_full_force or is_bear_3n):
            entry = cl1
            sl = max(h1, ema20) + pad
            dist = sl - entry
            if dist > 0:
                active_trade = {
                    'side': 'SELL', 'entry': entry, 'sl': sl, 'curr_sl': sl, 'sl_dist': dist,
                    'tp1': entry - tp1_r * dist, 'tp2': entry - tp2_r * dist,
                    'tp1_hit': False, 'remaining_vol': 1.0, 'pnl_r': 0.0,
                    'type': 'Full Lực EMA20' if is_bear_full_force else 'Mô hình 3N'
                }
                in_trade = True
                continue

    df_res = pd.DataFrame(trades)
    if df_res.empty:
        return {'total': 0, 'winrate': 0, 'net_r': 0, 'pf': 0, 'max_dd': 0}
        
    total = len(df_res)
    wins = df_res[df_res['pnl_r'] > 0]
    tp1_hits = df_res[df_res['tp1_hit'] == True]
    tp2_hits = df_res[df_res['exit_reason'] == 'TP2']
    net_r = df_res['pnl_r'].sum()
    gp = wins['pnl_r'].sum()
    gl = abs(df_res[df_res['pnl_r'] < 0]['pnl_r'].sum())
    pf = gp / gl if gl > 0 else 999.0
    df_res['cum'] = df_res['pnl_r'].cumsum()
    max_dd = (df_res['cum'].cummax() - df_res['cum']).max()
    
    return {
        'total': total,
        'winrate': round(len(wins) / total * 100, 2),
        'tp1_rate': round(len(tp1_hits) / total * 100, 2),
        'tp2_rate': round(len(tp2_hits) / total * 100, 2),
        'net_r': round(net_r, 2),
        'pf': round(pf, 2),
        'max_dd': round(max_dd, 2)
    }

if __name__ == '__main__':
    print("--- BACKTEST HỆ THỐNG ALA TRADING (CẢN EMA20 M30 + NẾN FULL LỰC + 3N) 3 NĂM BTC ---")
    res = test_ala_ema20_3n_backtest(tp1_r=1.0, tp2_r=2.0)
    print("Kết quả:", res)
