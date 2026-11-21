import ccxt
import pandas as pd
import ta
import requests
import time
from datetime import datetime
import json
import os

from flow_filter import get_flow_snapshot, format_flow_table

# --- CONFIGURATION ---
ACTIVE_TRADES_FILE = 'active_trades.json'
# Bạn cần thay thế Token và Chat ID của bạn vào đây
TELEGRAM_BOT_TOKEN = '9051874352:AAFrnfJ8Mm0QF4wBlz8V3vYjYiqz5_sIVF8'
TELEGRAM_CHAT_ID = '6022180065'

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

def analyze_coin(symbol, df, volume_24h, change_24h, flow_data=None):
    """Phân tích dữ liệu nến để tìm điểm vào lệnh
    `flow_data` (optional): dict snapshot từ flow_filter.get_flow_snapshot().
    """
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

    # ---- BỘ LỌC DÒNG TIỀN ----
    flow_blocked = False
    flow_boost = 0     # +1 (đồng thuận), -1 (lệch chiều), 0 (trung tính)
    flow_score = None
    if flow_data:
        flow_summary = flow_data.get('summary', {}) if isinstance(flow_data, dict) else {}
        flow_score = flow_summary.get('score', 0)
        # 1. Chặn tín hiệu nếu short-term đang bị dump mạnh
        if not flow_summary.get('short_term_not_dump', True):
            flow_blocked = True
            signal_found = False
        # 2. Nếu momentum lệch chiều với tín hiệu → giảm boost
        if signal_type == 'LONG' and flow_summary.get('momentum_aligned_positive'):
            flow_boost = 1
        elif signal_type == 'LONG' and flow_summary.get('momentum_aligned_negative'):
            flow_boost = -1
        elif signal_type == 'SHORT' and flow_summary.get('momentum_aligned_negative'):
            flow_boost = 1
        elif signal_type == 'SHORT' and flow_summary.get('momentum_aligned_positive'):
            flow_boost = -1

    if signal_found:
        vol_surge_ratio = vol_ratio * 100
        symbol_link = symbol.replace('/', '_').replace(':USDT', '')
        emoji = "🟢" if signal_type == "LONG" else "🔴"
        flow_emoji = "✅" if flow_boost >= 0 else "⚠️"
        flow_score_str = f"{flow_score}/100" if flow_score is not None else "N/A"

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
🌊 Dòng tiền đồng thuận: {flow_emoji} (điểm: {flow_score_str})

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
        'sl_percent': sl_percent,
        'flow_blocked': flow_blocked,
        'flow_boost': flow_boost,
        'flow_score': flow_score,
        'flow_data': flow_data,
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

    # ---- STAGE 1: LỌC DÒNG TIỀN (rẻ, 1 request / symbol) ----
    print("\n💧 Stage 1: Lọc dòng tiền (Inflow/Outflow trên Binance Futures)...")
    flow_cache: dict = {}     # symbol -> snapshot
    pre_filtered_pairs = []
    for item in pairs:
        symbol = item['symbol']
        snap = get_flow_snapshot(symbol)
        flow_cache[symbol] = snap
        if snap and snap.get('summary', {}).get('is_accumulation'):
            item_copy = dict(item)
            item_copy['flow_score'] = snap['summary'].get('score', 0)
            pre_filtered_pairs.append(item_copy)
        time.sleep(0.05)   # Binance Futures chịu được 1200 req/phút
    print(f"   ✅ Còn {len(pre_filtered_pairs)}/{len(pairs)} coin TÍCH LŨY "
          f"(giá đi ngang/giảm + dòng tiền 4h-12h dương)")
    print(f"   ℹ️  Đã lưu dòng tiền cho tất cả {len(flow_cache)} coin để dùng cho Stage 2 fallback")

    # ---- STAGE 2: PHÂN TÍCH KỸ THUẬT ----
    # Mặc định chỉ scan các coin đã qua Stage 1 (tích lũy). Nếu quá ít (<5) thì
    # bổ sung thêm các coin có flow_score cao nhất để bảng xếp hạng có dữ liệu.
    stage2_pairs = list(pre_filtered_pairs)
    if len(stage2_pairs) < 5:
        extras = []
        for item in pairs:
            sym = item['symbol']
            if sym in {p['symbol'] for p in stage2_pairs}:
                continue
            snap = flow_cache.get(sym)
            if not snap:
                continue
            score = snap['summary'].get('score', 0)
            if score >= 30:   # ngưỡng tối thiểu để bổ sung
                ic = dict(item)
                ic['flow_score'] = score
                extras.append((score, ic))
        extras.sort(key=lambda x: x[0], reverse=True)
        for _, ic in extras[:max(0, 10 - len(stage2_pairs))]:
            stage2_pairs.append(ic)
        print(f"   ➕ Bổ sung {len(stage2_pairs) - len(pre_filtered_pairs)} coin có flow_score >= 30 để có dữ liệu phân tích")

    all_stats = []
    signals_list = []

    for item in stage2_pairs:
        symbol = item['symbol']
        vol_24h = item['volume_24h']
        change_24h = item.get('change_24h', 0)
        flow_data = flow_cache.get(symbol)

        df = get_ohlcv_data(symbol, timeframe='15m', limit=200)
        if df is not None and not df.empty and len(df) >= 144:
            result = analyze_coin(symbol, df, vol_24h, change_24h, flow_data=flow_data)
            if result:
                all_stats.append(result)
                if result['signal_found']:
                    print(f"✅ ĐÃ PHÁT HIỆU TÍN HIỆU TẠM THỜI CHO {symbol}!")
                    signals_list.append(result)
                elif result.get('flow_blocked'):
                    print(f"   ⚠️  SMA+RSI có tín hiệu {result.get('signal_type')} nhưng BỊ CHẶN do short-term bị dump.")

        time.sleep(0.05)

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

        print("\n" + "="*70)
        print("🔥 BẢNG XẾP HẠNG TOP 5 COIN TIỀM NĂNG NHẤT LÚC NÀY 🔥")
        print("="*70)

        # ----- BẢNG CHÍNH: TOP TÍCH LŨY (giá ngang/giảm + dòng tiền vào) -----
        acc = [r for r in all_stats
               if (r.get('flow_data') or {}).get('summary', {}).get('is_accumulation')]
        if acc:
            print("\n💎 TOP 5 COIN TÍCH LŨY (giá đi ngang/giảm + dòng tiền 4h-12h đều dương):")
            acc.sort(key=lambda x: x.get('flow_score') or 0, reverse=True)
            for i, r in enumerate(acc[:5], 1):
                pct4h = (r.get('flow_data') or {}).get('price', {}).get('pct_4h', 0)
                pct1h = (r.get('flow_data') or {}).get('price', {}).get('pct_1h', 0)
                print(f"{i}. {r['symbol']:<18} | Giá 4h: {pct4h:>+6.2f}% | Giá 1h: {pct1h:>+5.2f}% | "
                      f"Flow: {r.get('flow_score') or 0:>3}/100 | RSI: {r['rsi']:>4.1f}")
                print(f"   => Entry: {r['entry']:.5f} | SL: {r['sl']:.5f} (-{r['sl_percent']:.1f}%) "
                      f"| TP1: {r['tp1']:.5f} (R:R 1.5)")
        else:
            print("\n⚠️  KHÔNG CÓ COIN TÍCH LŨY nào trong {0} coin — thị trường đang "
                  "sideway / giảm đồng loạt. Dưới đây là top coin theo dòng tiền:".format(len(pairs)))

        print("\n🚀 TOP 5 SIÊU PUMP 24 GIỜ QUA (TOP GAINERS — giá đã chạy):")
        top_24h = df_stats.sort_values(by='price_change_24h', ascending=False).head(5)
        for i, (_, r) in enumerate(top_24h.iterrows(), 1):
            flow_s = r.get('flow_score') or 0
            print(f"{i}. {r['symbol']:<18} | Tăng 24h: {r['price_change_24h']:>6.2f}% | "
                  f"Tăng 1h: {r['price_change_1h']:>5.2f}% | RSI: {r['rsi']:>4.1f} | Flow: {flow_s:>3}/100")

        print("\n📉 TOP 5 GIÁ GIẢM MẠNH TRONG 4 GIỜ QUA (cân nhắc SHORT hoặc bỏ qua):")
        df_with_4h = []
        for r in all_stats:
            pct4h = (r.get('flow_data') or {}).get('price', {}).get('pct_4h', 0)
            df_with_4h.append({'r': r, 'pct4h': pct4h})
        df_with_4h.sort(key=lambda x: x['pct4h'])
        for i, item in enumerate(df_with_4h[:5], 1):
            r = item['r']
            print(f"{i}. {r['symbol']:<18} | Giảm 4h: {item['pct4h']:>+6.2f}% | "
                  f"RSI: {r['rsi']:>4.1f} | Flow: {r.get('flow_score') or 0:>3}/100")

        print("\n🌊 TOP 5 FLOW SCORE CAO NHẤT (bất chấp giá):")
        top_flow = df_stats.sort_values(by='flow_score', ascending=False).head(5)
        for i, (_, r) in enumerate(top_flow.iterrows(), 1):
            print(f"{i}. {r['symbol']:<18} | Flow: {r.get('flow_score') or 0:>3}/100 | "
                  f"Vol ratio: {r['vol_ratio']:>4.1f}x | RSI: {r['rsi']:>4.1f}")
            print(f"   => Entry: {r['entry']:.5f} | SL: {r['sl']:.5f} (-{r['sl_percent']:.1f}%) "
                  f"| TP1: {r['tp1']:.5f} (R:R 1.5)")

        # In chi tiết 1 coin tích lũy mạnh nhất
        if acc:
            top_acc = acc[0]
            top_sym = top_acc['symbol']
            top_snap = flow_cache.get(top_sym)
            if top_snap:
                print(f"\n📈 Chi tiết dòng tiền của #{1} TÍCH LŨY: {top_sym} "
                      f"(Flow Score = {top_snap['summary']['score']}/100):")
                print(format_flow_table(top_snap))

if __name__ == "__main__":
    main()
