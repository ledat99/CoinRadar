"""
Run full side-by-side monthly comparison between:
1. Bot M5 Scalper (Volume Profile + Secondary Confirmation + TP Sweet Spot 1.2R/2.0R)
2. Bot H1 Ma Nữ (Break of Previous Candle + Perfect Wick Retest + TP 1.5R)
3. Bot M30 Ma Nữ (For BTC)
Export all metrics to markdown table.
"""

import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import datetime

def init_mt5():
    if not mt5.initialize():
        print("MT5 init failed")
        return False
    return True

def get_rates(symbol, tf, date_from, date_to):
    rates = mt5.copy_rates_range(symbol, tf, date_from, date_to)
    if rates is None or len(rates) == 0:
        return None
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df.set_index('time', inplace=True)
    return df

# 1. M5 Scalper Engine (Same as backtest_yearly_compound.py / Solution 2)
def run_m5_scalper(df, symbol, fixed_risk=20.0):
    trades = []
    # Simplified simulation matching our M5 VP Scalper verified parameters
    open_p = df['open'].values
    high_p = df['high'].values
    low_p = df['low'].values
    close_p = df['close'].values
    vol_p = df['tick_volume'].values
    times = df.index
    
    # Rolling Daily Value Area simulation
    # Using previous 288 M5 bars (24 hours)
    for i in range(288, len(df) - 1):
        # London + NY: 07:00 to 20:00 UTC
        if times[i].hour < 7 or times[i].hour > 20:
            continue
            
        sub_c = close_p[i-288:i]
        sub_v = vol_p[i-288:i]
        poc = np.median(sub_c)
        val = np.percentile(sub_c, 15)
        vah = np.percentile(sub_c, 85)
        
        # Long at VAL defense
        if low_p[i] <= val and close_p[i] > val and vol_p[i] > np.mean(sub_v[-20:]) * 1.3:
            entry = close_p[i]
            sl = low_p[i] - (entry * 0.0004)
            risk = entry - sl
            if risk >= (entry * 0.0003):
                tp1 = entry + risk * 1.2
                tp2 = entry + risk * 2.0
                win = False
                pnl = 0.0
                for k in range(i+1, min(i+40, len(df))):
                    if low_p[k] <= sl:
                        pnl = -fixed_risk
                        win = False
                        break
                    elif high_p[k] >= tp2:
                        pnl = fixed_risk * 1.6 # 50% at 1.2R + 50% at 2.0R
                        win = True
                        break
                    elif high_p[k] >= tp1:
                        # hit tp1, SL to BE, check if hits tp2 or BE
                        for m in range(k+1, min(i+40, len(df))):
                            if high_p[m] >= tp2:
                                pnl = fixed_risk * 1.6
                                win = True
                                break
                            elif low_p[m] <= entry:
                                pnl = fixed_risk * 0.6 # 50% at 1.2R, remaining 50% at BE
                                win = True
                                break
                        break
                if pnl != 0:
                    trades.append({
                        'time': times[i],
                        'system': 'M5_SCALP',
                        'symbol': symbol,
                        'win': win,
                        'pnl': pnl,
                        'month': times[i].strftime('%Y-%m'),
                        'sl_dist': risk
                    })
                    
        # Short at VAH defense
        elif high_p[i] >= vah and close_p[i] < vah and vol_p[i] > np.mean(sub_v[-20:]) * 1.3:
            entry = close_p[i]
            sl = high_p[i] + (entry * 0.0004)
            risk = sl - entry
            if risk >= (entry * 0.0003):
                tp1 = entry - risk * 1.2
                tp2 = entry - risk * 2.0
                win = False
                pnl = 0.0
                for k in range(i+1, min(i+40, len(df))):
                    if high_p[k] >= sl:
                        pnl = -fixed_risk
                        win = False
                        break
                    elif low_p[k] <= tp2:
                        pnl = fixed_risk * 1.6
                        win = True
                        break
                    elif low_p[k] <= tp1:
                        for m in range(k+1, min(i+40, len(df))):
                            if low_p[m] <= tp2:
                                pnl = fixed_risk * 1.6
                                win = True
                                break
                            elif high_p[m] >= entry:
                                pnl = fixed_risk * 0.6
                                win = True
                                break
                        break
                if pnl != 0:
                    trades.append({
                        'time': times[i],
                        'system': 'M5_SCALP',
                        'symbol': symbol,
                        'win': win,
                        'pnl': pnl,
                        'month': times[i].strftime('%Y-%m'),
                        'sl_dist': risk
                    })
    return pd.DataFrame(trades)

# 2. H1 Ma Nữ Engine
def run_h1_manu(df, symbol, fixed_risk=20.0, tp_ratio=1.5):
    trades = []
    open_p = df['open'].values
    high_p = df['high'].values
    low_p = df['low'].values
    close_p = df['close'].values
    times = df.index
    
    body_high = np.maximum(close_p, open_p)
    body_low = np.minimum(close_p, open_p)
    
    for i in range(30, len(df) - 1):
        if times[i].hour < 7 or times[i].hour > 20:
            continue
            
        sub_high = body_high[i-30:i]
        sub_low = body_low[i-30:i]
        recent_res = np.max(sub_high[:-1])
        recent_sup = np.min(sub_low[:-1])
        
        # BUY:
        if close_p[i] > recent_res and close_p[i-1] <= recent_res:
            break_high = high_p[i]
            break_close = close_p[i]
            next_low = low_p[i+1]
            next_high = high_p[i+1]
            
            if next_low <= break_close and next_high > break_high:
                entry = break_high
                sl = next_low
                risk = entry - sl
                if risk >= (entry * 0.0005):
                    tp = entry + risk * tp_ratio
                    win = False
                    if next_high >= tp:
                        win = True
                    else:
                        for k in range(i+2, min(i+40, len(df))):
                            if low_p[k] <= sl and high_p[k] >= tp:
                                win = False
                                break
                            elif low_p[k] <= sl:
                                win = False
                                break
                            elif high_p[k] >= tp:
                                win = True
                                break
                    pnl = fixed_risk * tp_ratio if win else -fixed_risk
                    trades.append({
                        'time': times[i+1],
                        'system': 'H1_MANU',
                        'symbol': symbol,
                        'win': win,
                        'pnl': pnl,
                        'month': times[i+1].strftime('%Y-%m'),
                        'sl_dist': risk
                    })
                    
        # SELL:
        elif close_p[i] < recent_sup and close_p[i-1] >= recent_sup:
            break_low = low_p[i]
            break_close = close_p[i]
            next_high = high_p[i+1]
            next_low = low_p[i+1]
            
            if next_high >= break_close and next_low < break_low:
                entry = break_low
                sl = next_high
                risk = sl - entry
                if risk >= (entry * 0.0005):
                    tp = entry - risk * tp_ratio
                    win = False
                    if next_low <= tp:
                        win = True
                    else:
                        for k in range(i+2, min(i+40, len(df))):
                            if high_p[k] >= sl and low_p[k] <= tp:
                                win = False
                                break
                            elif high_p[k] >= sl:
                                win = False
                                break
                            elif low_p[k] <= tp:
                                win = True
                                break
                    pnl = fixed_risk * tp_ratio if win else -fixed_risk
                    trades.append({
                        'time': times[i+1],
                        'system': 'H1_MANU',
                        'symbol': symbol,
                        'win': win,
                        'pnl': pnl,
                        'month': times[i+1].strftime('%Y-%m'),
                        'sl_dist': risk
                    })
    return pd.DataFrame(trades)

if __name__ == "__main__":
    if not init_mt5():
        exit(1)
        
    utc_from = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
    utc_to = datetime.datetime.now(datetime.timezone.utc)
    
    # 1. Run Gold M5 & H1
    df_gold_m5 = get_rates("XAUUSDc", mt5.TIMEFRAME_M5, utc_from, utc_to)
    df_gold_h1 = get_rates("XAUUSDc", mt5.TIMEFRAME_H1, utc_from, utc_to)
    
    # 2. Run BTC M5 & H1
    df_btc_m5 = get_rates("BTCUSDc", mt5.TIMEFRAME_M5, utc_from, utc_to)
    df_btc_h1 = get_rates("BTCUSDc", mt5.TIMEFRAME_H1, utc_from, utc_to)
    
    trades_gold_m5 = run_m5_scalper(df_gold_m5, "XAUUSD")
    trades_gold_h1 = run_h1_manu(df_gold_h1, "XAUUSD")
    
    trades_btc_m5 = run_m5_scalper(df_btc_m5, "BTCUSD")
    trades_btc_h1 = run_h1_manu(df_btc_h1, "BTCUSD")

    
    all_trades = pd.concat([trades_gold_m5, trades_gold_h1, trades_btc_m5, trades_btc_h1])
    
    def summarize(df_sub, name):
        if len(df_sub) == 0:
            return f"{name}: No trades"
        w = df_sub['win'].sum()
        tot = len(df_sub)
        pnl = df_sub['pnl'].sum()
        wr = (w / tot) * 100
        avg_sl = df_sub['sl_dist'].mean()
        # Max drawdown
        cum = df_sub['pnl'].cumsum()
        peak = cum.cummax()
        dd = peak - cum
        max_dd = dd.max()
        return {
            'Name': name,
            'Trades': tot,
            'Wins': w,
            'Losses': tot - w,
            'Winrate': f"{wr:.1f}%",
            'NetPnL': f"${pnl:+.1f}",
            'MaxDD': f"${max_dd:.1f}",
            'AvgSL': f"{avg_sl:.2f}"
        }
        
    print("=== SUMMARY METRICS (12/2025 - 11/2026) ===")
    res = [
        summarize(trades_gold_m5, "Vàng - M5 Scalper"),
        summarize(trades_gold_h1, "Vàng - H1 Ma Nữ"),
        summarize(trades_btc_m5, "BTC - M5 Scalper"),
        summarize(trades_btc_h1, "BTC - H1 Ma Nữ")
    ]
    print(pd.DataFrame(res).to_string(index=False))
    
    # Monthly comparison table
    print("\n=== MONTHLY BREAKDOWN ===")
    months = sorted(list(set(all_trades['month'])))
    monthly_data = []
    for m in months:
        g_m5 = trades_gold_m5[trades_gold_m5['month'] == m]['pnl'].sum()
        g_h1 = trades_gold_h1[trades_gold_h1['month'] == m]['pnl'].sum()
        b_m5 = trades_btc_m5[trades_btc_m5['month'] == m]['pnl'].sum()
        b_h1 = trades_btc_h1[trades_btc_h1['month'] == m]['pnl'].sum()
        monthly_data.append({
            'Tháng': m,
            'Vàng M5 ($)': f"{g_m5:+.1f}",
            'Vàng H1 ($)': f"{g_h1:+.1f}",
            'BTC M5 ($)': f"{b_m5:+.1f}",
            'BTC H1 ($)': f"{b_h1:+.1f}",
            'Tổng M5 ($)': f"{(g_m5+b_m5):+.1f}",
            'Tổng H1 ($)': f"{(g_h1+b_h1):+.1f}"
        })
    print(pd.DataFrame(monthly_data).to_string(index=False))
    mt5.shutdown()
