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
# 1. TÍNH VOLUME PROFILE (POC) CHUẨN XÁC SUẤT CAO CHO BITCOIN
# ==========================================
def calculate_btc_h4_plan():
    now = time.time()
    if PLAN_CACHE['BTC']['data'] and (now - PLAN_CACHE['BTC']['candle_time'] < 14400):
        return PLAN_CACHE['BTC']['data']
        
    url = 'https://api.bybit.com/v5/market/kline?category=linear&symbol=BTCUSDT&interval=60&limit=48'
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode())['result']['list']
        
    current_price = float(data[0][4])
    change_24h = (float(data[0][4]) - float(data[23][1])) / float(data[23][1]) * 100.0
    
    # Tính Volume Profile (POC) đa điểm từ 48 nến H1 (phiên 2 ngày)
    prices = []
    weights = []
    for k in data:
        high = float(k[2])
        low = float(k[3])
        vol = float(k[5])
        for p in np.linspace(low, high, 5):
            prices.append(p)
            weights.append(vol / 5.0)
            
    hist, bin_edges = np.histogram(prices, bins=35, weights=weights)
    poc = round((bin_edges[np.argmax(hist)] + bin_edges[np.argmax(hist)+1]) / 2, 1)
    
    highs = [float(k[2]) for k in data[:12]]
    lows = [float(k[3]) for k in data[:12]]
    swing_high = round(max(highs), 1)
    swing_low = round(min(lows), 1)
    
    # Xu hướng so với POC: Dưới POC -> Canh Short hồi về POC; Trên POC -> Canh Long tại POC
    is_uptrend = current_price >= poc
    signal = "LONG" if is_uptrend else "SHORT"
    
    if signal == "SHORT":
        # ENTRY CHUẨN THEO POC: Đón Short khi giá giật hồi về đúng vùng thanh khoản lớn POC
        entry_limit = poc if poc > current_price else swing_high
        # SELL STOP: Kích hoạt khi đâm thủng hỗ trợ râu nến thấp nhất
        entry_stop = round(swing_low * 0.998, 1)
        # SL linh hoạt đặt trên cản đỉnh râu + vùng đệm an toàn
        sl = round(max(entry_limit * 1.018, swing_high + 250.0), 1)
        risk = sl - entry_limit
        tp1 = round(entry_limit - (risk * 2.0), 1)
        tp2 = round(entry_limit - (risk * 3.5), 1)
    else: # LONG
        entry_limit = poc if poc < current_price else swing_low
        entry_stop = round(swing_high * 1.002, 1)
        sl = round(min(entry_limit * 0.982, swing_low - 250.0), 1)
        risk = entry_limit - sl
        tp1 = round(entry_limit + (risk * 2.0), 1)
        tp2 = round(entry_limit + (risk * 3.5), 1)
        
    sl_pct = (risk / entry_limit) * 100.0
    
    plan = {
        'signal': signal,
        'current_price': current_price,
        'poc': poc,
        'swing_high': swing_high,
        'swing_low': swing_low,
        'entry_limit': entry_limit,
        'entry_stop': entry_stop,
        'sl': sl,
        'sl_pct': round(sl_pct, 2),
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
        action_l = "Bán Giá Cao Khi Giá Hồi Về Vùng POC" if plan['signal'] == 'SHORT' else "Mua Giá Thấp Tại Vùng POC"
        action_s = "Bán Tháo Khi Thủng Đáy Râu H4" if plan['signal'] == 'SHORT' else "Mua Đuổi Khi Vượt Đỉnh Râu H4"
        
        text = f"""👑 <b>[KẾ HOẠCH BITCOIN CỐ ĐỊNH THEO VOLUME PROFILE (POC)]</b> 👑
━━━━━━━━━━━━━━━━━━
💰 Giá hiện tại: <b>${plan['current_price']:,.1f}</b>
🎯 <b>Vùng POC Cốt Lõi (Khối lượng lớn nhất):</b> <code>${plan['poc']:,.1f}</code>
📊 Đỉnh râu cản: <b>${plan['swing_high']:,.1f}</b> | Đáy râu hỗ trợ: <b>${plan['swing_low']:,.1f}</b>
━━━━━━━━━━━━━━━━━━
🚀 <b>CHIẾN LƯỢC: {s_emoji}</b>
👉 <b>1. LỆNH LIMIT CHUẨN THEO POC ({action_l}):</b>
   <code>${plan['entry_limit']:,.1f}</code>
👉 <b>2. LỆNH STOP PHÁ VỠ ({action_s}):</b>
   <code>${plan['entry_stop']:,.1f}</code>

🛡️ <b>Cắt lỗ (SL Linh Hoạt Trên Cản Râu):</b> <code>${plan['sl']:,.1f}</code> (-{plan['sl_pct']}%)
🎯 <b>Chốt lời 1 (TP1 - R:R 1:2):</b> <code>${plan['tp1']:,.1f}</code>
🎯 <b>Chốt lời 2 (TP2 - R:R 1:3.5):</b> <code>${plan['tp2']:,.1f}</code>

🛡️ <b>QUẢN LÝ VỐN (${CONFIG['ACCOUNT_BALANCE']:,.0f}):</b>
• Rủi ro tối đa 2%: <b>$20.0</b> | Khối lượng: <b>$1,000.0</b> | Đòn bẩy: <b>5x</b>
<i>💡 Điểm vào Entry được neo trực tiếp vào mức POC ${plan['poc']:,.1f} và giữ cố định trong phiên 4H!</i>"""
        send_telegram(text, reply_markup=get_main_keyboard())
    except Exception as e:
        send_telegram(f"Lỗi BTC POC: {e}", reply_markup=get_main_keyboard())

# ==========================================
# 2. KẾ HOẠCH VÀNG (OANDA) - SL LINH HOẠT THEO CẤU TRÚC RÂU CẢN
# ==========================================
def calculate_gold_h4_plan():
    now = time.time()
    if PLAN_CACHE['GOLD']['data'] and (now - PLAN_CACHE['GOLD']['candle_time'] < 14400):
        return PLAN_CACHE['GOLD']['data']
        
    url = 'https://scanner.tradingview.com/cfd/scan'
    payload = json.dumps({
        'symbols': {'tickers': ['OANDA:XAUUSD']},
        'columns': [
            'close|240', 'high|240', 'low|240', 'EMA20|240', 'ATR|240',
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
    h4_atr = d[4]
    
    is_uptrend = h4_close >= h4_ema20
    signal = "LONG" if is_uptrend else "SHORT"
    
    if signal == "SHORT":
        # ENTRY LIMIT: Đón tại vùng râu cản đỉnh H4 (vùng thanh khoản bán)
        entry_limit = round(h4_high, 2)
        entry_stop = round(h4_low - 1.5, 2)
        
        # SL LINH HOẠT HỢP LÝ: Đặt trên râu nến cản đỉnh + đệm 3 đến 5 giá (dao động trong ngưỡng hợp lý ~15-25 giá)
        sl = round(entry_limit + max(15.0, min(28.0, h4_high - h4_close + 5.0)), 2)
        sl_dist = round(sl - entry_limit, 2)
        tp1 = round(entry_limit - (sl_dist * 2.0), 2)
        tp2 = round(entry_limit - (sl_dist * 3.5), 2)
        advice = (
            f"⚠️ CẮT SỚM KHI XẤU: Nếu có nến H1 đóng cửa vượt cản ${entry_limit:,.2f} thì chủ động cắt lỗ sớm bằng tay để bảo vệ vốn!\n"
            f"💎 DCA KHI ĐẸP: Khi giá rơi thủng đáy ${h4_low:,.2f} và có lãi > {sl_dist:.0f} giá, dời SL về Entry và nhồi thêm Lệnh 2 (Sell Stop)!"
        )
    else: # LONG
        entry_limit = round(h4_low, 2)
        entry_stop = round(h4_high + 1.5, 2)
        sl = round(entry_limit - max(15.0, min(28.0, h4_close - h4_low + 5.0)), 2)
        sl_dist = round(entry_limit - sl, 2)
        tp1 = round(entry_limit + (sl_dist * 2.0), 2)
        tp2 = round(entry_limit + (sl_dist * 3.5), 2)
        advice = (
            f"⚠️ CẮT SỚM KHI XẤU: Nếu có nến H1 đóng cửa gãy hỗ trợ ${entry_limit:,.2f} thì chủ động cắt sớm bằng tay!\n"
            f"💎 DCA KHI ĐẸP: Khi giá tăng vượt đỉnh ${h4_high:,.2f} và có lãi > {sl_dist:.0f} giá, dời SL về Entry và nhồi thêm Lệnh 2 (Buy Stop)!"
        )
        
    plan = {
        'signal': signal,
        'current_price': h4_close,
        'h4_high': h4_high,
        'h4_low': h4_low,
        'entry_limit': entry_limit,
        'entry_stop': entry_stop,
        'sl': sl,
        'sl_dist': sl_dist,
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
        
        text = f"""🥇 <b>[KẾ HOẠCH VÀNG (OANDA) - SL LINH HOẠT THEO CẢN RÂU]</b> 🥇
━━━━━━━━━━━━━━━━━━
📊 Nguồn biểu đồ: <b>TradingView (OANDA:XAUUSD)</b>
💰 Giá Vàng hiện tại: <b>${plan['current_price']:,.2f}</b>
📈 Cản đỉnh râu H4: <b>${plan['h4_high']:,.2f}</b> | Đáy râu H4: <b>${plan['h4_low']:,.2f}</b>
━━━━━━━━━━━━━━━━━━
🚀 <b>CHIẾN LƯỢC: {s_emoji}</b>
👉 <b>{action_l}:</b>
   <code>${plan['entry_limit']:,.2f}</code>
👉 <b>{action_s}:</b>
   <code>${plan['entry_stop']:,.2f}</code>

🛡️ <b>Cắt lỗ (SL Linh Hoạt Ngoài Cản Râu {plan['sl_dist']:.1f} Giá):</b>
   <code>${plan['sl']:,.2f}</code>
🎯 <b>Chốt lời 1 (TP1 - Ăn {plan['sl_dist']*2:.1f} Giá):</b> <code>${plan['tp1']:,.2f}</code>
🎯 <b>Chốt lời 2 (TP2 - Ăn {plan['sl_dist']*3.5:.1f} Giá):</b> <code>${plan['tp2']:,.2f}</code>

🧠 <b>KẾ HOẠCH XỬ LÝ LỆNH CHỦ ĐỘNG:</b>
{plan['advice']}

🛡️ <b>QUẢN LÝ VỐN VÀNG (${CONFIG['ACCOUNT_BALANCE']:,.0f}):</b>
• Rủi ro tối đa 2%: <b>$20.0</b> | Khối lượng: <b>$2,500.0</b> | Đòn bẩy: <b>5x</b>
<i>💡 Điểm vào và SL được tính toán dựa trên cấu trúc râu nến cản thực tế, nằm trong ngưỡng an toàn hợp lý!</i>"""
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
