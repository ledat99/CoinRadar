import os
import sys
import pandas as pd
import numpy as np

# Load 3y cached BTCUSDT data
df_15m = pd.read_csv("cache_BTC_USDT_15m_3y.csv")
df_15m['datetime'] = pd.to_datetime(df_15m['timestamp'], unit='ms')
df_15m.set_index('datetime', inplace=True)

# Khung M30, H1, H4
df_30m = df_15m.resample('30min').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}).dropna()
df_4h = df_15m.resample('4h').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'}).dropna()

# 1. Khung lớn H4 Trend: Cấu trúc Đỉnh/Đáy hoặc Cụm EMA20 vs EMA50
df_4h['ema20'] = df_4h['close'].ewm(span=20, adjust=False).mean()
df_4h['ema50'] = df_4h['close'].ewm(span=50, adjust=False).mean()
df_4h['trend'] = np.where(df_4h['ema20'] > df_4h['ema50'], 1, -1)
h4_trend = df_4h['trend'].shift(1)

df_30m['h4_trend'] = df_30m.index.floor('4h').map(h4_trend)

# 2. Vùng cản phá vỡ (Break & Retest KeyLevel):
# Khi Trend H4 GIẢM: Tìm Đáy hỗ trợ cũ gần nhất vừa bị đâm thủng (nay thành Kháng cự mới để SELL).
# Khi Trend H4 TĂNG: Tìm Đỉnh kháng cự cũ gần nhất vừa bị phá (nay thành Hỗ trợ mới để BUY).
window = 5
df_30m['sw_h'] = (df_30m['high'] == df_30m['high'].rolling(2 * window + 1, center=True).max())
df_30m['sw_l'] = (df_30m['low'] == df_30m['low'].rolling(2 * window + 1, center=True).min())

def run_thuantran_reel_backtest(tp1_r=1.2, tp2_r=2.5):
    bars = df_30m.dropna().reset_index()
    trades = []
    in_trade = False
    active_trade = None
    pad = 40.0
    
    broken_support = None    # Hỗ trợ bị phá -> Kháng cự để Sell
    broken_resistance = None # Kháng cự bị phá -> Hỗ trợ để Buy
    
    recent_sw_high = None
    recent_sw_low = None
    
    for i in range(window * 2 + 1, len(bars)):
        row = bars.iloc[i]
        prev_row = bars.iloc[i-1]
        
        # Check swing points formed
        check_idx = i - window
        if bars['sw_h'].iloc[check_idx]:
            old_h = recent_sw_high
            recent_sw_high = bars.iloc[check_idx]['high']
            # Nếu giá đã đóng nến vượt qua đỉnh cũ -> Kháng cự bị phá (Breakout)
            if old_h and row['close'] > old_h:
                broken_resistance = old_h
                
        if bars['sw_l'].iloc[check_idx]:
            old_l = recent_sw_low
            recent_sw_low = bars.iloc[check_idx]['low']
            # Nếu giá đã đóng nến đâm thủng đáy cũ -> Hỗ trợ bị phá (Breakdown)
            if old_l and row['close'] < old_l:
                broken_support = old_l
                
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
                    t['curr_sl'] = t['entry'] # Move SL to BE
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
            
        # Entry Setup theo Video Thuận Trần:
        h4_t = row['h4_trend']
        o, h, l, c = row['open'], row['high'], row['low'], row['close']
        po, pc = prev_row['open'], prev_row['close']
        
        body = abs(c - o)
        lower_wick = min(o, c) - l
        upper_wick = h - max(o, c)
        
        # 1. Kịch bản SELL (Đúng như video 25/11):
        # H4 đang Giảm -> Giá hồi lên test lại Hỗ trợ cũ bị phá (broken_support) -> Nến M30 xác nhận rút râu hoặc nhấn chìm đỏ
        if h4_t == -1 and broken_support is not None:
            # Giá test vùng broken_support (+/- 0.6%)
            is_retest_res = (h >= broken_support * 0.995) and (c <= broken_support * 1.008)
            is_pinbar_bear = (upper_wick >= 1.4 * body) and (c <= h - 0.55 * (h - l)) and (c <= o)
            is_engulf_bear = (c < o) and (pc > po) and (c <= po) and (o >= pc)
            
            if is_retest_res and (is_pinbar_bear or is_engulf_bear):
                entry = c
                sl = h + pad # SL mút râu nến tín hiệu
                dist = sl - entry
                if dist > 0:
                    active_trade = {
                        'entry_time': row['datetime'], 'side': 'SELL', 'entry': entry,
                        'sl': sl, 'curr_sl': sl, 'sl_dist': dist,
                        'tp1': entry - tp1_r * dist, 'tp2': entry - tp2_r * dist,
                        'tp1_hit': False, 'remaining_vol': 1.0, 'pnl_r': 0.0,
                        'pattern': 'Bearish Pinbar' if is_pinbar_bear else 'Bearish Engulfing'
                    }
                    in_trade = True
                    broken_support = None # Đã dùng vùng retest này
                    continue
                    
        # 2. Kịch bản BUY:
        # H4 đang Tăng -> Giá hồi về test lại Kháng cự cũ bị phá (broken_resistance) -> Nến M30 xác nhận rút chân hoặc nhấn chìm xanh
        elif h4_t == 1 and broken_resistance is not None:
            is_retest_sup = (l <= broken_resistance * 1.005) and (c >= broken_resistance * 0.992)
            is_pinbar_bull = (lower_wick >= 1.4 * body) and (c >= l + 0.55 * (h - l)) and (c >= o)
            is_engulf_bull = (c > o) and (pc < po) and (c >= po) and (o <= pc)
            
            if is_retest_sup and (is_pinbar_bull or is_engulf_bull):
                entry = c
                sl = l - pad
                dist = entry - sl
                if dist > 0:
                    active_trade = {
                        'entry_time': row['datetime'], 'side': 'BUY', 'entry': entry,
                        'sl': sl, 'curr_sl': sl, 'sl_dist': dist,
                        'tp1': entry + tp1_r * dist, 'tp2': entry + tp2_r * dist,
                        'tp1_hit': False, 'remaining_vol': 1.0, 'pnl_r': 0.0,
                        'pattern': 'Bullish Pinbar' if is_pinbar_bull else 'Bullish Engulfing'
                    }
                    in_trade = True
                    broken_resistance = None
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
    print("--- BACKTEST CHIẾN THUẬT VIDEO REEL THUẬN TRẦN (3 NĂM BTC M30) ---")
    print(run_thuantran_reel_backtest(tp1_r=1.2, tp2_r=2.0))
    print("Với TP2 = 2.5R (Gồng xa):")
    print(run_thuantran_reel_backtest(tp1_r=1.2, tp2_r=2.5))
