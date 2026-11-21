import os
import json
import time
import requests
import urllib.parse
from datetime import datetime

# Import các công cụ phân tích
from bias_analyzer import get_market_bias, analyze_major_asset, quick_scan_market
import ccxt

CONFIG = {
    'TELEGRAM_BOT_TOKEN': '9051874352:AAFrnfJ8Mm0QF4wBlz8V3vYjYiqz5_sIVF8',
    'TELEGRAM_CHAT_ID': '6022180065',
    'ACCOUNT_BALANCE': 1000.0, # Vốn mẫu mặc định (USDT)
    'RISK_PER_TRADE': 2.0,     # Chấp nhận rủi ro 2% vốn / lệnh
}

binance_futures = ccxt.binance({
    'enableRateLimit': True,
    'options': {'defaultType': 'future'}
})

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

def handle_btc():
    bias = get_market_bias()
    sig = analyze_major_asset('BTC/USDT', risk_capital_percent=CONFIG['RISK_PER_TRADE'], account_balance=CONFIG['ACCOUNT_BALANCE'])
    
    if not sig:
        send_telegram("⚠️ Không thể tải dữ liệu Bitcoin lúc này.")
        return
        
    s_emoji = "🟢 LONG" if sig['type'] == 'LONG' else "🔴 SHORT"
    action_limit_desc = "Bán Giá Cao Đón Râu Hồi EMA20" if sig['type'] == 'SHORT' else "Mua Giá Thấp Đón Râu Hỗ Trợ"
    action_stop_desc = "Bán Đuổi Phá Đáy H4" if sig['type'] == 'SHORT' else "Mua Đuổi Phá Đỉnh H4"
    
    text = f"""👑 <b>[CHIẾN LƯỢC BITCOIN (BTC/USDT) - H4 & D1]</b> 👑
━━━━━━━━━━━━━━━━━━
💰 Giá hiện tại: <b>${sig['market_price']:,.1f}</b>
🎯 Xu hướng H4: <b>{sig['trend']}</b>
📊 RSI H4: <b>{sig['rsi']:.1f}</b>
━━━━━━━━━━━━━━━━━━
🚀 <b>CHIẾN LƯỢC: {s_emoji}</b>
👉 <b>1. LỆNH LIMIT ({action_limit_desc}):</b>
   <code>${sig['entry_limit']:,.1f}</code>
👉 <b>2. LỆNH STOP ({action_stop_desc}):</b>
   <code>${sig['entry_stop']:,.1f}</code>

🛡️ <b>Cắt lỗ (SL H4):</b> <code>${sig['sl']:,.1f}</code> (-{sig['sl_percent']:.2f}%)
🎯 <b>Chốt lời 1 (TP1 - R:R 1:2):</b> <code>${sig['tp1']:,.1f}</code>
🎯 <b>Chốt lời 2 (TP2 - R:R 1:3.5):</b> <code>${sig['tp2']:,.1f}</code>

🛡️ <b>QUẢN LÝ VỐN CHUẨN (${CONFIG['ACCOUNT_BALANCE']:,.0f}):</b>
• Rủi ro tối đa 2%: <b>${CONFIG['ACCOUNT_BALANCE']*sig['risk_percent']/100:.1f}</b>
• Khối lượng vị thế: <b>${sig['position_size_usd']:,.1f}</b> | Đòn bẩy: <b>{sig['suggested_leverage']}</b>
• Margin cần dùng: <b>${sig['margin_usd']:,.1f} (~{sig['margin_percent']:.1f}% vốn)</b>"""
        
    send_telegram(text, reply_markup=get_main_keyboard())

def handle_gold():
    sig = analyze_major_asset('XAU/USDT', risk_capital_percent=CONFIG['RISK_PER_TRADE'], account_balance=CONFIG['ACCOUNT_BALANCE'])
    
    if not sig:
        send_telegram("⚠️ Không thể tải dữ liệu Vàng (OANDA:XAUUSD) lúc này.")
        return
        
    s_emoji = "🟢 LONG" if sig['type'] == 'LONG' else "🔴 SHORT"
    action_limit_desc = "Bán Giá Cao Đón Râu Hồi EMA20" if sig['type'] == 'SHORT' else "Mua Giá Thấp Đón Râu Hỗ Trợ"
    action_stop_desc = "Bán Đuổi Phá Đáy H4" if sig['type'] == 'SHORT' else "Mua Đuổi Phá Đỉnh H4"
    
    text = f"""🥇 <b>[CHIẾN LƯỢC VÀNG THẾ GIỚI (OANDA:XAUUSD) - H4 & D1]</b> 🥇
━━━━━━━━━━━━━━━━━━
📊 Nguồn biểu đồ: <b>TradingView (OANDA)</b>
💰 Giá Vàng hiện tại: <b>${sig['market_price']:,.2f}</b>
📈 Xu hướng D1: <b>{sig.get('d1_trend')}</b> | H4: <b>{sig.get('trend')}</b>
📊 RSI H4: <b>{sig['rsi']:.1f}</b>
━━━━━━━━━━━━━━━━━━
🚀 <b>CHIẾN LƯỢC: {s_emoji} (CHIA 2 LỆNH VÀO)</b>
👉 <b>{action_limit_desc}:</b>
   <code>${sig['entry_limit']:,.2f}</code>
👉 <b>{action_stop_desc}:</b>
   <code>${sig['entry_stop']:,.2f}</code>

🛡️ <b>Cắt lỗ (SL Chuẩn {sig.get('sl_dist', 20):.0f} Giá):</b> <code>${sig['sl']:,.2f}</code>
🎯 <b>Chốt lời 1 (TP1 - Ăn 40 Giá):</b> <code>${sig['tp1']:,.2f}</code>
🎯 <b>Chốt lời 2 (TP2 - Ăn 70 Giá):</b> <code>${sig['tp2']:,.2f}</code>

🧠 <b>KẾ HOẠCH XỬ LÝ LỆNH CHỦ ĐỘNG:</b>
{sig.get('advice_market', '')}

🛡️ <b>QUẢN LÝ VỐN VÀNG (${CONFIG['ACCOUNT_BALANCE']:,.0f}):</b>
• Rủi ro tối đa 2%: <b>${CONFIG['ACCOUNT_BALANCE']*sig['risk_percent']/100:.1f}</b>
• Khối lượng vị thế: <b>${sig['position_size_usd']:,.1f}</b> | Đòn bẩy: <b>{sig['suggested_leverage']}</b>
• Margin cần dùng: <b>${sig['margin_usd']:,.1f} (~{sig['margin_percent']:.1f}% vốn)</b>"""
        
    send_telegram(text, reply_markup=get_main_keyboard())

def handle_check():
    send_telegram("🔍 Đang kiểm tra trạng thái các lệnh và tạo Báo Cáo Ngày...")
    from check_trades import check_trades
    try:
        check_trades()
    except Exception as e:
        send_telegram(f"Lỗi kiểm tra lệnh: {e}", reply_markup=get_main_keyboard())

def handle_scan(mode='long'):
    # Không gửi tin nhắn đệm 'Đang quét...' nữa để tránh spam nhiều tin nhắn
    from bias_analyzer import quick_scan_market
    results = quick_scan_market(mode=mode, limit=3)
    if not results:
        action_vn = "TĂNG (LONG)" if mode == 'long' else "GIẢM (SHORT)"
        send_telegram(f"⚠️ Hiện tại thị trường đang nén biên độ, chưa có coin nào đạt chuẩn {action_vn} có CHoCH & Test cản an toàn.")
        return
        
    active_trades = []
    if os.path.exists('active_trades.json'):
        try:
            with open('active_trades.json', 'r', encoding='utf-8') as f:
                active_trades = json.load(f)
        except Exception:
            active_trades = []
            
    header = "🚀 [TOP COIN TIỀM NĂNG TĂNG - LONG]" if mode == 'long' else "📉 [TOP COIN TIỀM NĂNG GIẢM - SHORT]"
    msg = f"<b>{header}</b>\n━━━━━━━━━━━━━━━━━━"
    
    for i, r in enumerate(results, 1):
        if not any(t['symbol'] == r['symbol'] for t in active_trades):
            active_trades.append({
                'symbol': r['symbol'],
                'type': r['type'],
                'entry': r['entry_limit'],
                'sl': r['sl'],
                'tp1': r['tp1']
            })
            
        emoji = "🟢" if mode == 'long' else "🔴"
        msg += f"""
{i}. <b>{r['symbol']}</b> {emoji} (Vol 24h: ${r['vol_m']:.1f}M)
• Giá thị trường: <b>{r['market_price']}</b> | RSI: <b>{r['rsi']:.1f}</b>
🎯 <b>Trạng thái:</b> <i>{r.get('stop_status', 'Bình thường')}</i>
👉 <b>{r['limit_label']}:</b> <code>{r['entry_limit']}</code>
👉 <b>{r['stop_label']}:</b> <code>{r['entry_stop']}</code>
🛡️ <b>Cắt lỗ (SL):</b> <code>{r['sl']:.4f}</code> (-{r['sl_pct']:.1f}%)
🎯 <b>Chốt lời (TP1):</b> <code>{r['tp1']:.4f}</code> [R:R 1:2]
🎯 <b>Chốt lời (TP2):</b> <code>{r['tp2']:.4f}</code> [R:R 1:3.5]"""

    msg += "\n━━━━━━━━━━━━━━━━━━\n<i>💡 Chỉ gửi đúng 1 tin nhắn duy nhất & đã tự động lưu để theo dõi TP/SL!</i>"
    
    with open('active_trades.json', 'w', encoding='utf-8') as f:
        json.dump(active_trades, f, indent=4)
        
    send_telegram(msg, reply_markup=get_main_keyboard())

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
        
    send_telegram(
        "👋 <b>Bot Săn Kèo & Báo Cáo Ngày Đã Sẵn Sàng!</b>\n"
        "Bấm vào các nút bên dưới để nhận phân tích:",
        reply_markup=get_main_keyboard()
    )
    
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
                    elif text in ["/check", "🔍 Kiểm Tra Lệnh & Báo Cáo Ngày", "check"]:
                        handle_check()
                    elif text in ["/long", "📈 Tìm Coin TĂNG (LONG)", "long"]:
                        handle_scan(mode='long')
                    elif text in ["/short", "📉 Tìm Coin GIẢM (SHORT)", "short"]:
                        handle_scan(mode='short')
            time.sleep(1)
        except Exception as e:
            print(f"Lỗi: {e}")
            time.sleep(3)

import http.server
import socketserver
import threading

def start_health_server():
    """Tạo một server HTTP siêu nhẹ để Render nhận diện port và giữ bot Live 24/7"""
    port = int(os.environ.get('PORT', 8080))
    class HealthHandler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'Bot is running healthy!')
        def log_message(self, format, *args):
            return
    try:
        with socketserver.TCPServer(('', port), HealthHandler) as httpd:
            print(f'Health server running on port {port}')
            httpd.serve_forever()
    except Exception as e:
        print(f'Health server error: {e}')

if __name__ == '__main__':
    # Chạy server HTTP nền cho Render
    threading.Thread(target=start_health_server, daemon=True).start()
    run_bot()
