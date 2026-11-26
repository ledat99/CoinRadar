import os
import sys
import pandas as pd
import numpy as np

# Load 3y data of BTC
df_15m = pd.read_csv("cache_BTC_USDT_15m_3y.csv")
df_15m['datetime'] = pd.to_datetime(df_15m['timestamp'], unit='ms')
df_15m.set_index('datetime', inplace=True)

# Resample to M30, H1, H4
df_30m = df_15m.resample('30min').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}).dropna()
df_4h = df_15m.resample('4h').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'}).dropna()

# H4 Trend Filter: EMA20 vs EMA50
df_4h['ema20'] = df_4h['close'].ewm(span=20, adjust=False).mean()
df_4h['ema50'] = df_4h['close'].ewm(span=50, adjust=False).mean()

# Proper Swing High / Swing Low detection on M30 or H1 (fractal 5-bar / 3-bar swing)
# A swing high is a high with lower highs on both sides (e.g. 5-bar swing)
def detect_swings(df, window=5):
    highs = df['high']
    lows = df['low']
    
    swing_highs = (highs == highs.rolling(2 * window + 1, center=True).max())
    swing_lows = (lows == lows.rolling(2 * window + 1, center=True).min())
    
    return swing_highs, swing_lows

def run_m30_fibo_backtest():
    df = df_30m.copy()
    
    # Map H4 trend
    df['h4_time'] = df.index.floor('4h')
    h4_trend = (df_4h['ema20'] > df_4h['ema50']).astype(int).shift(1)
    df['h4_bull'] = df['h4_time'].map(h4_trend)
    
    # Detect Swings on M30 with 5-bar window (no lookahead: shifted by window bars)
    window = 5
    sh_series = (df['high'] == df['high'].rolling(2 * window + 1, center=True).max())
    sl_series = (df['low'] == df['low'].rolling(2 * window + 1, center=True).min())
    
    # Store confirmed swing points as of bar i
    bars = df.dropna().reset_index()
    
    trades = []
    in_trade = False
    active_trade = None
    
    recent_swing_high = None
    recent_swing_low = None
    
    for i in range(window * 2 + 1, len(bars)):
        row = bars.iloc[i]
        prev_row = bars.iloc[i-1]
        
        # Check if a swing formed window bars ago
        check_idx = i - window
        if sh_series.iloc[check_idx]:
            recent_swing_high = bars.iloc[check_idx]['high']
        if sl_series.iloc[check_idx]:
            recent_swing_low = bars.iloc[check_idx]['low']
            
        # Manage active trade
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
                    t['curr_sl'] = t['entry'] # Move SL to BE
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
            
        # Look for Entry Setup
        if recent_swing_high is None or recent_swing_low is None:
            continue
            
        peak = recent_swing_high
        trough = recent_swing_low
        if peak <= trough:
            continue
            
        amplitude = peak - trough
        if amplitude < 1000: # Wave too small
            continue
            
        is_strong = amplitude >= 2500
        
        o, h, l, c = row['open'], row['high'], row['low'], row['close']
        body = abs(c - o)
        po, pc = prev_row['open'], prev_row['close']
        
        # M30 Reversal Candle Signal definitions:
        # 1. Bullish Pinbar: long bottom wick >= 1.5 * body, closes in upper half
        # 2. Bullish Engulfing: green candle covers previous red candle
        # 3. Inside Bar break / Morning star like
        lower_wick = min(o, c) - l
        upper_wick = h - max(o, c)
        
        is_bull_pin = (lower_wick >= 1.5 * body) and (c >= l + 0.6 * (h - l)) and (c > o)
        is_bull_eng = (c > o) and (pc < po) and (c >= po) and (o <= pc)
        is_bull_reversal = is_bull_pin or is_bull_eng
        
        is_bear_pin = (upper_wick >= 1.5 * body) and (c <= h - 0.6 * (h - l)) and (c < o)
        is_bear_eng = (c < o) and (pc > po) and (c <= po) and (o >= pc)
        is_bear_reversal = is_bear_pin or is_bear_eng
        
        h4_bull = row['h4_bull']
        
        # BUY: H4 Bullish + Pullback into Fibo
        if h4_bull == 1:
            if is_strong:
                fibo_top = peak - 0.500 * amplitude
                fibo_bot = peak - 0.618 * amplitude
            else:
                fibo_top = peak - 0.318 * amplitude
                fibo_bot = peak - 0.382 * amplitude
                
            # Price in Fibo zone and M30 confirmed reversal
            if (l <= fibo_top and h >= fibo_bot) and is_bull_reversal:
                entry = c
                sl = l - 30.0 # SL below signal candle wick
                dist = entry - sl
                if dist > 0:
                    active_trade = {
                        'entry_time': row['datetime'], 'side': 'BUY', 'entry': entry,
                        'sl': sl, 'curr_sl': sl, 'sl_dist': dist,
                        'tp1': entry + 1.2 * dist, 'tp2': entry + 2.0 * dist,
                        'tp1_hit': False, 'remaining_vol': 1.0, 'pnl_r': 0.0
                    }
                    in_trade = True
                    
        # SELL: H4 Bearish + Pullback into Fibo
        elif h4_bull == 0:
            if is_strong:
                fibo_bot = trough + 0.500 * amplitude
                fibo_top = trough + 0.618 * amplitude
            else:
                fibo_bot = trough + 0.318 * amplitude
                fibo_top = trough + 0.382 * amplitude
                
            if (h >= fibo_bot and l <= fibo_top) and is_bear_reversal:
                entry = c
                sl = h + 30.0 # SL above signal candle wick
                dist = sl - entry
                if dist > 0:
                    active_trade = {
                        'entry_time': row['datetime'], 'side': 'SELL', 'entry': entry,
                        'sl': sl, 'curr_sl': sl, 'sl_dist': dist,
                        'tp1': entry - 1.2 * dist, 'tp2': entry - 2.0 * dist,
                        'tp1_hit': False, 'remaining_vol': 1.0, 'pnl_r': 0.0
                    }
                    in_trade = True

    df_res = pd.DataFrame(trades)
    print(f"Total M30 Trades: {len(df_res)}")
    if not df_res.empty:
        wins = df_res[df_res['pnl_r'] > 0]
        tp1_hits = df_res[df_res['tp1_hit'] == True]
        tp2_hits = df_res[df_res['exit_reason'] == 'TP2']
        net_r = df_res['pnl_r'].sum()
        gp = wins['pnl_r'].sum()
        gl = abs(df_res[df_res['pnl_r'] < 0]['pnl_r'].sum())
        pf = gp / gl if gl > 0 else 999
        df_res['cum'] = df_res['pnl_r'].cumsum()
        dd = (df_res['cum'].cummax() - df_res['cum']).max()
        print(f"Winrate: {len(wins)/len(df_res)*100:.2f}%")
        print(f"TP1 Hit: {len(tp1_hits)} ({len(tp1_hits)/len(df_res)*100:.2f}%)")
        print(f"TP2 Hit: {len(tp2_hits)} ({len(tp2_hits)/len(df_res)*100:.2f}%)")
        print(f"Net R: {net_r:.2f} R")
        print(f"Profit Factor: {pf:.2f}")
        print(f"Max DD: {dd:.2f} R")

if __name__ == '__main__':
    run_m30_fibo_backtest()
