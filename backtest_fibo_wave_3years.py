import os
import sys
import time
import math
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import ccxt

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

# 1. Fetch Binance Historical Data for 3 years
def fetch_binance_ohlcv(symbol="BTC/USDT", timeframe="15m", since_days=365*3):
    exchange = ccxt.binance({
        'enableRateLimit': True,
        'options': {'defaultType': 'future'}
    })
    
    now_ms = exchange.milliseconds()
    since_ms = now_ms - (since_days * 24 * 60 * 60 * 1000)
    
    csv_file = f"cache_{symbol.replace('/', '_')}_{timeframe}_3y.csv"
    if os.path.exists(csv_file):
        log(f"Loading cached data from {csv_file}...")
        df = pd.read_csv(csv_file)
        df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df

    log(f"Fetching {symbol} {timeframe} data from Binance (last {since_days} days)...")
    all_ohlcv = []
    current_since = since_ms
    limit = 1000
    
    while current_since < now_ms:
        try:
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe, since=current_since, limit=limit)
            if not ohlcv or len(ohlcv) == 0:
                break
            all_ohlcv.extend(ohlcv)
            current_since = ohlcv[-1][0] + (1 if timeframe == '1m' else 60000)
            log(f"Fetched {len(all_ohlcv)} bars... up to {datetime.fromtimestamp(ohlcv[-1][0]/1000).strftime('%Y-%m-%d')}")
            if len(ohlcv) < limit:
                break
            time.sleep(exchange.rateLimit / 1000.0)
        except Exception as e:
            log(f"Error fetching: {e}. Retrying...")
            time.sleep(2)
            
    df = pd.DataFrame(all_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df.drop_duplicates(subset=['timestamp'], inplace=True)
    df.sort_values('timestamp', inplace=True)
    df.to_csv(csv_file, index=False)
    df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
    log(f"Saved {len(df)} bars to {csv_file}")
    return df

# 2. Backtest Engine for 3-Step Fibo Wave
def run_fibo_wave_backtest(df_15m, symbol="BTCUSDT", is_gold=False):
    """
    Step 1: H4 EMA20 vs EMA50 (Uptrend: EMA20 > EMA50, Downtrend: EMA20 < EMA50)
    Step 2: H1 Swing wave (Peak=1.0, Trough=0.0).
            Wave amplitude: Strong if amp >= threshold else Slow.
            Target Fibo zone:
            - Strong: 0.500 - 0.618
            - Slow: 0.318 - 0.382
    Step 3: M15 Reversal Candle (Pinbar wick > 1.3 * body or Bull/Bear Engulfing).
            SL at wick extreme (+ buffer).
            TP1: 1.2R (50% chốt lời + dời SL về BE).
            TP2: 2.2R (50% còn lại chốt hết).
    """
    log(f"--- Running 3-Step Fibo Wave Backtest for {symbol} ---")
    
    # Resample to H1 and H4
    df_15m = df_15m.copy()
    df_15m.set_index('datetime', inplace=True)
    
    # H1
    df_1h = df_15m.resample('1h').agg({
        'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'
    }).dropna()
    
    # H4
    df_4h = df_15m.resample('4h').agg({
        'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'
    }).dropna()
    df_4h['ema20'] = df_4h['close'].ewm(span=20, adjust=False).mean()
    df_4h['ema50'] = df_4h['close'].ewm(span=50, adjust=False).mean()
    
    # Reindex/merge H4 trend into H1 or M15 without forward-looking bias
    df_15m['h4_time'] = df_15m.index.floor('4h')
    h4_trend_map = (df_4h['ema20'] > df_4h['ema50']).astype(int) # 1: Bull, 0: Bear
    # Shift H4 by 1 bar to prevent lookahead
    h4_trend_map = h4_trend_map.shift(1)
    df_15m['h4_bull'] = df_15m['h4_time'].map(h4_trend_map)
    
    # Determine H1 swings over rolling window (e.g. 24 bars / 1 day)
    # Shift by 1 bar to prevent lookahead
    h1_rolling_high = df_1h['high'].shift(1).rolling(24).max()
    h1_rolling_low = df_1h['low'].shift(1).rolling(24).min()
    
    df_15m['h1_time'] = df_15m.index.floor('1h')
    df_15m['h1_high'] = df_15m['h1_time'].map(h1_rolling_high)
    df_15m['h1_low'] = df_15m['h1_time'].map(h1_rolling_low)
    
    # Thresholds
    strong_amp_thresh = 50.0 if is_gold else 2500.0
    buffer = 1.0 if is_gold else 30.0
    
    trades = []
    in_trade = False
    active_trade = None
    
    bars = df_15m.dropna().reset_index()
    log(f"Total M15 bars to simulate: {len(bars)}")
    
    for i in range(1, len(bars)):
        row = bars.iloc[i]
        prev_row = bars.iloc[i-1]
        
        # Check active trade
        if in_trade:
            t = active_trade
            c_high = row['high']
            c_low = row['low']
            
            if t['side'] == 'BUY':
                # Check SL
                current_sl = t['curr_sl']
                if c_low <= current_sl:
                    # Stopped out
                    loss_pnl = (current_sl - t['entry']) * t['remaining_vol']
                    t['pnl_r'] += (current_sl - t['entry']) / t['sl_dist'] * t['remaining_vol']
                    t['exit_time'] = row['datetime']
                    t['exit_reason'] = 'SL_BE' if t['tp1_hit'] else 'SL'
                    trades.append(t)
                    in_trade = False
                    continue
                
                # Check TP1
                if not t['tp1_hit'] and c_high >= t['tp1']:
                    t['tp1_hit'] = True
                    t['pnl_r'] += 1.2 * 0.5  # hit 1.2R with 50%
                    t['remaining_vol'] = 0.5
                    t['curr_sl'] = t['entry'] # Move SL to BE
                
                # Check TP2
                if t['tp1_hit'] and c_high >= t['tp2']:
                    t['pnl_r'] += 2.2 * 0.5  # hit 2.2R with 50%
                    t['exit_time'] = row['datetime']
                    t['exit_reason'] = 'TP2'
                    trades.append(t)
                    in_trade = False
                    continue
                    
            elif t['side'] == 'SELL':
                current_sl = t['curr_sl']
                if c_high >= current_sl:
                    t['pnl_r'] += (t['entry'] - current_sl) / t['sl_dist'] * t['remaining_vol']
                    t['exit_time'] = row['datetime']
                    t['exit_reason'] = 'SL_BE' if t['tp1_hit'] else 'SL'
                    trades.append(t)
                    in_trade = False
                    continue
                    
                if not t['tp1_hit'] and c_low <= t['tp1']:
                    t['tp1_hit'] = True
                    t['pnl_r'] += 1.2 * 0.5
                    t['remaining_vol'] = 0.5
                    t['curr_sl'] = t['entry'] # Move SL to BE
                    
                if t['tp1_hit'] and c_low <= t['tp2']:
                    t['pnl_r'] += 2.2 * 0.5
                    t['exit_time'] = row['datetime']
                    t['exit_reason'] = 'TP2'
                    trades.append(t)
                    in_trade = False
                    continue
                    
            # Skip new signal if already in trade
            continue

        # Look for new signal
        h4_bull = row['h4_bull']
        if pd.isna(h4_bull):
            continue
            
        peak = row['h1_high']
        trough = row['h1_low']
        if pd.isna(peak) or pd.isna(trough) or peak <= trough:
            continue
            
        amplitude = peak - trough
        is_strong = amplitude >= strong_amp_thresh
        
        # Candle metrics
        o = row['open']
        h = row['high']
        l = row['low']
        c = row['close']
        body = abs(c - o)
        po = prev_row['open']
        pc = prev_row['close']
        
        # BUY SIGNAL SETUP (Step 1: H4 Bullish)
        if h4_bull == 1:
            # Fibo levels measured from trough (0) to peak (1)
            # Pullback level = peak - ratio * amplitude
            if is_strong:
                # Strong wave -> Deep pullback: 0.500 - 0.618
                fibo_top = peak - 0.500 * amplitude
                fibo_bottom = peak - 0.618 * amplitude
            else:
                # Slow wave -> Shallow pullback: 0.318 - 0.382
                fibo_top = peak - 0.318 * amplitude
                fibo_bottom = peak - 0.382 * amplitude
                
            # Check if current price is in target Fibo zone
            in_fibo_zone = (l <= fibo_top and h >= fibo_bottom)
            if in_fibo_zone:
                # Step 3: Reversal candle confirmation
                lower_wick = min(o, c) - l
                upper_wick = h - max(o, c)
                is_bull_pinbar = (lower_wick >= 1.3 * body) and (c > o or (c >= l + 0.6 * (h - l)))
                is_bull_engulfing = (c > o) and (pc < po) and (c >= po) and (o <= pc)
                
                if is_bull_pinbar or is_bull_engulfing:
                    entry = c
                    sl = l - buffer
                    sl_dist = entry - sl
                    if sl_dist > 0:
                        tp1 = entry + 1.2 * sl_dist
                        tp2 = entry + 2.2 * sl_dist
                        active_trade = {
                            'entry_time': row['datetime'],
                            'side': 'BUY',
                            'entry': entry,
                            'sl': sl,
                            'curr_sl': sl,
                            'sl_dist': sl_dist,
                            'tp1': tp1,
                            'tp2': tp2,
                            'tp1_hit': False,
                            'remaining_vol': 1.0,
                            'pnl_r': 0.0,
                            'wave_type': 'STRONG' if is_strong else 'SLOW',
                            'pattern': 'PINBAR' if is_bull_pinbar else 'ENGULFING'
                        }
                        in_trade = True
                        
        # SELL SIGNAL SETUP (Step 1: H4 Bearish)
        elif h4_bull == 0:
            if is_strong:
                # Strong down wave -> Pullback up to 0.500 - 0.618
                fibo_bottom = trough + 0.500 * amplitude
                fibo_top = trough + 0.618 * amplitude
            else:
                fibo_bottom = trough + 0.318 * amplitude
                fibo_top = trough + 0.382 * amplitude
                
            in_fibo_zone = (h >= fibo_bottom and l <= fibo_top)
            if in_fibo_zone:
                upper_wick = h - max(o, c)
                lower_wick = min(o, c) - l
                is_bear_pinbar = (upper_wick >= 1.3 * body) and (c < o or (c <= h - 0.6 * (h - l)))
                is_bear_engulfing = (c < o) and (pc > po) and (c <= po) and (o >= pc)
                
                if is_bear_pinbar or is_bear_engulfing:
                    entry = c
                    sl = h + buffer
                    sl_dist = sl - entry
                    if sl_dist > 0:
                        tp1 = entry - 1.2 * sl_dist
                        tp2 = entry - 2.2 * sl_dist
                        active_trade = {
                            'entry_time': row['datetime'],
                            'side': 'SELL',
                            'entry': entry,
                            'sl': sl,
                            'curr_sl': sl,
                            'sl_dist': sl_dist,
                            'tp1': tp1,
                            'tp2': tp2,
                            'tp1_hit': False,
                            'remaining_vol': 1.0,
                            'pnl_r': 0.0,
                            'wave_type': 'STRONG' if is_strong else 'SLOW',
                            'pattern': 'PINBAR' if is_bear_pinbar else 'ENGULFING'
                        }
                        in_trade = True

    # Analysis
    res_df = pd.DataFrame(trades)
    log(f"Backtest completed. Total trades generated: {len(res_df)}")
    return res_df

def print_metrics(df_trades, label="BTCUSDT"):
    if df_trades.empty:
        print(f"No trades executed for {label}")
        return
        
    total_trades = len(df_trades)
    wins = df_trades[df_trades['pnl_r'] > 0]
    losses = df_trades[df_trades['pnl_r'] < 0]
    bes = df_trades[df_trades['pnl_r'] == 0]
    
    tp1_hits = df_trades[df_trades['tp1_hit'] == True]
    tp2_hits = df_trades[df_trades['exit_reason'] == 'TP2']
    sl_full = df_trades[df_trades['exit_reason'] == 'SL']
    sl_be = df_trades[df_trades['exit_reason'] == 'SL_BE']
    
    win_rate = (len(wins) / total_trades) * 100
    tp1_rate = (len(tp1_hits) / total_trades) * 100
    tp2_rate = (len(tp2_hits) / total_trades) * 100
    
    total_pnl_r = df_trades['pnl_r'].sum()
    gross_profit = wins['pnl_r'].sum()
    gross_loss = abs(losses['pnl_r'].sum())
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 999.0
    
    # Calculate Max Drawdown in R
    df_trades['cum_r'] = df_trades['pnl_r'].cumsum()
    df_trades['peak_r'] = df_trades['cum_r'].cummax()
    df_trades['drawdown_r'] = df_trades['peak_r'] - df_trades['cum_r']
    max_dd_r = df_trades['drawdown_r'].max()
    
    print("\n" + "="*50)
    print(f"BÁO CÁO KẾT QUẢ BACKTEST 3 NĂM ({label})")
    print("="*50)
    print(f"Thời gian: {df_trades['entry_time'].iloc[0]} -> {df_trades['entry_time'].iloc[-1]}")
    print(f"Tổng số lệnh (Total Trades): {total_trades}")
    print(f"Tỷ lệ chạm TP1 (1.2R): {len(tp1_hits)} lệnh ({tp1_rate:.2f}%)")
    print(f"Tỷ lệ chạm TP2 full (2.2R): {len(tp2_hits)} lệnh ({tp2_rate:.2f}%)")
    print(f"Số lệnh dính SL bảo toàn (BE sau TP1): {len(sl_be)} lệnh")
    print(f"Số lệnh dính Full SL: {len(sl_full)} lệnh ({len(sl_full)/total_trades*100:.2f}%)")
    print(f"Tỷ lệ Thắng (Winrate PnL > 0): {win_rate:.2f}%")
    print(f"Tổng Lợi Nhuận ròng (Net R): +{total_pnl_r:.2f} R")
    print(f"Profit Factor (Gross Win / Gross Loss): {profit_factor:.2f}")
    print(f"Max Drawdown (Sụt giảm vốn tối đa): -{max_dd_r:.2f} R")
    print(f"Lợi nhuận trung bình mỗi lệnh (Expectancy): {total_pnl_r/total_trades:.2f} R / lệnh")
    print("="*50 + "\n")

if __name__ == '__main__':
    # 1. Backtest BTCUSDT 3 years
    df_btc = fetch_binance_ohlcv("BTC/USDT", "15m", since_days=365*3)
    btc_trades = run_fibo_wave_backtest(df_btc, symbol="BTCUSDT", is_gold=False)
    print_metrics(btc_trades, label="BTCUSDT Futures (3 Years)")
