import os
import sys
import pandas as pd
import numpy as np

# Load the cached 3y data of BTC
df_15m = pd.read_csv("cache_BTC_USDT_15m_3y.csv")
df_15m['datetime'] = pd.to_datetime(df_15m['timestamp'], unit='ms')
df_15m.set_index('datetime', inplace=True)

df_1h = df_15m.resample('1h').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'}).dropna()
df_4h = df_15m.resample('4h').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'}).dropna()

df_4h['ema20'] = df_4h['close'].ewm(span=20, adjust=False).mean()
df_4h['ema50'] = df_4h['close'].ewm(span=50, adjust=False).mean()
df_4h['ema200'] = df_4h['close'].ewm(span=200, adjust=False).mean()

# Check different variants
# Variant A: Standard (as tested)
# Variant B: Only Strong Waves (amplitude >= 3000 USD) & Deep Fibo (0.5 - 0.618)
# Variant C: Add Trend Strength Filter (H4 EMA20 > EMA50 AND close > EMA200)
# Variant D: Only Engulfing or High Quality Pinbar (wick >= 2.0 * body)

def simulate_variant(min_amp=2500, only_strong=False, wick_ratio=1.3, h4_200=False, r_tp1=1.5, r_tp2=3.0):
    df_m = df_15m.copy()
    df_m['h4_time'] = df_m.index.floor('4h')
    
    if h4_200:
        h4_bull = ((df_4h['ema20'] > df_4h['ema50']) & (df_4h['close'] > df_4h['ema200'])).astype(int).shift(1)
        h4_bear = ((df_4h['ema20'] < df_4h['ema50']) & (df_4h['close'] < df_4h['ema200'])).astype(int).shift(1)
    else:
        h4_bull = (df_4h['ema20'] > df_4h['ema50']).astype(int).shift(1)
        h4_bear = (df_4h['ema20'] < df_4h['ema50']).astype(int).shift(1)
        
    df_m['h4_bull'] = df_m['h4_time'].map(h4_bull)
    df_m['h4_bear'] = df_m['h4_time'].map(h4_bear)
    
    h1_high = df_1h['high'].shift(1).rolling(24).max()
    h1_low = df_1h['low'].shift(1).rolling(24).min()
    df_m['h1_high'] = df_m.index.floor('1h').map(h1_high)
    df_m['h1_low'] = df_m.index.floor('1h').map(h1_low)
    
    bars = df_m.dropna().reset_index()
    trades = []
    in_trade = False
    active_trade = None
    buffer = 30.0
    
    for i in range(1, len(bars)):
        row = bars.iloc[i]
        prev_row = bars.iloc[i-1]
        
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
                    t['pnl_r'] += r_tp1 * 0.5
                    t['remaining_vol'] = 0.5
                    t['curr_sl'] = t['entry']
                if t['tp1_hit'] and c_high >= t['tp2']:
                    t['pnl_r'] += r_tp2 * 0.5
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
                    t['pnl_r'] += r_tp1 * 0.5
                    t['remaining_vol'] = 0.5
                    t['curr_sl'] = t['entry']
                if t['tp1_hit'] and c_low <= t['tp2']:
                    t['pnl_r'] += r_tp2 * 0.5
                    t['exit_reason'] = 'TP2'
                    trades.append(t)
                    in_trade = False
                    continue
            continue
            
        peak = row['h1_high']
        trough = row['h1_low']
        amplitude = peak - trough
        is_strong = amplitude >= min_amp
        
        if only_strong and not is_strong:
            continue
            
        o, h, l, c = row['open'], row['high'], row['low'], row['close']
        body = abs(c - o)
        po, pc = prev_row['open'], prev_row['close']
        
        # BUY
        if row['h4_bull'] == 1:
            if is_strong:
                fibo_top = peak - 0.500 * amplitude
                fibo_bot = peak - 0.618 * amplitude
            else:
                fibo_top = peak - 0.318 * amplitude
                fibo_bot = peak - 0.382 * amplitude
                
            if l <= fibo_top and h >= fibo_bot:
                lower_wick = min(o, c) - l
                is_pin = (lower_wick >= wick_ratio * body) and (c >= l + 0.55 * (h - l))
                is_eng = (c > o) and (pc < po) and (c >= po) and (o <= pc)
                if is_pin or is_eng:
                    entry = c
                    sl = l - buffer
                    dist = entry - sl
                    if dist > 0:
                        active_trade = {
                            'side': 'BUY', 'entry': entry, 'sl': sl, 'curr_sl': sl, 'sl_dist': dist,
                            'tp1': entry + r_tp1 * dist, 'tp2': entry + r_tp2 * dist,
                            'tp1_hit': False, 'remaining_vol': 1.0, 'pnl_r': 0.0
                        }
                        in_trade = True
                        
        # SELL
        elif row['h4_bear'] == 1:
            if is_strong:
                fibo_bot = trough + 0.500 * amplitude
                fibo_top = trough + 0.618 * amplitude
            else:
                fibo_bot = trough + 0.318 * amplitude
                fibo_top = trough + 0.382 * amplitude
                
            if h >= fibo_bot and l <= fibo_top:
                upper_wick = h - max(o, c)
                is_pin = (upper_wick >= wick_ratio * body) and (c <= h - 0.55 * (h - l))
                is_eng = (c < o) and (pc > po) and (c <= po) and (o >= pc)
                if is_pin or is_eng:
                    entry = c
                    sl = h + buffer
                    dist = sl - entry
                    if dist > 0:
                        active_trade = {
                            'side': 'SELL', 'entry': entry, 'sl': sl, 'curr_sl': sl, 'sl_dist': dist,
                            'tp1': entry - r_tp1 * dist, 'tp2': entry - r_tp2 * dist,
                            'tp1_hit': False, 'remaining_vol': 1.0, 'pnl_r': 0.0
                        }
                        in_trade = True

    df_res = pd.DataFrame(trades)
    if df_res.empty:
        return 0, 0, 0, 0, 0
    total = len(df_res)
    win_cnt = len(df_res[df_res['pnl_r'] > 0])
    pnl = df_res['pnl_r'].sum()
    gp = df_res[df_res['pnl_r'] > 0]['pnl_r'].sum()
    gl = abs(df_res[df_res['pnl_r'] < 0]['pnl_r'].sum())
    pf = (gp / gl) if gl > 0 else 999
    
    df_res['cum'] = df_res['pnl_r'].cumsum()
    dd = (df_res['cum'].cummax() - df_res['cum']).max()
    return total, win_cnt/total*100, pnl, pf, dd

print("Testing variants on 3 Years BTCUSDT:")
print("Variant 1 (Original):", simulate_variant(min_amp=2500, only_strong=False, wick_ratio=1.3, h4_200=False, r_tp1=1.2, r_tp2=2.2))
print("Variant 2 (Chỉ đánh sóng mạnh Fibo 0.5-0.618, bỏ sóng chậm):", simulate_variant(min_amp=2500, only_strong=True, wick_ratio=1.3, h4_200=False, r_tp1=1.2, r_tp2=2.2))
print("Variant 3 (Chỉ sóng mạnh + Nến Pinbar chất lượng cao wick >= 2.0*body):", simulate_variant(min_amp=2500, only_strong=True, wick_ratio=2.0, h4_200=False, r_tp1=1.2, r_tp2=2.2))
print("Variant 4 (Chỉ sóng mạnh + Lọc thêm H4 theo EMA200):", simulate_variant(min_amp=2500, only_strong=True, wick_ratio=1.5, h4_200=True, r_tp1=1.2, r_tp2=2.2))
print("Variant 5 (Sóng mạnh + EMA200 + R:R 1.5R & 3R):", simulate_variant(min_amp=2500, only_strong=True, wick_ratio=1.5, h4_200=True, r_tp1=1.5, r_tp2=3.0))
