import os
import sys
import pandas as pd
import numpy as np

# Load 3y cached BTCUSDT M15 data
df_15m = pd.read_csv("cache_BTC_USDT_15m_3y.csv")
df_15m['datetime'] = pd.to_datetime(df_15m['timestamp'], unit='ms')
df_15m.set_index('datetime', inplace=True)

# Resample to M30 and H4
df_30m = df_15m.resample('30min').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}).dropna()
df_4h = df_15m.resample('4h').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'}).dropna()

# Calculate RSI 14 on M30
def calc_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / (loss + 1e-9)
    return 100 - (100 / (1 + rs))

df_30m['rsi'] = calc_rsi(df_30m['close'], 14)

# Calculate Bollinger Bands on M30 (20, 2)
df_30m['sma20'] = df_30m['close'].rolling(20).mean()
df_30m['std20'] = df_30m['close'].rolling(20).std()
df_30m['bb_upper'] = df_30m['sma20'] + 2 * df_30m['std20']
df_30m['bb_lower'] = df_30m['sma20'] - 2 * df_30m['std20']

# Support & Resistance (Swing High / Low rolling 20 bars)
df_30m['res_level'] = df_30m['high'].shift(1).rolling(20).max()
df_30m['sup_level'] = df_30m['low'].shift(1).rolling(20).min()

# H4 Trend (EMA20 vs EMA50)
df_4h['ema20'] = df_4h['close'].ewm(span=20, adjust=False).mean()
df_4h['ema50'] = df_4h['close'].ewm(span=50, adjust=False).mean()
h4_bull = (df_4h['ema20'] > df_4h['ema50']).astype(int).shift(1)
df_30m['h4_bull'] = df_30m.index.floor('4h').map(h4_bull)

def backtest_thuan_tran_m30(use_h4_filter=True, tp1_r=1.2, tp2_r=2.0):
    bars = df_30m.dropna().reset_index()
    trades = []
    in_trade = False
    active_trade = None
    pad = 40.0
    
    for i in range(1, len(bars)):
        row = bars.iloc[i]
        prev_row = bars.iloc[i-1]
        
        # Trade management
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
                    t['curr_sl'] = t['entry']
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
            
        # Entry Logic Thuận Trần (Kháng cự/Hỗ trợ + Quá mua/Quá bán + Nến xác nhận M30)
        o, h, l, c = row['open'], row['high'], row['low'], row['close']
        po, pc = prev_row['open'], prev_row['close']
        rsi = row['rsi']
        bb_low = row['bb_lower']
        bb_up = row['bb_upper']
        sup = row['sup_level']
        res = row['res_level']
        h4_b = row['h4_bull']
        
        body = abs(c - o)
        lower_wick = min(o, c) - l
        upper_wick = h - max(o, c)
        
        # Nến đảo chiều M30
        is_bull_pin = (lower_wick >= 1.4 * body) and (c >= l + 0.6 * (h - l)) and (c >= o)
        is_bull_eng = (c > o) and (pc < po) and (c >= po) and (o <= pc)
        
        is_bear_pin = (upper_wick >= 1.4 * body) and (c <= h - 0.6 * (h - l)) and (c <= o)
        is_bear_eng = (c < o) and (pc > po) and (c <= po) and (o >= pc)
        
        # BUY: Tại vùng Hỗ Trợ (hoặc test dải dưới BB) + Quá bán (RSI < 38) + Nến đảo chiều
        is_buy_oversold = (rsi <= 38.0) or (l <= bb_low)
        is_near_sup = (abs(l - sup) / sup <= 0.008) or (l <= sup and c > sup)
        
        if is_buy_oversold and is_near_sup and (is_bull_pin or is_bull_eng):
            if not use_h4_filter or h4_b == 1:
                entry = c
                sl = l - pad
                dist = entry - sl
                if dist > 0:
                    active_trade = {
                        'side': 'BUY', 'entry': entry, 'sl': sl, 'curr_sl': sl, 'sl_dist': dist,
                        'tp1': entry + tp1_r * dist, 'tp2': entry + tp2_r * dist,
                        'tp1_hit': False, 'remaining_vol': 1.0, 'pnl_r': 0.0
                    }
                    in_trade = True
                    continue
                    
        # SELL: Tại vùng Kháng Cự (hoặc test dải trên BB) + Quá mua (RSI > 62) + Nến đảo chiều
        is_sell_overbought = (rsi >= 62.0) or (h >= bb_up)
        is_near_res = (abs(h - res) / res <= 0.008) or (h >= res and c < res)
        
        if is_sell_overbought and is_near_res and (is_bear_pin or is_bear_eng):
            if not use_h4_filter or h4_b == 0:
                entry = c
                sl = h + pad
                dist = sl - entry
                if dist > 0:
                    active_trade = {
                        'side': 'SELL', 'entry': entry, 'sl': sl, 'curr_sl': sl, 'sl_dist': dist,
                        'tp1': entry - tp1_r * dist, 'tp2': entry - tp2_r * dist,
                        'tp1_hit': False, 'remaining_vol': 1.0, 'pnl_r': 0.0
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
    print("Testing Hệ Thống Thuận Trần ALA Trading trên nến M30 BTCUSDT (3 Năm):")
    res1 = backtest_thuan_tran_m30(use_h4_filter=True, tp1_r=1.2, tp2_r=2.0)
    print("Có lọc Trend H4 (Thuận Xu Hướng Lớn):", res1)
    res2 = backtest_thuan_tran_m30(use_h4_filter=False, tp1_r=1.2, tp2_r=2.0)
    print("Đánh thuần Sideway Cản Cứng (Không lọc H4):", res2)
