import ccxt
import pandas as pd
import ta
import requests
import time
from datetime import datetime
import json
import os

# --- CONFIGURATION ---
ACTIVE_TRADES_FILE = 'active_trades.json'
# Bạn cần thay thế Token và Chat ID của bạn vào đây
TELEGRAM_BOT_TOKEN = 'YOUR_TELEGRAM_BOT_TOKEN'
TELEGRAM_CHAT_ID = 'YOUR_TELEGRAM_CHAT_ID'

# Khởi tạo sàn Binance (Spot)
binance = ccxt.binance({
    'enableRateLimit': True,
    'options': {
        'defaultType': 'future',
    }
})

# Khởi tạo sàn BingX
bingx = ccxt.bingx({
    'enableRateLimit': True,
})

def send_telegram_message(message):
    """Hàm gửi tin nhắn về Telegram"""
    if TELEGRAM_BOT_TOKEN == 'YOUR_TELEGRAM_BOT_TOKEN':
        print("\n" + "="*40)
        print("TÍN HIỆU TỪ BOT (Cần cấu hình Telegram để nhận qua app):")
        print(message.replace('<b>', '').replace('</b>', '').replace('<a href=', '').replace('</a>', ''))
        print("="*40 + "\n")
        return
        
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Lỗi gửi Telegram: {e}")

def load_active_trades():
    if os.path.exists(ACTIVE_TRADES_FILE):
        try:
            with open(ACTIVE_TRADES_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Lỗi đọc file {ACTIVE_TRADES_FILE}: {e}")
            return []
    return []

def save_active_trades(trades):
    try:
        with open(ACTIVE_TRADES_FILE, 'w') as f:
            json.dump(trades, f, indent=4)
    except Exception as e:
        print(f"Lỗi lưu file {ACTIVE_TRADES_FILE}: {e}")



def get_lowcap_usdt_pairs(bingx_symbols, min_volume_usd=5000000, max_volume_usd=50000000000):
    """
    Lọc các cặp giao dịch Spot USDT trên Binance có Volume 24h nằm trong khoảng min - max, VÀ CÓ MẶT TRÊN BINGX.
    """
    try:
        tickers = binance.fetch_tickers()
        valid_pairs = []
        for symbol, ticker in tickers.items():
            if '/USDT' in symbol and 'quoteVolume' in ticker:
                # Kiểm tra xem symbol này có trên BingX không
                base_symbol = symbol.split(':')[0] if ':' in symbol else symbol
                if base_symbol not in bingx_symbols:
                    continue
                    
                vol_24h = ticker['quoteVolume']
                if min_volume_usd <= vol_24h <= max_volume_usd:
                    valid_pairs.append({
                        'symbol': symbol,
                        'volume_24h': vol_24h,
                        'change_24h': ticker.get('percentage', 0)
                    })
        return valid_pairs
    except Exception as e:
        print(f"Lỗi khi lấy danh sách coin: {e}")
        return []

def get_ohlcv_data(symbol, timeframe='15m', limit=200):
    """Lấy dữ liệu nến (Open, High, Low, Close, Volume)"""
    try:
        ohlcv = binance.fetch_ohlcv(symbol, timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df
    except Exception as e:
        print(f"Lỗi lấy dữ liệu {symbol}: {e}")
        return None

def analyze_coin(symbol, df, volume_24h, change_24h):
    """Phân tích dữ liệu nến để tìm điểm vào lệnh"""
    # Tính toán các chỉ số kỹ thuật dùng thư viện ta
    df['rsi'] = ta.momentum.RSIIndicator(close=df['close'], window=14).rsi()
    df['sma_volume'] = ta.trend.SMAIndicator(close=df['volume'], window=20).sma_indicator()
    df['atr'] = ta.volatility.AverageTrueRange(high=df['high'], low=df['low'], close=df['close'], window=14).average_true_range()
    df['ema_20'] = ta.trend.EMAIndicator(close=df['close'], window=20).ema_indicator()
    
    # LOGIC MỚI: TÌM COIN THEO SMA 3 ĐƯỜNG M15 (Open, High, Low)
    df['sma_open_144'] = ta.trend.SMAIndicator(close=df['open'], window=144).sma_indicator()
    df['sma_high_144'] = ta.trend.SMAIndicator(close=df['high'], window=144).sma_indicator()
    df['sma_low_144'] = ta.trend.SMAIndicator(close=df['low'], window=144).sma_indicator()
    df['avg_3_sma'] = (df['sma_open_144'] + df['sma_high_144'] + df['sma_low_144']) / 3
    
    # Đảm bảo có đủ dữ liệu để tính toán (cần ít nhất 144 nến)
    if df['avg_3_sma'].isna().iloc[-1]:
        return None
        
    current = df.iloc[-1]
    
    # Kiểm tra vượt trung bình 3 đường trong thời gian gần nhất (vài nến gần đây)
    crossed_recently_up = False
    crossed_recently_down = False
    candles_since_cross = 999
    
    for i in range(1, 6): 
        curr_idx = -i
        prev_idx = -(i+1)
        # Check Long cross
        if df['close'].iloc[prev_idx] <= df['avg_3_sma'].iloc[prev_idx] and df['close'].iloc[curr_idx] > df['avg_3_sma'].iloc[curr_idx]:
            crossed_recently_up = True
            candles_since_cross = i
            break
        # Check Short cross
        if df['close'].iloc[prev_idx] >= df['avg_3_sma'].iloc[prev_idx] and df['close'].iloc[curr_idx] < df['avg_3_sma'].iloc[curr_idx]:
            crossed_recently_down = True
            candles_since_cross = i
            break
            
    # Điều kiện cho LONG
    is_above = current['close'] > current['avg_3_sma']
    is_strong_up = current['close'] > (current['avg_3_sma'] * 1.005) # Lớn hơn trung bình ít nhất 0.5%
    rsi_bullish = current['rsi'] > 60
    
    # Điều kiện cho SHORT
    is_below = current['close'] < current['avg_3_sma']
    is_strong_down = current['close'] < (current['avg_3_sma'] * 0.995) # Thấp hơn trung bình ít nhất 0.5%
    rsi_bearish = current['rsi'] < 40
    
    # ---- TÍNH TOÁN ENTRY, SL, TP ----
    entry_price = current['close']
    signal_found = False
    signal_type = None
    
    if crossed_recently_up and is_above and is_strong_up and rsi_bullish:
        signal_found = True
        signal_type = "LONG"
        swing_low = df['low'].tail(10).min()
        stop_loss = swing_low * 0.99
        if (entry_price - stop_loss) / entry_price > 0.10:
            stop_loss = entry_price * 0.90
        risk_amount = entry_price - stop_loss
        tp1 = entry_price + (risk_amount * 1.5)
        tp2 = entry_price + (risk_amount * 3.0)
        sl_percent = ((entry_price - stop_loss) / entry_price) * 100
        
    elif crossed_recently_down and is_below and is_strong_down and rsi_bearish:
        signal_found = True
        signal_type = "SHORT"
        swing_high = df['high'].tail(10).max()
        stop_loss = swing_high * 1.01
        if (stop_loss - entry_price) / entry_price > 0.10:
            stop_loss = entry_price * 1.10
        risk_amount = stop_loss - entry_price
        tp1 = entry_price - (risk_amount * 1.5)
        tp2 = entry_price - (risk_amount * 3.0)
        sl_percent = ((stop_loss - entry_price) / entry_price) * 100
    
    # Mặc định (cho việc hiển thị các coin ko có tín hiệu trong bảng)
    if not signal_found:
        swing_low = df['low'].tail(10).min()
        stop_loss = swing_low * 0.99
        if (entry_price - stop_loss) / entry_price > 0.10: stop_loss = entry_price * 0.90
        risk_amount = entry_price - stop_loss
        tp1 = entry_price + (risk_amount * 1.5)
        tp2 = entry_price + (risk_amount * 3.0)
        sl_percent = ((entry_price - stop_loss) / entry_price) * 100

    vol_ratio = current['volume'] / current['sma_volume'] if current['sma_volume'] > 0 else 0
    price_change_1h = (current['close'] - df.iloc[-4]['open']) / df.iloc[-4]['open'] * 100 if len(df) >= 4 else 0

    if signal_found:
        vol_surge_ratio = vol_ratio * 100
        symbol_link = symbol.replace('/', '_').replace(':USDT', '')
        emoji = "🟢" if signal_type == "LONG" else "🔴"
        
        msg = f"""🚨 <b>[TÍN HIỆU - {signal_type}]</b> 🚨
📌 Coin: <b>{symbol}</b> {emoji}
📊 Khung thời gian: 15m
💰 Volume 24h: {volume_24h/1000000:.1f}M USD
📈 RSI: {current['rsi']:.1f}

🟢 Vùng vào lệnh (Entry): <b>{entry_price}</b>
🔴 Cắt lỗ (SL): <b>{stop_loss:.4f}</b> (-{sl_percent:.1f}%)
🎯 Chốt lời 1 (TP1): <b>{tp1:.4f}</b> [R:R 1:1.5]
🎯 Chốt lời 2 (TP2): <b>{tp2:.4f}</b> [R:R 1:3.0]

--------------------------
🔍 <b>Xác nhận:</b>
🔥 Vượt SMA 3 Đường: {candles_since_cross} nến trước
📈 Giá hiện tại so với SMA: {(current['close']/current['avg_3_sma'] - 1)*100:.2f}%
🔗 Chart: <a href='https://www.binance.com/en/futures/{symbol_link}'>Binance Futures {symbol}</a>"""

    return {
        'msg': msg if signal_found else None,
        'symbol': symbol,
        'signal_found': signal_found,
        'signal_type': signal_type if signal_found else None,
        'vol_ratio': vol_ratio,
        'price_change_1h': price_change_1h,
        'price_change_24h': change_24h,
        'rsi': current['rsi'],
        'entry': entry_price,
        'sl': stop_loss,
        'tp1': tp1,
        'tp2': tp2,
        'sl_percent': sl_percent
    }

def main():
    print("🚀 Bắt đầu chạy Bot Crypto Scanner...")
    print(f"⏰ Thời gian: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Tải danh sách lệnh cũ (để append lệnh mới vào)
    active_trades = load_active_trades()
    
    # Tải danh sách coin từ BingX trước để đối chiếu
    print("Đang tải dữ liệu thị trường từ BingX...")
    try:
        bingx.load_markets()
        bingx_symbols = set(bingx.symbols)
        print(f"Đã tải {len(bingx_symbols)} cặp giao dịch từ BingX.")
    except Exception as e:
        print(f"Lỗi tải dữ liệu BingX: {e}")
        bingx_symbols = set()
    
    # Lấy danh sách coin (Bao gồm cả Top Coin, Volume 24h > 5M USD)
    print("Đang quét danh sách coin từ Binance và đối chiếu với BingX...")
    pairs = get_lowcap_usdt_pairs(bingx_symbols, min_volume_usd=5000000, max_volume_usd=100000000000)
    print(f"🔍 Tìm thấy {len(pairs)} cặp coin thỏa mãn điều kiện Volume và có trên BingX.")
    
    pd.options.mode.chained_assignment = None # Tắt cảnh báo pandas
    
    all_stats = []
    signals_list = []
    
    for item in pairs:
        symbol = item['symbol']
        vol_24h = item['volume_24h']
        change_24h = item.get('change_24h', 0)
        
        df = get_ohlcv_data(symbol, timeframe='15m', limit=200)
        if df is not None and not df.empty and len(df) >= 144:
            result = analyze_coin(symbol, df, vol_24h, change_24h)
            if result:
                all_stats.append(result)
                if result['signal_found']:
                    print(f"✅ ĐÃ PHÁT HIỆU TÍN HIỆU TẠM THỜI CHO {symbol}!")
                    signals_list.append(result)
        
        # Sleep 0.2s để tránh bị Binance cấm IP (Rate limit)
        time.sleep(0.2)

    # Lọc top 5 coin tiềm năng nhất dựa trên RSI (tăng mạnh hoặc giảm mạnh)
    # Sắp xếp theo độ lệch của RSI so với mức trung bình 50
    signals_list.sort(key=lambda x: abs(x['rsi'] - 50), reverse=True)
    top_5_signals = signals_list[:5]
    
    for result in top_5_signals:
        symbol = result['symbol']
        print(f"🚀 CHỌN LỌC TOP TÍN HIỆU: {symbol} (RSI: {result['rsi']:.1f})")
        if result.get('msg'):
            send_telegram_message(result['msg'])
        # Thêm vào danh sách lệnh đang mở
        if not any(t['symbol'] == symbol for t in active_trades):
            active_trades.append({
                'symbol': symbol,
                'type': result['signal_type'],
                'entry': result['entry'],
                'sl': result['sl'],
                'tp1': result['tp1']
            })
            save_active_trades(active_trades)
        
    print(f"\n🏁 Hoàn thành vòng quét lúc {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # In ra top 5 coin tiềm năng nhất ngay cả khi không có tín hiệu báo lệnh
    if all_stats:
        df_stats = pd.DataFrame(all_stats)
        
        print("\n" + "="*50)
        print("🔥 BẢNG XẾP HẠNG TOP 5 COIN TIỀM NĂNG NHẤT LÚC NÀY 🔥")
        print("="*50)
        
        print("\n🚀 TOP 5 SIÊU PUMP 24 GIỜ QUA (TOP GAINERS):")
        top_24h = df_stats.sort_values(by='price_change_24h', ascending=False).head(5)
        for i, (_, r) in enumerate(top_24h.iterrows(), 1):
            print(f"{i}. {r['symbol']:<10} | Tăng 24h: {r['price_change_24h']:>6.2f}% | Tăng 1h: {r['price_change_1h']:>5.2f}% | RSI: {r['rsi']:>4.1f}")

        print("\n📈 TOP 5 TĂNG MẠNH NHẤT TRONG 1 GIỜ QUA (MOMENTUM GẦN):")
        top_price = df_stats.sort_values(by='price_change_1h', ascending=False).head(5)
        for i, (_, r) in enumerate(top_price.iterrows(), 1):
            print(f"{i}. {r['symbol']:<10} | Tăng 1h: {r['price_change_1h']:>5.2f}% | RSI: {r['rsi']:>4.1f}")
            print(f"   => Entry: {r['entry']:.5f} | SL: {r['sl']:.5f} (-{r['sl_percent']:.1f}%) | TP1: {r['tp1']:.5f} (R:R 1.5)")
            
        print("\n🌊 TOP 5 CÓ DÒNG TIỀN VÀO MẠNH NHẤT (HIỆN TẠI):")
        top_vol = df_stats.sort_values(by='vol_ratio', ascending=False).head(5)
        for i, (_, r) in enumerate(top_vol.iterrows(), 1):
            print(f"{i}. {r['symbol']:<10} | Vol: {r['vol_ratio']:>4.1f}x | RSI: {r['rsi']:>4.1f}")
            print(f"   => Entry: {r['entry']:.5f} | SL: {r['sl']:.5f} (-{r['sl_percent']:.1f}%) | TP1: {r['tp1']:.5f} (R:R 1.5)")

if __name__ == "__main__":
    main()
