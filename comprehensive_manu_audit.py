"""
Comprehensive Backtest and Analysis of Duy Thành (Senpai Thành) 'Ma Nữ' System:
Break of Previous Candle + Perfect Wick Retest
Analyzed on XAUUSDc and BTCUSDc on M30 and H1
Testing TP = 1.0R (Concept Do Nay Thi Truong) vs 1.5R vs 2.0R
"""

import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import datetime

def init_mt5():
    if not mt5.initialize():
        print("MT5 initialize failed:", mt5.last_error())
        return False
    return True

def get_rates(symbol, timeframe, date_from, date_to):
    rates = mt5.copy_rates_range(symbol, timeframe, date_from, date_to)
    if rates is None or len(rates) == 0:
        return None
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df.set_index('time', inplace=True)
    return df

def run_manu_strategy(df, symbol, tp_ratio=1.5, fixed_risk_usd=20.0, initial_capital=2000.0, session_filter=True):
    """
    Simulates the Break of Previous Candle + Perfect Wick Retest setup.
    """
    open_prices = df['open'].values
    high_prices = df['high'].values
    low_prices = df['low'].values
    close_prices = df['close'].values
    volumes = df['tick_volume'].values
    times = df.index
    
    body_high = np.maximum(close_prices, open_prices)
    body_low = np.minimum(close_prices, open_prices)
    
    trades = []
    balance = initial_capital
    peak_balance = initial_capital
    max_dd_usd = 0.0
    max_dd_pct = 0.0
    
    # 30-bar rolling linechart support & resistance
    for i in range(30, len(df) - 1):
        # Session check if enabled (London & NY: 07:00 to 20:00 UTC)
        trade_hour = times[i].hour
        if session_filter and (trade_hour < 7 or trade_hour > 20):
            continue
            
        sub_high = body_high[i-30:i]
        sub_low = body_low[i-30:i]
        
        recent_res = np.max(sub_high[:-1])
        recent_sup = np.min(sub_low[:-1])
        
        # BUY SETUP
        if close_prices[i] > recent_res and close_prices[i-1] <= recent_res:
            break_high = high_prices[i]
            break_close = close_prices[i]
            
            next_low = low_prices[i+1]
            next_high = high_prices[i+1]
            
            # Retest down to/near broken level, then surges past break_high
            if next_low <= break_close and next_high > break_high:
                entry = break_high
                sl = next_low
                risk_dist = entry - sl
                
                min_risk = entry * 0.0005
                if risk_dist >= min_risk:
                    tp = entry + risk_dist * tp_ratio
                    win = False
                    
                    if next_high >= tp:
                        win = True
                    else:
                        for k in range(i+2, min(i+40, len(df))):
                            if low_prices[k] <= sl and high_prices[k] >= tp:
                                win = False
                                break
                            elif low_prices[k] <= sl:
                                win = False
                                break
                            elif high_prices[k] >= tp:
                                win = True
                                break
                                
                    pnl = fixed_risk_usd * tp_ratio if win else -fixed_risk_usd
                    balance += pnl
                    if balance > peak_balance:
                        peak_balance = balance
                    dd = peak_balance - balance
                    dd_pct = (dd / peak_balance) * 100.0 if peak_balance > 0 else 0
                    if dd > max_dd_usd:
                        max_dd_usd = dd
                    if dd_pct > max_dd_pct:
                        max_dd_pct = dd_pct
                        
                    trades.append({
                        'time': times[i+1],
                        'type': 'BUY',
                        'entry': entry,
                        'sl': sl,
                        'tp': tp,
                        'win': win,
                        'pnl': pnl,
                        'balance': balance,
                        'month': times[i+1].strftime('%Y-%m')
                    })
                    
        # SELL SETUP
        elif close_prices[i] < recent_sup and close_prices[i-1] >= recent_sup:
            break_low = low_prices[i]
            break_close = close_prices[i]
            
            next_high = high_prices[i+1]
            next_low = low_prices[i+1]
            
            if next_high >= break_close and next_low < break_low:
                entry = break_low
                sl = next_high
                risk_dist = sl - entry
                
                min_risk = entry * 0.0005
                if risk_dist >= min_risk:
                    tp = entry - risk_dist * tp_ratio
                    win = False
                    
                    if next_low <= tp:
                        win = True
                    else:
                        for k in range(i+2, min(i+40, len(df))):
                            if high_prices[k] >= sl and low_prices[k] <= tp:
                                win = False
                                break
                            elif high_prices[k] >= sl:
                                win = False
                                break
                            elif low_prices[k] <= tp:
                                win = True
                                break
                                
                    pnl = fixed_risk_usd * tp_ratio if win else -fixed_risk_usd
                    balance += pnl
                    if balance > peak_balance:
                        peak_balance = balance
                    dd = peak_balance - balance
                    dd_pct = (dd / peak_balance) * 100.0 if peak_balance > 0 else 0
                    if dd > max_dd_usd:
                        max_dd_usd = dd
                    if dd_pct > max_dd_pct:
                        max_dd_pct = dd_pct
                        
                    trades.append({
                        'time': times[i+1],
                        'type': 'SELL',
                        'entry': entry,
                        'sl': sl,
                        'tp': tp,
                        'win': win,
                        'pnl': pnl,
                        'balance': balance,
                        'month': times[i+1].strftime('%Y-%m')
                    })

    df_trades = pd.DataFrame(trades)
    return df_trades, max_dd_usd, max_dd_pct

if __name__ == "__main__":
    if not init_mt5():
        exit(1)
        
    date_from = datetime.datetime(2024, 1, 1)
    date_to = datetime.datetime.now()
    
    print("=" * 80)
    print("AUDIT HỆ THỐNG MA NỮ (SENPAI THÀNH) - KHUNG M30 VÀ H1 (2024 - 11/2026)")
    print("Fixed Risk: $20 / Trade (1% vốn $2000), Session Filter: London & NY (07:00 - 20:00 UTC)")
    print("=" * 80)
    
    summary_results = []
    
    for symbol in ["XAUUSDc", "BTCUSDc"]:
        for tf, tf_name in [(mt5.TIMEFRAME_M30, "M30"), (mt5.TIMEFRAME_H1, "H1")]:
            df = get_rates(symbol, tf, date_from, date_to)
            if df is None:
                continue
                
            for tp_ratio in [1.0, 1.5, 2.0]:
                df_trades, max_dd_usd, max_dd_pct = run_manu_strategy(df, symbol, tp_ratio=tp_ratio)
                if len(df_trades) > 0:
                    win_count = df_trades['win'].sum()
                    loss_count = len(df_trades) - win_count
                    winrate = (win_count / len(df_trades)) * 100.0
                    net_pnl = df_trades['pnl'].sum()
                    roi = (net_pnl / 2000.0) * 100.0
                    
                    summary_results.append({
                        'Symbol': symbol,
                        'TF': tf_name,
                        'TP_R': f"1:{tp_ratio}R",
                        'Trades': len(df_trades),
                        'Winrate': f"{winrate:.1f}%",
                        'NetPnL': f"${net_pnl:+.1f}",
                        'ROI': f"{roi:+.1f}%",
                        'MaxDD': f"${max_dd_usd:.1f} ({max_dd_pct:.1f}%)"
                    })
                    
    df_summary = pd.DataFrame(summary_results)
    print(df_summary.to_string(index=False))
    
    # Chi tiết tháng của H1 TP 1.5R trên Gold và BTC
    print("\n" + "=" * 80)
    print("CHI TIẾT TỪNG THÁNG CHO KHUNG H1 (TP 1.5R):")
    print("=" * 80)
    for symbol in ["XAUUSDc", "BTCUSDc"]:
        df = get_rates(symbol, mt5.TIMEFRAME_H1, date_from, date_to)
        df_trades, _, _ = run_manu_strategy(df, symbol, tp_ratio=1.5)
        monthly = df_trades.groupby('month').agg(
            total=('win', 'count'),
            wins=('win', lambda x: x.sum()),
            pnl=('pnl', 'sum')
        )
        monthly['winrate'] = (monthly['wins'] / monthly['total']) * 100.0
        print(f"\n--- {symbol} H1 TP 1.5R ---")
        for m, row in monthly.tail(12).iterrows():
            print(f"Tháng {m}: {int(row['total']):2d} lệnh | Thắng: {int(row['wins']):2d} ({row['winrate']:.1f}%) | PnL: ${row['pnl']:+6.1f}")
            
    mt5.shutdown()

