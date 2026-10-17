import ccxt
import pandas as pd
import ta
import sys
import warnings

warnings.filterwarnings('ignore')

def run_backtest(symbol='VANRY/USDT', limit=1000):
    binance = ccxt.binance()
    print(f"Đang tải {limit} nến 1h cho {symbol}...")
    try:
        ohlcv = binance.fetch_ohlcv(symbol, '1h', limit=limit)
    except Exception as e:
        print(f"Lỗi: {e}")
        return
        
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    
    # Tính toán chỉ báo giống hệt bot
    df['rsi'] = ta.momentum.RSIIndicator(close=df['close'], window=14).rsi()
    df['sma_volume'] = ta.trend.SMAIndicator(close=df['volume'], window=20).sma_indicator()
    df['ema_20'] = ta.trend.EMAIndicator(close=df['close'], window=20).ema_indicator()
    
    # Tính SMA 3 Đường
    df['sma_open_144'] = ta.trend.SMAIndicator(close=df['open'], window=144).sma_indicator()
    df['sma_high_144'] = ta.trend.SMAIndicator(close=df['high'], window=144).sma_indicator()
    df['sma_low_144'] = ta.trend.SMAIndicator(close=df['low'], window=144).sma_indicator()
    df['avg_3_sma'] = (df['sma_open_144'] + df['sma_high_144'] + df['sma_low_144']) / 3
    
    trades = []
    in_trade = False
    
    entry_price = 0
    sl = 0
    tp1 = 0
    trade_type = None # 'LONG' or 'SHORT'
    
    for i in range(145, len(df)):
        current = df.iloc[i]
        
        # 1. Nếu đang trong một lệnh, kiểm tra xem nó cắn SL hay TP ở nến này
        if in_trade:
            if trade_type == 'LONG':
                if current['low'] <= sl:
                    loss_pct = (sl - entry_price) / entry_price * 100
                    trades.append({'time': current['timestamp'], 'type': 'LOSS', 'pnl': loss_pct})
                    print(f"   🔴 [THUA LONG] Cắt lỗ tại {sl:.4f} ({loss_pct:.2f}%)")
                    in_trade = False
                elif current['high'] >= tp1:
                    win_pct = (tp1 - entry_price) / entry_price * 100
                    trades.append({'time': current['timestamp'], 'type': 'WIN', 'pnl': win_pct})
                    print(f"   🟢 [THẮNG LONG] Chốt lời tại {tp1:.4f} (+{win_pct:.2f}%)")
                    in_trade = False
            elif trade_type == 'SHORT':
                if current['high'] >= sl:
                    loss_pct = (entry_price - sl) / entry_price * 100
                    trades.append({'time': current['timestamp'], 'type': 'LOSS', 'pnl': loss_pct})
                    print(f"   🔴 [THUA SHORT] Cắt lỗ tại {sl:.4f} ({loss_pct:.2f}%)")
                    in_trade = False
                elif current['low'] <= tp1:
                    win_pct = (entry_price - tp1) / entry_price * 100
                    trades.append({'time': current['timestamp'], 'type': 'WIN', 'pnl': win_pct})
                    print(f"   🟢 [THẮNG SHORT] Chốt lời tại {tp1:.4f} (+{win_pct:.2f}%)")
                    in_trade = False
            continue

        # 2. LOGIC TÌM ĐIỂM VÀO (Nếu chưa có lệnh nào)
        crossed_recently_up = False
        crossed_recently_down = False
        
        for j in range(1, 6):
            curr_idx = i - j
            prev_idx = i - j - 1
            if prev_idx >= 0:
                # Check Long cross
                if df['close'].iloc[prev_idx] <= df['avg_3_sma'].iloc[prev_idx] and df['close'].iloc[curr_idx] > df['avg_3_sma'].iloc[curr_idx]:
                    crossed_recently_up = True
                # Check Short cross
                if df['close'].iloc[prev_idx] >= df['avg_3_sma'].iloc[prev_idx] and df['close'].iloc[curr_idx] < df['avg_3_sma'].iloc[curr_idx]:
                    crossed_recently_down = True
                    
        is_above = current['close'] > current['avg_3_sma']
        is_strong_up = current['close'] > (current['avg_3_sma'] * 1.005)
        rsi_bullish = current['rsi'] > 60
        
        is_below = current['close'] < current['avg_3_sma']
        is_strong_down = current['close'] < (current['avg_3_sma'] * 0.995)
        rsi_bearish = current['rsi'] < 40
        
        if crossed_recently_up and is_above and is_strong_up and rsi_bullish:
            in_trade = True
            trade_type = 'LONG'
            entry_price = current['close']
            
            swing_low = df['low'].iloc[i-10:i].min()
            sl = swing_low * 0.99
            if (entry_price - sl) / entry_price > 0.10:
                sl = entry_price * 0.90
                
            risk_amount = entry_price - sl
            tp1 = entry_price + (risk_amount * 1.5)
            trade_time = current['timestamp']
            
            print(f"\n⚡ [TÍN HIỆU LONG] {trade_time} | Entry: {entry_price:.5f} | SL: {sl:.5f} | TP1: {tp1:.5f}")
            
        elif crossed_recently_down and is_below and is_strong_down and rsi_bearish:
            in_trade = True
            trade_type = 'SHORT'
            entry_price = current['close']
            
            swing_high = df['high'].iloc[i-10:i].max()
            sl = swing_high * 1.01
            if (sl - entry_price) / entry_price > 0.10:
                sl = entry_price * 1.10
                
            risk_amount = sl - entry_price
            tp1 = entry_price - (risk_amount * 1.5)
            trade_time = current['timestamp']
            
            print(f"\n⚡ [TÍN HIỆU SHORT] {trade_time} | Entry: {entry_price:.5f} | SL: {sl:.5f} | TP1: {tp1:.5f}")

    # ---- BÁO CÁO THỐNG KÊ ----
    print("\n" + "="*40)
    print(f"📊 BÁO CÁO BACKTEST CHIẾN LƯỢC: {symbol}")
    print(f"Thời gian test: {df.iloc[0]['timestamp']} -> {df.iloc[-1]['timestamp']}")
    print("="*40)
    
    total_trades = len(trades)
    if total_trades == 0:
        print("Không có tín hiệu báo lệnh nào xuất hiện trong 10 ngày qua.")
        return
        
    wins = len([t for t in trades if t['type'] == 'WIN'])
    losses = total_trades - wins
    win_rate = (wins / total_trades) * 100
    total_pnl = sum([t['pnl'] for t in trades])
    
    print(f"Tổng số lệnh đã đánh: {total_trades}")
    print(f"Số lệnh Thắng: {wins} lệnh")
    print(f"Số lệnh Thua: {losses} lệnh")
    print(f"Tỉ lệ thắng (Win Rate): {win_rate:.2f}%")
    print(f"Tổng Lợi Nhuận/Thua Lỗ: {total_pnl:.2f}%")
    print("="*40)
    
    if total_pnl > 0:
        print("✅ KẾT LUẬN: Chiến lược đang CÓ LÃI BỀN VỮNG trên đồng coin này!")
    else:
        print("❌ KẾT LUẬN: Chiến lược đang LỖ, bạn nên điều chỉnh lại SL/TP hoặc chọn coin khác.")

if __name__ == '__main__':
    # Nếu người dùng truyền vào tham số (VD: python backtest.py HMSTR/USDT) thì lấy tham số đó
    symbol_to_test = sys.argv[1] if len(sys.argv) > 1 else 'VANRY/USDT'
    run_backtest(symbol_to_test, limit=1000)
