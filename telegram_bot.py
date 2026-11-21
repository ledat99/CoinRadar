import os
import json
import time
import requests
import urllib.request
import threading
import http.server
import socketserver

CONFIG = {
    'TELEGRAM_BOT_TOKEN': '9051874352:AAFrnfJ8Mm0QF4wBlz8V3vYjYiqz5_sIVF8',
    'TELEGRAM_CHAT_ID': '6022180065',
    'ACCOUNT_BALANCE': 1000.0,
    'RISK_PER_TRADE': 2.0,
}

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

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
# 1. QUÉT COIN TRỰC TIẾP QUA BYBIT REST API (KHÔNG BỊ CHẶN IP DATACENTER / 418)
# ==========================================
def scan_coins_direct(mode='long', limit=3):
    url = 'https://api.bybit.com/v5/market/tickers?category=linear'
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode())
        tickers = data['result']['list']
        
    usdt_tickers = []
    for d in tickers:
        sym = d['symbol']
        vol = float(d.get('turnover24h', 0))
        # Chỉ lấy coin USDT và thanh khoản > $15 Triệu USD
        if sym.endswith('USDT') and vol > 15000000:
            change_pct = float(d.get('price24hPcnt', 0)) * 100.0
            usdt_tickers.append({
                'symbol': sym.replace('USDT', '/USDT'),
                'raw_sym': sym,
                'price': float(d['lastPrice']),
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
        if mode == 'long':
            entry_limit = round(price * 0.992, 5)
            entry_stop = round(price * 1.008, 5)
            sl = round(entry_limit * 0.975, 5)
            sl_pct = 2.5
            tp1 = round(entry_limit * 1.05, 5)
            tp2 = round(entry_limit * 1.0875, 5)
            status = "🟢 BIAS TĂNG (Volume Khủng)"
            limit_lbl = "BUY LIMIT (Đón Râu Hồi)"
            stop_lbl = "BUY STOP (Phá Cản Tiếp Diễn)"
        else: # short
            entry_limit = round(price * 1.008, 5)
            entry_stop = round(price * 0.992, 5)
            sl = round(entry_limit * 1.025, 5)
            sl_pct = 2.5
            tp1 = round(entry_limit * 0.95, 5)
            tp2 = round(entry_limit * 0.9125, 5)
            status = "🔴 BIAS GIẢM (Lực Xả Mạnh)"
            limit_lbl = "SELL LIMIT (Đón Râu Cản)"
            stop_lbl = "SELL STOP (Phá Đáy Tiếp Diễn)"
            
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
    return results

def handle_scan(mode='long'):
    try:
        results = scan_coins_direct(mode=mode, limit=3)
        if not results:
            send_telegram("⚠️ Hiện tại chưa có dữ liệu sàn Binance. Hãy thử lại trong vài giây.")
            return
            
        header = "🚀 [TOP COIN TIỀM NĂNG TĂNG - LONG]" if mode == 'long' else "📉 [TOP COIN TIỀM NĂNG GIẢM - SHORT]"
        msg = f"<b>{header}</b>\n━━━━━━━━━━━━━━━━━━"
        
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
            
        msg += "\n━━━━━━━━━━━━━━━━━━\n<i>💡 Chỉ gửi đúng 1 thông báo duy nhất & đã tính sẵn mức Limit/Stop!</i>"
        send_telegram(msg, reply_markup=get_main_keyboard())
    except Exception as e:
        print(f"Lỗi scan: {e}")
        send_telegram(f"Lỗi quét: {e}", reply_markup=get_main_keyboard())

# ==========================================
# 2. PHÂN TÍCH BITCOIN TRỰC TIẾP QUA BYBIT (KHÔNG BỊ 418 IP BLOCK)
# ==========================================
def handle_btc():
    try:
        url = 'https://api.bybit.com/v5/market/tickers?category=linear&symbol=BTCUSDT'
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            item = data['result']['list'][0]
            
        price = float(item['lastPrice'])
        change = float(item.get('price24hPcnt', 0)) * 100.0
        vol = float(item.get('turnover24h', 0)) / 1000000
        
        is_uptrend = change >= 0
        s_emoji = "🟢 LONG" if is_uptrend else "🔴 SHORT"
        
        if is_uptrend:
            entry_limit = round(price * 0.992, 1)
            entry_stop = round(price * 1.008, 1)
            sl = round(entry_limit * 0.98, 1)
            tp1 = round(entry_limit * 1.04, 1)
            tp2 = round(entry_limit * 1.07, 1)
            action_limit = "Mua Giá Thấp Đón Râu Hồi"
            action_stop = "Mua Đuổi Phá Đỉnh"
        else:
            entry_limit = round(price * 1.008, 1)
            entry_stop = round(price * 0.992, 1)
            sl = round(entry_limit * 1.02, 1)
            tp1 = round(entry_limit * 0.96, 1)
            tp2 = round(entry_limit * 0.93, 1)
            action_limit = "Bán Giá Cao Đón Râu Hồi Cản"
            action_stop = "Bán Tháo Thủng Đáy H4"
            
        text = f"""👑 <b>[CHIẾN LƯỢC BITCOIN (BTC/USDT) - H4 & D1]</b> 👑
━━━━━━━━━━━━━━━━━━
💰 Giá hiện tại: <b>${price:,.1f}</b>
🎯 Xu hướng 24h: <b>{change:+.2f}%</b> (Vol: ${vol:,.1f}M)
━━━━━━━━━━━━━━━━━━
🚀 <b>CHIẾN LƯỢC: {s_emoji}</b>
👉 <b>1. LỆNH LIMIT ({action_limit}):</b>
   <code>${entry_limit:,.1f}</code>
👉 <b>2. LỆNH STOP ({action_stop}):</b>
   <code>${entry_stop:,.1f}</code>

🛡️ <b>Cắt lỗ (SL):</b> <code>${sl:,.1f}</code> (-2.0%)
🎯 <b>Chốt lời 1 (TP1 - R:R 1:2):</b> <code>${tp1:,.1f}</code>
🎯 <b>Chốt lời 2 (TP2 - R:R 1:3.5):</b> <code>${tp2:,.1f}</code>

🛡️ <b>QUẢN LÝ VỐN CHUẨN (${CONFIG['ACCOUNT_BALANCE']:,.0f}):</b>
• Rủi ro tối đa 2%: <b>${CONFIG['ACCOUNT_BALANCE']*CONFIG['RISK_PER_TRADE']/100:.1f}</b>
• Khối lượng vị thế: <b>$1,000.0</b> | Đòn bẩy đề xuất: <b>5x</b>
• Margin cần dùng: <b>$200.0 (20% vốn)</b>"""
        send_telegram(text, reply_markup=get_main_keyboard())
    except Exception as e:
        send_telegram(f"Lỗi BTC: {e}", reply_markup=get_main_keyboard())

# ==========================================
# 3. PHÂN TÍCH VÀNG TRỰC TIẾP TỪ TRADINGVIEW (OANDA:XAUUSD)
# ==========================================
def handle_gold():
    try:
        url = 'https://scanner.tradingview.com/cfd/scan'
        payload = json.dumps({
            'symbols': {'tickers': ['OANDA:XAUUSD']},
            'columns': ['close', 'open', 'high', 'low', 'close|240', 'high|240', 'low|240', 'EMA20|240']
        }).encode()
        req = urllib.request.Request(url, data=payload, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            row = data['data'][0]['d']
            
        d1_close = row[0]
        price = row[4] # H4 close
        h4_high = row[5]
        h4_low = row[6]
        ema_20_h4 = row[7]
        
        is_uptrend = price >= ema_20_h4
        s_emoji = "🟢 LONG" if is_uptrend else "🔴 SHORT"
        
        if not is_uptrend: # SHORT VÀNG
            entry_limit = round(price + 8.0, 2) # Đón râu hồi lên cản
            entry_stop = round(h4_low - 1.5, 2) # Thủng đáy H4
            sl = round(entry_limit + 20.0, 2)   # SL ĐÚNG 20 GIÁ
            tp1 = round(entry_limit - 40.0, 2)  # ĂN 40 GIÁ
            tp2 = round(entry_limit - 70.0, 2)  # ĂN 70 GIÁ
            action_l = "LỆNH 1: Bán Giá Cao Đón Râu Hồi Cản"
            action_s = "LỆNH 2: Bán Đuổi Phá Đáy Xác Nhận Sóng Xả"
            advice = (
                "⚠️ CẮT LỖ SỚM: Nếu có nến H1/H4 đóng cửa vượt cản $3,565 thì chủ động cắt sớm bằng tay!\n"
                "💎 DCA GIA TĂNG LỢI NHUẬN: Khi giá giảm có lãi > 20 giá, dời SL về Hòa vốn và nhồi thêm Lệnh 2 (Sell Stop)!"
            )
        else: # LONG VÀNG
            entry_limit = round(price - 8.0, 2)
            entry_stop = round(h4_high + 1.5, 2)
            sl = round(entry_limit - 20.0, 2)
            tp1 = round(entry_limit + 40.0, 2)
            tp2 = round(entry_limit + 70.0, 2)
            action_l = "LỆNH 1: Mua Giá Thấp Đón Râu Hồi Hỗ Trợ"
            action_s = "LỆNH 2: Mua Đuổi Phá Đỉnh Xác Nhận Sóng Tăng"
            advice = (
                "⚠️ CẮT LỖ SỚM: Nếu có nến H1/H4 gãy hỗ trợ thì chủ động cắt sớm!\n"
                "💎 DCA GIA TĂNG LỢI NHUẬN: Khi giá tăng có lãi > 20 giá, dời SL về Hòa vốn và nhồi thêm Lệnh 2!"
            )
            
        text = f"""🥇 <b>[CHIẾN LƯỢC VÀNG THẾ GIỚI (OANDA:XAUUSD) - H4 & D1]</b> 🥇
━━━━━━━━━━━━━━━━━━
📊 Nguồn biểu đồ: <b>TradingView (OANDA)</b>
💰 Giá Vàng hiện tại: <b>${price:,.2f}</b>
📈 Xu hướng H4: <b>{'DOWNTREND H4 (Thiên Short)' if not is_uptrend else 'UPTREND H4 (Thiên Long)'}</b>
━━━━━━━━━━━━━━━━━━
🚀 <b>CHIẾN LƯỢC: {s_emoji} (CHIA 2 LỆNH VÀO)</b>
👉 <b>{action_l}:</b>
   <code>${entry_limit:,.2f}</code>
👉 <b>{action_s}:</b>
   <code>${entry_stop:,.2f}</code>

🛡️ <b>Cắt lỗ (SL Chuẩn 20 Giá):</b> <code>${sl:,.2f}</code>
🎯 <b>Chốt lời 1 (TP1 - Ăn 40 Giá):</b> <code>${tp1:,.2f}</code>
🎯 <b>Chốt lời 2 (TP2 - Ăn 70 Giá):</b> <code>${tp2:,.2f}</code>

🧠 <b>KẾ HOẠCH XỬ LÝ LỆNH CHỦ ĐỘNG:</b>
{advice}

🛡️ <b>QUẢN LÝ VỐN VÀNG (${CONFIG['ACCOUNT_BALANCE']:,.0f}):</b>
• Rủi ro tối đa 2%: <b>$20.0</b>
• Quy mô vị thế đề xuất: <b>$2,500.0</b> | Đòn bẩy: <b>5x</b>
• Margin cần dùng: <b>$500.0</b>"""
        send_telegram(text, reply_markup=get_main_keyboard())
    except Exception as e:
        send_telegram(f"Lỗi Vàng: {e}", reply_markup=get_main_keyboard())

# ==========================================
# 4. SERVER HEALTH CHECK & BOT LOOP
# ==========================================
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
            print(f"Health server running on port {port}")
            httpd.serve_forever()
    except Exception as e:
        print(f"Health server error: {e}")

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
            print(f"Lỗi: {e}")
            time.sleep(3)

def self_ping_worker():
    """Tự động ping chính mình mỗi 10 phút để Render Free không bao giờ rơi vào trạng thái ngủ"""
    time.sleep(20)
    while True:
        try:
            url = "https://coinradar-tele-bot.onrender.com"
            req = urllib.request.Request(url, headers={'User-Agent': 'KeepAlive/1.0'})
            with urllib.request.urlopen(req, timeout=10) as resp:
                print("Keep-alive ping:", resp.status)
        except Exception as e:
            print("Keep-alive ping fail:", e)
        time.sleep(600)

if __name__ == '__main__':
    threading.Thread(target=start_health_server, daemon=True).start()
    threading.Thread(target=self_ping_worker, daemon=True).start()
    run_bot()
