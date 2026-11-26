import os
import sys
import pandas as pd
import numpy as np

# Load 3y cached BTCUSDT M15 data
df_15m = pd.read_csv("cache_BTC_USDT_15m_3y.csv")
df_15m['datetime'] = pd.to_datetime(df_15m['timestamp'], unit='ms')
df_15m.set_index('datetime', inplace=True)

df_30m = df_15m.resample('30min').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}).dropna()
df_4h = df_15m.resample('4h').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'}).dropna()

# RSI 14
def calc_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / (loss + 1e-9)
    return 100 - (100 / (1 + rs))

df_30m['rsi'] = calc_rsi(df_30m['close'], 14)

# Fractal Swing High / Low (5 bars)
window = 5
df_30m['sw_h'] = (df_30m['high'] == df_30m['high'].rolling(2 * window + 1, center=True).max())
df_30m['sw_l'] = (df_30m['low'] == df_30m['low'].rolling(2 * window + 1, center=True).min())

# Divergence detection & Strong Key Zone Rejection
def test_improved_thuantran():
    bars = df_30m.dropna().reset_index()
    trades = []
    in_trade = False
    active_trade = None
    pad = 40.0
    
    # Store confirmed swing points
    recent_sw_high = None
    recent_sw_low = None
    recent_sw_high_rsi = None
    recent_sw_low_rsi = None
    
    for i in range(window * 2 + 1, len(bars)):
        row = bars.iloc[i]
        prev_row = bars.iloc[i-1]
        
        # Check if swing formed window bars ago
        check_idx = i - window
        if bars['sw_h'].iloc[check_idx]:
            recent_sw_high = bars.iloc[check_idx]['high']
            recent_sw_high_rsi = bars.iloc[check_idx]['rsi']
        if bars['sw_l'].iloc[check_idx]:
            recent_sw_low = bars.iloc[check_idx]['low']
            recent_sw_low_rsi = bars.iloc[check_idx]['rsi']
            
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
                    t['pnl_r'] += 1.2 * 0.5
                    t['remaining_vol'] = 0.5
                    t['curr_sl'] = t['entry']
                if t['tp1_hit'] and c_high >= t['tp2']:
                    t['pnl_r'] += 2.0 * 0.5
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
                    t['pnl_r'] += 1.2 * 0.5
                    t['remaining_vol'] = 0.5
                    t['curr_sl'] = t['entry']
                if t['tp1_hit'] and c_low <= t['tp2']:
                    t['pnl_r'] += 2.0 * 0.5
                    t['exit_reason'] = 'TP2'
                    trades.append(t)
                    in_trade = False
                    continue
            continue
            
        if recent_sw_high is None or recent_sw_low is None:
            continue
            
        o, h, l, c = row['open'], row['high'], row['low'], row['close']
        po, pc = prev_row['open'], prev_row['close']
        rsi = row['rsi']
        
        body = abs(c - o)
        lower_wick = min(o, c) - l
        upper_wick = h - max(o, c)
        
        # BUY: Quét râu qua đáy hỗ trợ (Sweep recent low) VÀ có Phân kỳ Dương RSI (Giá tạo đáy sâu hơn nhưng RSI đáy cao hơn)
        is_bull_div = (l <= recent_sw_low) and (rsi > recent_sw_low_rsi) and (rsi <= 40)
        is_bull_reversal = ((lower_wick >= 1.5 * body) and c >= o) or ((c > o) and (pc < po) and (c >= po))
        
        if is_bull_div and is_bull_reversal and c > recent_sw_low:
            entry = c
            sl = l - pad
            dist = entry - sl
            if dist > 0:
                active_trade = {
                    'side': 'BUY', 'entry': entry, 'sl': sl, 'curr_sl': sl, 'sl_dist': dist,
                    'tp1': entry + 1.2 * dist, 'tp2': entry + 2.0 * dist,
                    'tp1_hit': False, 'remaining_vol': 1.0, 'pnl_r': 0.0
                }
                in_trade = True
                continue
                
        # SELL: Quét râu qua đỉnh kháng cự (Sweep recent high) VÀ có Phân kỳ Âm RSI (Giá tạo đỉnh cao hơn nhưng RSI đỉnh thấp hơn)
        is_bear_div = (h >= recent_sw_high) and (rsi < recent_sw_high_rsi) and (rsi >= 60)
        is_bear_reversal = ((upper_wick >= 1.5 * body) and c <= o) or ((c < o) and (pc > po) and (c <= po))
        
        if is_bear_div and is_bear_reversal and c < recent_sw_high:
            entry = c
            sl = h + pad
            dist = sl - entry
            if dist > 0:
                active_trade = {
                    'side': 'SELL', 'entry': entry, 'sl': sl, 'curr_sl': sl, 'sl_dist': dist,
                    'tp1': entry - 1.2 * dist, 'tp2': entry - 2.0 * dist,
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

print("Kết quả Thuận Trần Nâng Cấp (Cản Cứng + Phân Kỳ RSI + Nến Rút Chân M30):", test_improved_thuantran())
