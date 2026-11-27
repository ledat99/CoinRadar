import pandas as pd
import numpy as np

# Load 3-year M15 data
print("Loading 3-year M15 data...")
df_15m = pd.read_csv('cache_BTC_USDT_15m_3y.csv')
df_15m['datetime'] = pd.to_datetime(df_15m['timestamp'], unit='ms')
df_15m.set_index('datetime', inplace=True)

df_30m = df_15m.resample('30min').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}).dropna()
df_1h = df_15m.resample('1h').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}).dropna()
df_4h = df_15m.resample('4h').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'}).dropna()
df_1d = df_15m.resample('1D').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'}).dropna()

df_4h['ema20'] = df_4h['close'].ewm(span=20, adjust=False).mean()
df_4h['ema50'] = df_4h['close'].ewm(span=50, adjust=False).mean()
h4_bull = (df_4h['ema20'] > df_4h['ema50']).reindex(df_30m.index, method='ffill')

STARTING_CAPITAL = 1000.0
RISK_USD = 10.0 # 1% vốn = 10u mỗi lệnh SL

def run_simulation(signals_df, strat_name="Strategy"):
    bars = signals_df.dropna().reset_index()
    capital = STARTING_CAPITAL
    equity_curve = [capital]
    trades = []
    in_trade = False
    active = None
    
    for i in range(1, len(bars)):
        row = bars.iloc[i]
        
        if in_trade:
            t = active
            c_high = row['high']
            c_low = row['low']
            
            if t['side'] == 'BUY':
                if c_low <= t['curr_sl']:
                    # Exit SL or SL_BE
                    pnl_r = (t['curr_sl'] - t['entry']) / t['sl_dist'] * t['remaining_vol']
                    pnl_usd = pnl_r * RISK_USD
                    t['pnl_r'] += pnl_r
                    t['pnl_usd'] += pnl_usd
                    t['exit_reason'] = 'SL_BE' if t['tp1_hit'] else 'SL'
                    capital += t['pnl_usd']
                    equity_curve.append(capital)
                    trades.append(t)
                    in_trade = False
                    continue
                if not t['tp1_hit'] and c_high >= t['tp1']:
                    t['tp1_hit'] = True
                    r_tp1 = 1.0 * 0.5 # Chốt 50% tại TP1
                    pnl_usd_tp1 = r_tp1 * RISK_USD
                    t['pnl_r'] += r_tp1
                    t['pnl_usd'] += pnl_usd_tp1
                    t['remaining_vol'] = 0.5
                    t['curr_sl'] = t['entry'] # Dời BE
                if t['tp1_hit'] and c_high >= t['tp2']:
                    r_tp2 = 2.0 * 0.5 # Chốt 50% tại TP2
                    pnl_usd_tp2 = r_tp2 * RISK_USD
                    t['pnl_r'] += r_tp2
                    t['pnl_usd'] += pnl_usd_tp2
                    t['exit_reason'] = 'TP2'
                    capital += t['pnl_usd']
                    equity_curve.append(capital)
                    trades.append(t)
                    in_trade = False
                    continue
            elif t['side'] == 'SELL':
                if c_high >= t['curr_sl']:
                    pnl_r = (t['entry'] - t['curr_sl']) / t['sl_dist'] * t['remaining_vol']
                    pnl_usd = pnl_r * RISK_USD
                    t['pnl_r'] += pnl_r
                    t['pnl_usd'] += pnl_usd
                    t['exit_reason'] = 'SL_BE' if t['tp1_hit'] else 'SL'
                    capital += t['pnl_usd']
                    equity_curve.append(capital)
                    trades.append(t)
                    in_trade = False
                    continue
                if not t['tp1_hit'] and c_low <= t['tp1']:
                    t['tp1_hit'] = True
                    r_tp1 = 1.0 * 0.5
                    pnl_usd_tp1 = r_tp1 * RISK_USD
                    t['pnl_r'] += r_tp1
                    t['pnl_usd'] += pnl_usd_tp1
                    t['remaining_vol'] = 0.5
                    t['curr_sl'] = t['entry']
                if t['tp1_hit'] and c_low <= t['tp2']:
                    r_tp2 = 2.0 * 0.5
                    pnl_usd_tp2 = r_tp2 * RISK_USD
                    t['pnl_r'] += r_tp2
                    t['pnl_usd'] += pnl_usd_tp2
                    t['exit_reason'] = 'TP2'
                    capital += t['pnl_usd']
                    equity_curve.append(capital)
                    trades.append(t)
                    in_trade = False
                    continue
            continue
            
        sig = row.get('signal')
        if sig in ['BUY', 'SELL']:
            entry = row['close']
            sl = row['sl']
            sl_dist = abs(entry - sl)
            if sl_dist <= 0:
                continue
            
            # Position sizing: Vốn 1000u, SL = 10u (1%)
            # position_size_btc = RISK_USD / sl_dist
            # position_value_usd = position_size_btc * entry
            pos_size = RISK_USD / sl_dist
            pos_val = pos_size * entry
            
            tp1 = entry + 1.0 * sl_dist if sig == 'BUY' else entry - 1.0 * sl_dist
            tp2 = entry + 2.0 * sl_dist if sig == 'BUY' else entry - 2.0 * sl_dist
            
            active = {
                'side': sig, 'entry': entry, 'sl': sl, 'curr_sl': sl, 'sl_dist': sl_dist,
                'tp1': tp1, 'tp2': tp2, 'tp1_hit': False, 'remaining_vol': 1.0,
                'pnl_r': 0.0, 'pnl_usd': 0.0, 'pos_size': pos_size, 'pos_val': pos_val
            }
            in_trade = True
            
    # Calculate performance metrics
    total_trades = len(trades)
    if total_trades == 0:
        print(f"[{strat_name}] No trades executed.")
        return
        
    wins = len([t for t in trades if t['pnl_usd'] > 0])
    losses = len([t for t in trades if t['pnl_usd'] < 0])
    be = len([t for t in trades if t['pnl_usd'] == 0])
    win_rate = (wins / total_trades) * 100
    total_pnl_usd = capital - STARTING_CAPITAL
    roi_pct = (total_pnl_usd / STARTING_CAPITAL) * 100
    
    # Calculate Max Drawdown
    eq = np.array(equity_curve)
    peak = np.maximum.accumulate(eq)
    dd = (eq - peak) / peak * 100
    max_dd_pct = abs(np.min(dd))
    max_dd_usd = abs(np.min(eq - peak))
    
    # Profit factor
    gross_win = sum([t['pnl_usd'] for t in trades if t['pnl_usd'] > 0])
    gross_loss = abs(sum([t['pnl_usd'] for t in trades if t['pnl_usd'] < 0]))
    pf = (gross_win / gross_loss) if gross_loss > 0 else 999.0
    
    avg_pos_val = np.mean([t['pos_val'] for t in trades])
    avg_leverage = avg_pos_val / STARTING_CAPITAL
    
    print(f"\n==========================================")
    print(f"📊 KẾT QUẢ BACKTEST: {strat_name}")
    print(f"💼 Vốn Ban Đầu: ${STARTING_CAPITAL:,.1f} | Rủi Ro Cố Định: ${RISK_USD:.1f}/lệnh (1.0% Vốn)")
    print(f"==========================================")
    print(f"• Tổng số lệnh: {total_trades:,} kèo")
    print(f"• Thắng (Wins): {wins:,} ({win_rate:.2f}%) | Hoà (BE): {be:,} | Thua (SL): {losses:,}")
    print(f"• Lợi nhuận ròng: {'+' if total_pnl_usd >= 0 else ''}${total_pnl_usd:,.2f} ({'+' if roi_pct >= 0 else ''}{roi_pct:.2f}% ROI)")
    print(f"• Vốn cuối kỳ: ${capital:,.2f}")
    print(f"• Profit Factor (PF): {pf:.2f}")
    print(f"• Max Drawdown: -{max_dd_pct:.2f}% (-${max_dd_usd:,.2f})")
    print(f"• Volume vị thế trung bình: ${avg_pos_val:,.1f} (~Đòn bẩy {avg_leverage:.1f}x)")
    return {
        'name': strat_name, 'trades': total_trades, 'winrate': win_rate,
        'pnl_usd': total_pnl_usd, 'final_cap': capital, 'roi': roi_pct,
        'pf': pf, 'max_dd_pct': max_dd_pct, 'max_dd_usd': max_dd_usd,
        'avg_lev': avg_leverage
    }

# 1. CHIẾN LƯỢC 1: FIBO SÓNG HỒI M30 (H4 Trend + Golden Zone Pullback)
def test_fibo_wave_strategy():
    df = df_30m.copy()
    df['h4_bull'] = h4_bull
    
    # 20-bar Fractal Swings
    rolling_period = 20
    df['sw_high'] = df['high'].shift(1).rolling(rolling_period).max()
    df['sw_low'] = df['low'].shift(1).rolling(rolling_period).min()
    df['wave_range'] = df['sw_high'] - df['sw_low']
    
    df['signal'] = None
    df['sl'] = 0.0
    
    for i in range(rolling_period + 2, len(df)):
        h4_b = df['h4_bull'].iloc[i]
        c = df['close'].iloc[i]
        o = df['open'].iloc[i]
        h = df['high'].iloc[i]
        l = df['low'].iloc[i]
        sw_h = df['sw_high'].iloc[i]
        sw_l = df['sw_low'].iloc[i]
        rng = df['wave_range'].iloc[i]
        
        if rng < 500.0:
            continue
            
        fibo_50 = sw_h - 0.500 * rng
        fibo_618 = sw_h - 0.618 * rng
        fibo_382 = sw_l + 0.382 * rng
        
        # BUY: H4 Bull, Pullback to 0.5 - 0.618, Reversal candle
        if h4_b and (l <= fibo_50) and (c >= fibo_618) and (c > o):
            df.at[df.index[i], 'signal'] = 'BUY'
            df.at[df.index[i], 'sl'] = max(sw_l, c - 400.0)
        # SELL: H4 Bear, Pullback to 0.5 - 0.618
        elif (not h4_b) and (h >= fibo_50) and (c <= fibo_382) and (c < o):
            df.at[df.index[i], 'signal'] = 'SELL'
            df.at[df.index[i], 'sl'] = min(sw_h, c + 400.0)
            
    return run_simulation(df, "1. FIBO SÓNG HỒI (M30 FRACTAL)")

# 2. CHIẾN LƯỢC 2: THUẬN TRẦN ALA TRADING M30 (H4 Trend + EMA20 Retest + Full Force/3N)
def test_thuan_tran_m30_strategy():
    df = df_30m.copy()
    df['h4_bull'] = h4_bull
    df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
    
    df['signal'] = None
    df['sl'] = 0.0
    
    for i in range(5, len(df)):
        h4_b = df['h4_bull'].iloc[i]
        c = df['close'].iloc[i]
        o = df['open'].iloc[i]
        h = df['high'].iloc[i]
        l = df['low'].iloc[i]
        ema = df['ema20'].iloc[i]
        
        # 3 nến trước
        c1_c, c1_o, c1_h, c1_l = df['close'].iloc[i-1], df['open'].iloc[i-1], df['high'].iloc[i-1], df['low'].iloc[i-1]
        c2_c, c2_o = df['close'].iloc[i-2], df['open'].iloc[i-2]
        c3_c = df['close'].iloc[i-3]
        
        body1 = abs(c1_c - c1_o)
        rng1 = max(c1_h - c1_l, 0.01)
        
        # Long
        if h4_b and (c >= ema):
            is_full = (c1_c > c1_o) and (body1 >= 0.58 * rng1) and (c1_l <= ema * 1.002)
            is_3n = (c1_c > c2_c > c3_c) and (min(c1_l, c2_o, c3_c) <= ema * 1.002)
            if is_full or is_3n:
                df.at[df.index[i], 'signal'] = 'BUY'
                df.at[df.index[i], 'sl'] = c - max(abs(c - c1_l) + 50.0, 300.0)
        # Short
        elif (not h4_b) and (c <= ema):
            is_full = (c1_c < c1_o) and (body1 >= 0.58 * rng1) and (c1_h >= ema * 0.998)
            is_3n = (c1_c < c2_c < c3_c) and (max(c1_h, c2_o, c3_c) >= ema * 0.998)
            if is_full or is_3n:
                df.at[df.index[i], 'signal'] = 'SELL'
                df.at[df.index[i], 'sl'] = c + max(abs(c1_h - c) + 50.0, 300.0)
                
    return run_simulation(df, "2. THUẬN TRẦN ALA TRADING (M30 EMA20)")

# 3. CHIẾN LƯỢC 3: VOLUME PROFILE DAILY M30 SCALP
def test_vp_daily_strategy():
    df = df_30m.copy()
    y_high = df_1d['high'].shift(1).reindex(df.index, method='ffill')
    y_low = df_1d['low'].shift(1).reindex(df.index, method='ffill')
    y_close = df_1d['close'].shift(1).reindex(df.index, method='ffill')
    
    y_poc = (y_high + y_low + y_close) / 3.0
    y_vah = y_poc + (y_high - y_low) * 0.35
    y_val = y_poc - (y_high - y_low) * 0.35
    
    df['signal'] = None
    df['sl'] = 0.0
    
    for i in range(5, len(df)):
        c = df['close'].iloc[i]
        o = df['open'].iloc[i]
        l = df['low'].iloc[i]
        h = df['high'].iloc[i]
        val = y_val.iloc[i]
        vah = y_vah.iloc[i]
        
        # BUY at yVAL
        if (l <= val) and (c > val) and (c > o):
            df.at[df.index[i], 'signal'] = 'BUY'
            df.at[df.index[i], 'sl'] = c - max(abs(c - l) + 40.0, 250.0)
        # SELL at yVAH
        elif (h >= vah) and (c < vah) and (c < o):
            df.at[df.index[i], 'signal'] = 'SELL'
            df.at[df.index[i], 'sl'] = c + max(abs(h - c) + 40.0, 250.0)
            
    return run_simulation(df, "3. VOLUME PROFILE DAILY (M30 VP)")

# 4. CHIẾN LƯỢC 4: MA NỮ C7TT (SWEEP LIQUIDITY SWING)
def test_manu_c7tt_strategy():
    df = df_30m.copy()
    rolling_period = 10
    prev_h = df['high'].shift(1).rolling(rolling_period).max()
    prev_l = df['low'].shift(1).rolling(rolling_period).min()
    
    df['signal'] = None
    df['sl'] = 0.0
    
    for i in range(rolling_period + 2, len(df)):
        c = df['close'].iloc[i]
        o = df['open'].iloc[i]
        l = df['low'].iloc[i]
        h = df['high'].iloc[i]
        ph = prev_h.iloc[i]
        pl = prev_l.iloc[i]
        
        # Sweep Low -> Fake breakout to the downside -> Close back above
        if (l < pl) and (c > pl) and (c > o):
            df.at[df.index[i], 'signal'] = 'BUY'
            df.at[df.index[i], 'sl'] = c - max(abs(c - l) + 40.0, 250.0)
        # Sweep High -> Fake breakout to the upside -> Close back below
        elif (h > ph) and (c < ph) and (c < o):
            df.at[df.index[i], 'signal'] = 'SELL'
            df.at[df.index[i], 'sl'] = c + max(abs(h - c) + 40.0, 250.0)
            
    return run_simulation(df, "4. MA NỮ CHIÊU 7 THẦN TĂNG (M30 SWEEP)")

if __name__ == '__main__':
    res1 = test_fibo_wave_strategy()
    res2 = test_thuan_tran_m30_strategy()
    res3 = test_vp_daily_strategy()
    res4 = test_manu_c7tt_strategy()
