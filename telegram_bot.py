import os
import json
import time
import requests
import urllib.request
import threading
import http.server
import socketserver
import numpy as np

CONFIG = {
    'TELEGRAM_BOT_TOKEN': '9051874352:AAFrnfJ8Mm0QF4wBlz8V3vYjYiqz5_sIVF8',
    'TELEGRAM_CHAT_ID': '6022180065',
    'ACCOUNT_BALANCE': 1000.0,
    'RISK_PER_TRADE': 2.0,
}

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

# Cache lưu trữ các mức cản H4 để cố định điểm vào lệnh trong phiên H4
PLAN_CACHE = {
    'BTC': {'candle_time': 0, 'data': None},
    'GOLD': {'candle_time': 0, 'data': None},
    'COINS_LONG': {'time': 0, 'data': []},
    'COINS_SHORT': {'time': 0, 'data': []}
}

def send_telegram(text, reply_markup=None):
    url = f"https://api.telegram.org/bot{CONFIG['TELEGRAM_BOT_TOKEN']}/sendMessage"
    payload = {
        "chat_id": CONFIG['TELEGRAM_CHAT_ID'],
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Lỗi gửi Telegram: {e}")

def get_main_keyboard():
    return {
        "keyboard": [
            [{"text": "📈 Tìm Coin TĂNG (LONG)"}, {"text": "📉 Tìm Coin GIẢM (SHORT)"}],
            [{"text": "👑 Phân Tích BTC"}, {"text": "🥇 Phân Tích VÀNG (XAU)"}],
            [{"text": "🔍 Kiểm Tra Lệnh & Báo Cáo Ngày"}, {"text": "⚙️ Menu Hỗ Trợ"}]
        ],
        "resize_keyboard": True
    }

# ==========================================
# 1. TÍNH VOLUME PROFILE & CỐ ĐỊNH KẾ HOẠCH BITCOIN THEO KHUNG H4
# ==========================================
def calculate_btc_h4_plan():
    now = time.time()
    # Nếu kế hoạch H4 còn hiệu lực trong vòng 4 tiếng (14400s) thì giữ nguyên điểm vào cố định!
    if PLAN_CACHE['BTC']['data'] and (now - PLAN_CACHE['BTC']['candle_time'] < 14400):
        return PLAN_CACHE['BTC']['data']
        
    url = 'https://api.bybit.com/v5/market/kline?category=linear&symbol=BTCUSDT&interval=240&limit=30'
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode())['result']['list']
        
    current_price = float(data[0][4])
    change_24h = (float(data[0][4]) - float(data[5][1])) / float(data[5][1]) * 100.0
    
    # 1. Tính Volume Profile (POC) từ 30 nến H4
    prices = []
    vols = []
    for k in data:
        mid = (float(k[2]) + float(k[3])) / 2
        prices.append(mid)
        vols.append(float(k[5]))
        
    hist, bin_edges = np.histogram(prices, bins=25, weights=vols)
    poc = (bin_edges[np.argmax(hist)] + bin_edges[np.argmax(hist)+1]) / 2
    
    # 2. Lấy cản râu nến H4 gần nhất
    highs = [float(k[2]) for k in data[:6]]
    lows = [float(k[3]) for k in data[:6]]
    swing_high_h4 = max(highs)
    swing_low_h4 = min(lows)
    
    is_uptrend = current_price >= poc
    signal = "LONG" if is_uptrend else "SHORT"
    
    if signal == "SHORT":
        # SELL LIMIT: Cố định tại cản râu nến cao nhất H4 hoặc vùng POC
        entry_limit = round(min(swing_high_h4, poc) if min(swing_high_h4, poc) > current_price else swing_high_h4, 1)
        # SELL STOP: Bán khi thủng đáy râu thấp nhất H4
        entry_stop = round(swing_low_h4 * 0.998, 1)
        sl = round(entry_limit * 1.025, 1) # SL 2.5%
        risk = sl - entry_limit
        tp1 = round(entry_limit - (risk * 2.0), 1)
        tp2 = round(entry_limit - (risk * 3.5), 1)
    else: # LONG
        entry_limit = round(max(swing_low_h4, poc) if max(swing_low_h4, poc) < current_price else swing_low_h4, 1)
        entry_stop = round(swing_high_h4 * 1.002, 1)
        sl = round(entry_limit * 0.975, 1)
        risk = entry_limit - sl
        tp1 = round(entry_limit + (risk * 2.0), 1)
        tp2 = round(entry_limit + (risk * 3.5), 1)
        
    plan = {
        'signal': signal,
        'current_price': current_price,
        'poc': round(poc, 1),
        'swing_high': round(swing_high_h4, 1),
        'swing_low': round(swing_low_h4, 1),
        'entry_limit': entry_limit,
        'entry_stop': entry_stop,
        'sl': sl,
        'tp1': tp1,
        'tp2': tp2,
        'change_24h': change_24h
    }
    PLAN_CACHE['BTC']['data'] = plan
    PLAN_CACHE['BTC']['candle_time'] = now
    return plan

def handle_btc():
    try:
        plan = calculate_btc_h4_plan()
        s_emoji = "🟢 LONG" if plan['signal'] == 'LONG' else "🔴 SHORT"
        action_l = "Bán Giá Cao Tại Cản Râu H4" if plan['signal'] == 'SHORT' else "Mua Giá Thấp Tại Hỗ Trợ Râu H4"
        action_s = "Bán Tháo Khi Thủng Đáy Râu H4" if plan['signal'] == 'SHORT' else "Mua Đuổi Khi Vượt Đỉnh Râu H4"
        
        text = f"""👑 <b>[KẾ HOẠCH BITCOIN CỐ ĐỊNH THEO KHUNG H4]</b> 👑
━━━━━━━━━━━━━━━━━━
💰 Giá hiện tại: <b>${plan['current_price']:,.1f}</b>
🎯 Vùng POC (Thanh khoản Volume lớn nhất): <b>${plan['poc']:,.1f}</b>
📊 Đỉnh râu H4: <b>${plan['swing_high']:,.1f}</b> | Đáy râu H4: <b>${plan['swing_low']:,.1f}</b>
━━━━━━━━━━━━━━━━━━
🚀 <b>CHIẾN LƯỢC H4: {s_emoji}</b>
👉 <b>1. LỆNH LIMIT CỐ ĐỊNH ({action_l}):</b>
   <code>${plan['entry_limit']:,.1f}</code>
👉 <b>2. LỆNH STOP KÍCH HOẠT ({action_s}):</b>
   <code>${plan['entry_stop']:,.1f}</code>

🛡️ <b>Cắt lỗ (SL H4):</b> <code>${plan['sl']:,.1f}</code>
🎯 <b>Chốt lời 1 (TP1 - R:R 1:2):</b> <code>${plan['tp1']:,.1f}</code>
🎯 <b>Chốt lời 2 (TP2 - R:R 1:3.5):</b> <code>${plan['tp2']:,.1f}</code>

🛡️ <b>QUẢN LÝ VỐN (${CONFIG['ACCOUNT_BALANCE']:,.0f}):</b>
• Rủi ro tối đa 2%: <b>$20.0</b>
• Vị thế: <b>$1,000.0</b> | Đòn bẩy đề xuất: <b>5x</b>
• Margin cần dùng: <b>$200.0</b>
<i>💡 Lưu ý: Các mức giá Entry/SL này được CỐ ĐỊNH xuyên suốt phiên 4H, không bị thay đổi lắt nhắt!</i>"""
        send_telegram(text, reply_markup=get_main_keyboard())
    except Exception as e:
        send_telegram(f"Lỗi BTC H4: {e}", reply_markup=get_main_keyboard())

# ==========================================
# 2. CỐ ĐỊNH KẾ HOẠCH VÀNG (OANDA) THEO CẢN RÂU NẾN H4 & D1
# ==========================================
def calculate_gold_h4_plan():
    now = time.time()
    if PLAN_CACHE['GOLD']['data'] and (now - PLAN_CACHE['GOLD']['candle_time'] < 14400):
        return PLAN_CACHE['GOLD']['data']
        
    url = 'https://scanner.tradingview.com/cfd/scan'
    payload = json.dumps({
        'symbols': {'tickers': ['OANDA:XAUUSD']},
        'columns': [
            'close|240', 'high|240', 'low|240', 'EMA20|240',
            'high', 'low', 'close', 'EMA20'
        ]
    }).encode()
    req = urllib.request.Request(url, data=payload, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=10) as resp:
        d = json.loads(resp.read().decode())['data'][0]['d']
        
    h4_close = d[0]
    h4_high = d[1]
    h4_low = d[2]
    h4_ema20 = d[3]
    d1_high = d[4]
    d1_low = d[5]
    
    is_uptrend = h4_close >= h4_ema20
    signal = "LONG" if is_uptrend else "SHORT"
    
    if signal == "SHORT":
        # SELL LIMIT CỐ ĐỊNH: Đón tại cản râu cao nhất nến H4
        entry_limit = round(h4_high, 2)
        # SELL STOP: Bán tháo khi đâm thủng đáy râu thấp nhất nến H4
        entry_stop = round(h4_low - 1.5, 2)
        sl = round(entry_limit + 20.0, 2) # SL đúng 20 giá
        tp1 = round(entry_limit - 40.0, 2)
        tp2 = round(entry_limit - 70.0, 2)
        advice = (
            "⚠️ CẮT LỖ SỚM: Nếu có nến H1/H4 đóng cửa vượt qua cản đỉnh $3,546.00 thì chủ động cắt sớm bằng tay!\n"
            "💎 DCA GIA TĂNG LỢI NHUẬN: Khi giá thủng đáy $3,502.00 và có lãi > 20 giá, dời SL về Hòa vốn và nhồi thêm Lệnh 2 (Sell Stop)!"
        )
    else: # LONG
        entry_limit = round(h4_low, 2)
        entry_stop = round(h4_high + 1.5, 2)
        sl = round(entry_limit - 20.0, 2)
        tp1 = round(entry_limit + 40.0, 2)
        tp2 = round(entry_limit + 70.0, 2)
        advice = (
            "⚠️ CẮT LỖ SỚM: Nếu nến H1/H4 gãy cản đáy thì chủ động cắt sớm!\n"
            "💎 DCA GIA TĂNG LỢI NHUẬN: Khi giá vượt đỉnh và có lãi > 20 giá, dời SL về Hòa vốn và nhồi thêm Lệnh 2 (Buy Stop)!"
        )
        
    plan = {
        'signal': signal,
        'current_price': h4_close,
        'h4_high': h4_high,
        'h4_low': h4_low,
        'entry_limit': entry_limit,
        'entry_stop': entry_stop,
        'sl': sl,
        'tp1': tp1,
        'tp2': tp2,
        'advice': advice
    }
    PLAN_CACHE['GOLD']['data'] = plan
    PLAN_CACHE['GOLD']['candle_time'] = now
    return plan

def handle_gold():
    try:
        plan = calculate_gold_h4_plan()
        s_emoji = "🟢 LONG" if plan['signal'] == 'LONG' else "🔴 SHORT"
        action_l = "LỆNH 1: Bán Giá Cao Tại Cản Râu H4" if plan['signal'] == 'SHORT' else "LỆNH 1: Mua Giá Thấp Tại Đáy Râu H4"
        action_s = "LỆNH 2: Bán Phá Đáy Xác Nhận Sóng Xả H4" if plan['signal'] == 'SHORT' else "LỆNH 2: Mua Vượt Đỉnh H4"
        
        text = f"""🥇 <b>[KẾ HOẠCH VÀNG (OANDA) CỐ ĐỊNH THEO KHUNG H4]</b> 🥇
━━━━━━━━━━━━━━━━━━
📊 Nguồn biểu đồ: <b>TradingView (OANDA:XAUUSD)</b>
💰 Giá Vàng hiện tại: <b>${plan['current_price']:,.2f}</b>
📈 Cản đỉnh râu H4: <b>${plan['h4_high']:,.2f}</b> | Đáy râu H4: <b>${plan['h4_low']:,.2f}</b>
━━━━━━━━━━━━━━━━━━
🚀 <b>CHIẾN LƯỢC H4: {s_emoji}</b>
👉 <b>{action_l}:</b>
   <code>${plan['entry_limit']:,.2f}</code>
👉 <b>{action_s}:</b>
   <code>${plan['entry_stop']:,.2f}</code>

🛡️ <b>Cắt lỗ (SL Chuẩn 20 Giá):</b> <code>${plan['sl']:,.2f}</code>
🎯 <b>Chốt lời 1 (TP1 - Ăn 40 Giá):</b> <code>${plan['tp1']:,.2f}</code>
🎯 <b>Chốt lời 2 (TP2 - Ăn 70 Giá):</b> <code>${plan['tp2']:,.2f}</code>

🧠 <b>KẾ HOẠCH XỬ LÝ LỆNH CHỦ ĐỘNG:</b>
{plan['advice']}

🛡️ <b>QUẢN LÝ VỐN VÀNG (${CONFIG['ACCOUNT_BALANCE']:,.0f}):</b>
• Rủi ro tối đa 2%: <b>$20.0</b> | Đòn bẩy đề xuất: <b>5x</b>
• Margin cần dùng: <b>$500.0</b>
<i>💡 Mức giá Entry $3,544.40 & SL này được giữ CỐ ĐỊNH trong suốt nến 4H để bạn yên tâm vào lệnh!</i>"""
        send_telegram(text, reply_markup=get_main_keyboard())
    except Exception as e:
        send_telegram(f"Lỗi Vàng H4: {e}", reply_markup=get_main_keyboard())

# ==========================================
# 3. QUÉT COIN THEO PHIÊN 1H - CỐ ĐỊNH ENTRY
# ==========================================
def scan_coins_bybit(mode='long', limit=3):
    now = time.time()
    cache_key = 'COINS_LONG' if mode == 'long' else 'COINS_SHORT'
    # Giữ cố định danh sách coin và điểm vào trong 1 tiếng (3600s)
    if PLAN_CACHE[cache_key]['data'] and (now - PLAN_CACHE[cache_key]['time'] < 3600):
        return PLAN_CACHE[cache_key]['data']
        
    url = 'https://api.bybit.com/v5/market/tickers?category=linear'
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode())
        tickers = data['result']['list']
        
    usdt_tickers = []
    for d in tickers:
        sym = d['symbol']
        vol = float(d.get('turnover24h', 0))
        if sym.endswith('USDT') and vol > 15000000:
            change_pct = float(d.get('price24hPcnt', 0)) * 100.0
            usdt_tickers.append({
                'symbol': sym.replace('USDT', '/USDT'),
                'price': float(d['lastPrice']),
                'high_24h': float(d['highPrice24h']),
                'low_24h': float(d['lowPrice24h']),
                'change': change_pct,
                'vol_m': vol / 1000000
            })
            
    if mode == 'long':
        usdt_tickers.sort(key=lambda x: x['change'], reverse=True)
    else:
        usdt_tickers.sort(key=lambda x: x['change'])
        
    candidates = usdt_tickers[:limit]
    results = []
    
    for c in candidates:
        price = c['price']
        high_c = c['high_24h']
        low_c = c['low_24h']
        
        if mode == 'long':
            # Cố định Entry Limit đón râu nến dưới
            entry_limit = round(max(low_c, price * 0.988), 5)
            entry_stop = round(high_c * 1.002, 5)
            sl = round(entry_limit * 0.975, 5)
            sl_pct = 2.5
            tp1 = round(entry_limit * 1.05, 5)
            tp2 = round(entry_limit * 1.0875, 5)
            status = "🟢 BIAS TĂNG (Volume Khủng)"
            limit_lbl = "BUY LIMIT (Đón Râu Hồi)"
            stop_lbl = "BUY STOP (Phá Cản)"
        else: # short
            entry_limit = round(min(high_c, price * 1.012), 5)
            entry_stop = round(low_c * 0.998, 5)
            sl = round(entry_limit * 1.025, 5)
            sl_pct = 2.5
            tp1 = round(entry_limit * 0.95, 5)
            tp2 = round(entry_limit * 0.9125, 5)
            status = "🔴 BIAS GIẢM (Lực Xả Mạnh)"
            limit_lbl = "SELL LIMIT (Đón Râu Cản)"
            stop_lbl = "SELL STOP (Phá Đáy)"
            
        results.append({
            'symbol': c['symbol'],
            'market_price': price,
            'change': c['change'],
            'vol_m': c['vol_m'],
            'entry_limit': entry_limit,
            'entry_stop': entry_stop,
            'limit_lbl': limit_lbl,
            'stop_lbl': stop_lbl,
            'status': status,
            'sl': sl,
            'sl_pct': sl_pct,
            'tp1': tp1,
            'tp2': tp2
        })
        
    PLAN_CACHE[cache_key]['data'] = results
    PLAN_CACHE[cache_key]['time'] = now
    return results

def handle_scan(mode='long'):
    try:
        results = scan_coins_bybit(mode=mode, limit=3)
        header = "🚀 [TOP COIN TIỀM NĂNG TĂNG - LONG]" if mode == 'long' else "📉 [TOP COIN TIỀM NĂNG GIẢM - SHORT]"
        msg = f"<b>{header} (KẾ HOẠCH CỐ ĐỊNH THEO PHIÊN)</b>\n━━━━━━━━━━━━━━━━━━"
        
        for i, r in enumerate(results, 1):
            emoji = "🟢" if mode == 'long' else "🔴"
            msg += f"""
{i}. <b>{r['symbol']}</b> {emoji} (Vol: ${r['vol_m']:.1f}M)
• Giá thị trường: <b>{r['market_price']}</b> | Biến động: <b>{r['change']:+.2f}%</b>
🎯 <b>Trạng thái:</b> <i>{r['status']}</i>
👉 <b>{r['limit_lbl']}:</b> <code>{r['entry_limit']}</code>
👉 <b>{r['stop_lbl']}:</b> <code>{r['entry_stop']}</code>
🛡️ <b>Cắt lỗ (SL):</b> <code>{r['sl']}</code> (-{r['sl_pct']}%)
🎯 <b>Chốt lời 1 (TP1):</b> <code>{r['tp1']}</code> [R:R 1:2]
🎯 <b>Chốt lời 2 (TP2):</b> <code>{r['tp2']}</code> [R:R 1:3.5]"""
            
        msg += "\n━━━━━━━━━━━━━━━━━━\n<i>💡 Điểm vào lệnh được neo cố định theo cản nến trong phiên để bạn kịp đặt lệnh trên sàn!</i>"
        send_telegram(msg, reply_markup=get_main_keyboard())
    except Exception as e:
        send_telegram(f"Lỗi scan: {e}", reply_markup=get_main_keyboard())

# ==========================================
# 4. SERVER HEALTH CHECK & AUTO-PING
# ==========================================
def self_ping_worker():
    time.sleep(20)
    while True:
        try:
            url = "https://coinradar-tele-bot.onrender.com"
            req = urllib.request.Request(url, headers={'User-Agent': 'KeepAlive/1.0'})
            with urllib.request.urlopen(req, timeout=10) as resp:
                pass
        except Exception:
            pass
        time.sleep(600)

def start_health_server():
    port = int(os.environ.get('PORT', 8080))
    class HealthHandler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'Bot is healthy!')
        def log_message(self, format, *args):
            return
    try:
        with socketserver.TCPServer(('', port), HealthHandler) as httpd:
            httpd.serve_forever()
    except Exception:
        pass

def run_bot():
    print("🤖 Bot Telegram đang lắng nghe...")
    url = f"https://api.telegram.org/bot{CONFIG['TELEGRAM_BOT_TOKEN']}/getUpdates"
    
    try:
        init_resp = requests.get(url, params={"offset": -1}, timeout=10).json()
        if init_resp.get("result"):
            last_update_id = init_resp["result"][-1]["update_id"]
            requests.get(url, params={"offset": last_update_id + 1}, timeout=10)
        else:
            last_update_id = 0
    except Exception:
        last_update_id = 0
        
    while True:
        try:
            params = {"offset": last_update_id + 1, "timeout": 20}
            resp = requests.get(url, params=params, timeout=25)
            if resp.status_code == 200:
                data = resp.json()
                for update in data.get("result", []):
                    last_update_id = update["update_id"]
                    msg = update.get("message", {})
                    text = msg.get("text", "").strip()
                    chat_id = str(msg.get("chat", {}).get("id"))
                    
                    if chat_id != CONFIG['TELEGRAM_CHAT_ID']:
                        continue
                        
                    if text in ["/start", "menu", "Menu", "⚙️ Menu Hỗ Trợ"]:
                        send_telegram("Chọn một tính năng bên dưới:", reply_markup=get_main_keyboard())
                    elif text in ["/btc", "👑 Phân Tích BTC", "btc", "BTC"]:
                        handle_btc()
                    elif text in ["/gold", "🥇 Phân Tích VÀNG (XAU)", "gold", "vang", "Vàng"]:
                        handle_gold()
                    elif text in ["/long", "📈 Tìm Coin TĂNG (LONG)", "long"]:
                        handle_scan(mode='long')
                    elif text in ["/short", "📉 Tìm Coin GIẢM (SHORT)", "short"]:
                        handle_scan(mode='short')
            time.sleep(1)
        except Exception as e:
            time.sleep(3)

if __name__ == '__main__':
    threading.Thread(target=start_health_server, daemon=True).start()
    threading.Thread(target=self_ping_worker, daemon=True).start()
    run_bot()
