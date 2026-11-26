import os
import sys
import pandas as pd
import numpy as np

# Load 3y data of BTCUSDT M15
df_15m = pd.read_csv("cache_BTC_USDT_15m_3y.csv")
df_15m['datetime'] = pd.to_datetime(df_15m['timestamp'], unit='ms')
df_15m.set_index('datetime', inplace=True)

# Resample to M30, H1, H4, D1
df_30m = df_15m.resample('30min').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}).dropna()
df_1h = df_15m.resample('1h').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}).dropna()
df_4h = df_15m.resample('4h').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}).dropna()
df_1d = df_15m.resample('1D').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}).dropna()

# Engine helper to simulate trades with TP1 (1.2R, close 50% + move BE), TP2 (2.0R, close remaining)
def simulate_engine(signals_df, label="Strategy"):
    bars = signals_df.dropna().reset_index()
    trades = []
    in_trade = False
    active_trade = None
    
    for i in range(1, len(bars)):
        row = bars.iloc[i]
        
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
            
        sig = row.get('signal')
        if sig in ['BUY', 'SELL']:
            entry = row['close']
            sl = row['sl']
            sl_dist = abs(entry - sl)
            if sl_dist <= 0:
                continue
            tp1 = entry + 1.2 * sl_dist if sig == 'BUY' else entry - 1.2 * sl_dist
            tp2 = entry + 2.0 * sl_dist if sig == 'BUY' else entry - 2.0 * sl_dist
            active_trade = {
                'side': sig, 'entry': entry, 'sl': sl, 'curr_sl': sl, 'sl_dist': sl_dist,
                'tp1': tp1, 'tp2': tp2, 'tp1_hit': False, 'remaining_vol': 1.0, 'pnl_r': 0.0
            }
            in_trade = True

    df_res = pd.DataFrame(trades)
    if df_res.empty:
        return {'label': label, 'total': 0, 'winrate': 0, 'net_r': 0, 'pf': 0, 'max_dd': 0, 'tp1_rate': 0, 'tp2_rate': 0}
        
    total = len(df_res)
    wins = df_res[df_res['pnl_r'] > 0]
    tp1_hits = df_res[df_res['tp1_hit'] == True]
    tp2_hits = df_res[df_res['exit_reason'] == 'TP2']
    net_r = df_res['pnl_r'].sum()
    gp = wins['pnl_r'].sum()
    gl = abs(df_res[df_res['pnl_r'] < 0]['pnl_r'].sum())
    pf = (gp / gl) if gl > 0 else 999.0
    df_res['cum'] = df_res['pnl_r'].cumsum()
    max_dd = (df_res['cum'].cummax() - df_res['cum']).max()
    
    return {
        'label': label,
        'total': total,
        'winrate': round(len(wins) / total * 100, 2),
        'tp1_rate': round(len(tp1_hits) / total * 100, 2),
        'tp2_rate': round(len(tp2_hits) / total * 100, 2),
        'net_r': round(net_r, 2),
        'pf': round(pf, 2),
        'max_dd': round(max_dd, 2)
    }

# ==========================================
# 1. PHƯƠNG PHÁP 1: VOLUME PROFILE SCALP (Áp dụng trên M30)
# ==========================================
def test_volume_profile_m30():
    df = df_30m.copy()
    
    # Calculate Previous Day High (yVAH), Low (yVAL), and Close as proxy for Value Area
    y_high = df_1d['high'].shift(1)
    y_low = df_1d['low'].shift(1)
    y_close = df_1d['close'].shift(1)
    
    df['d_date'] = df.index.date
    df['y_vah'] = df.index.floor('1D').map(y_high)
    df['y_val'] = df.index.floor('1D').map(y_low)
    
    # 20-period rolling volume average on M30
    df['vol_ma'] = df['volume'].rolling(20).mean()
    
    signals = []
    sls = []
    
    for i in range(1, len(df)):
        o = df['open'].iloc[i]
        h = df['high'].iloc[i]
        l = df['low'].iloc[i]
        c = df['close'].iloc[i]
        v = df['volume'].iloc[i]
        v_ma = df['vol_ma'].iloc[i]
        y_vah = df['y_vah'].iloc[i]
        y_val = df['y_val'].iloc[i]
        
        body = abs(c - o)
        lower_wick = min(o, c) - l
        upper_wick = h - max(o, c)
        
        sig = None
        sl = None
        
        # BUY: Giá test yVAL (hoặc quét dưới yVAL) + Rút chân + Nổ Vol M30
        if pd.notna(y_val) and l <= y_val and c > y_val:
            if lower_wick >= 1.3 * body and v >= 1.2 * v_ma and c >= o:
                sig = 'BUY'
                sl = l - 30.0
                
        # SELL: Giá test yVAH (hoặc quét trên yVAH) + Rút râu + Nổ Vol M30
        elif pd.notna(y_vah) and h >= y_vah and c < y_vah:
            if upper_wick >= 1.3 * body and v >= 1.2 * v_ma and c <= o:
                sig = 'SELL'
                sl = h + 30.0
                
        signals.append(sig)
        sls.append(sl)
        
    df['signal'] = [None] + signals
    df['sl'] = [None] + sls
    return simulate_engine(df, label="1. Volume Profile Scalp (M30)")

# ==========================================
# 2. PHƯƠNG PHÁP 2: MA NỮ - CHIÊU 7 THẦN TĂNG C7TT (Áp dụng trên M30)
# ==========================================
def test_manu_c7tt_m30():
    df = df_30m.copy()
    
    # Rolling 10-bar Swing High & Swing Low on M30
    df['prev_high'] = df['high'].shift(1).rolling(10).max()
    df['prev_low'] = df['low'].shift(1).rolling(10).min()
    
    signals = []
    sls = []
    
    for i in range(1, len(df)):
        o = df['open'].iloc[i]
        h = df['high'].iloc[i]
        l = df['low'].iloc[i]
        c = df['close'].iloc[i]
        po = df['open'].iloc[i-1]
        pc = df['close'].iloc[i-1]
        
        sw_h = df['prev_high'].iloc[i]
        sw_l = df['prev_low'].iloc[i]
        
        body = abs(c - o)
        lower_wick = min(o, c) - l
        upper_wick = h - max(o, c)
        
        sig = None
        sl = None
        
        # C7TT LONG: Quét râu qua Swing Low trước đó (Sweep liquidity) nhưng đóng nến rút chân nằm trên Swing Low
        if pd.notna(sw_l) and l < sw_l and c > sw_l:
            is_pinbar = (lower_wick >= 1.4 * body) and (c >= o)
            is_engulf = (c > o) and (pc < po) and (c >= po)
            if is_pinbar or is_engulf:
                sig = 'BUY'
                sl = l - 30.0
                
        # C7TT SHORT: Quét râu qua Swing High trước đó (Sweep liquidity) nhưng đóng nến rút râu nằm dưới Swing High
        elif pd.notna(sw_h) and h > sw_h and c < sw_h:
            is_pinbar = (upper_wick >= 1.4 * body) and (c <= o)
            is_engulf = (c < o) and (pc > po) and (c <= po)
            if is_pinbar or is_engulf:
                sig = 'SELL'
                sl = h + 30.0
                
        signals.append(sig)
        sls.append(sl)
        
    df['signal'] = [None] + signals
    df['sl'] = [None] + sls
    return simulate_engine(df, label="2. Ma Nữ C7TT (Sweep Liquidity M30)")

# ==========================================
# 3. PHƯƠNG PHÁP 3: FIBO SÓNG HỒI 3 BƯỚC MỚI (M30)
# ==========================================
def test_fibo_wave_m30():
    import test_m30_fibo
    # Run the exact backtest logic
    df = df_30m.copy()
    df_4h_local = df_15m.resample('4h').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'}).dropna()
    df_4h_local['ema20'] = df_4h_local['close'].ewm(span=20, adjust=False).mean()
    df_4h_local['ema50'] = df_4h_local['close'].ewm(span=50, adjust=False).mean()
    
    df['h4_time'] = df.index.floor('4h')
    df['h4_bull'] = df['h4_time'].map((df_4h_local['ema20'] > df_4h_local['ema50']).astype(int).shift(1))
    
    window = 5
    sh_series = (df['high'] == df['high'].rolling(2 * window + 1, center=True).max())
    sl_series = (df['low'] == df['low'].rolling(2 * window + 1, center=True).min())
    
    bars = df.dropna().reset_index()
    signals = []
    sls = []
    
    recent_sh = None
    recent_sl = None
    
    for i in range(len(bars)):
        if i >= window:
            check_idx = i - window
            if sh_series.iloc[check_idx]:
                recent_sh = bars.iloc[check_idx]['high']
            if sl_series.iloc[check_idx]:
                recent_sl = bars.iloc[check_idx]['low']
                
        if i == 0 or recent_sh is None or recent_sl is None:
            signals.append(None)
            sls.append(None)
            continue
            
        peak = recent_sh
        trough = recent_sl
        amp = peak - trough
        if amp < 1000:
            signals.append(None)
            sls.append(None)
            continue
            
        is_strong = amp >= 2500
        o, h, l, c = bars.iloc[i]['open'], bars.iloc[i]['high'], bars.iloc[i]['low'], bars.iloc[i]['close']
        po, pc = bars.iloc[i-1]['open'], bars.iloc[i-1]['close']
        body = abs(c - o)
        lower_wick = min(o, c) - l
        upper_wick = h - max(o, c)
        
        is_bull_pin = (lower_wick >= 1.5 * body) and (c >= l + 0.6 * (h - l)) and (c > o)
        is_bull_eng = (c > o) and (pc < po) and (c >= po) and (o <= pc)
        is_bull_rev = is_bull_pin or is_bull_eng
        
        is_bear_pin = (upper_wick >= 1.5 * body) and (c <= h - 0.6 * (h - l)) and (c < o)
        is_bear_eng = (c < o) and (pc > po) and (c <= po) and (o >= pc)
        is_bear_rev = is_bear_pin or is_bear_eng
        
        sig = None
        sl = None
        
        if bars.iloc[i]['h4_bull'] == 1:
            fibo_top = peak - (0.500 if is_strong else 0.318) * amp
            fibo_bot = peak - (0.618 if is_strong else 0.382) * amp
            if l <= fibo_top and h >= fibo_bot and is_bull_rev:
                sig = 'BUY'
                sl = l - 30.0
        elif bars.iloc[i]['h4_bull'] == 0:
            fibo_bot = trough + (0.500 if is_strong else 0.318) * amp
            fibo_top = trough + (0.618 if is_strong else 0.382) * amp
            if h >= fibo_bot and l <= fibo_top and is_bear_rev:
                sig = 'SELL'
                sl = h + 30.0
                
        signals.append(sig)
        sls.append(sl)
        
    bars['signal'] = signals
    bars['sl'] = sls
    bars.set_index('datetime', inplace=True)
    return simulate_engine(bars, label="3. Fibo Sóng Hồi 3 Bước (M30)")

if __name__ == '__main__':
    print("--- CHẠY BACKTEST SO SÁNH 3 PHƯƠNG PHÁP TRÊN NẾN M30 (3 NĂM BTC) ---")
    r1 = test_volume_profile_m30()
    r2 = test_manu_c7tt_m30()
    r3 = test_fibo_wave_m30()
    
    res = [r1, r2, r3]
    df_compare = pd.DataFrame(res)
    print("\n" + "="*80)
    print(df_compare.to_string(index=False))
    print("="*80)
