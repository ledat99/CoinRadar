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
    send_telegram("⏳ Đang phân tích Market Bias & Xu hướng Bitcoin...")
    bias = get_market_bias()
    sig = analyze_major_asset('BTC/USDT', risk_capital_percent=CONFIG['RISK_PER_TRADE'], account_balance=CONFIG['ACCOUNT_BALANCE'])
    
    emoji_bias = "🟢" if bias['bias'] == 'BULLISH' else ("🔴" if bias['bias'] == 'BEARISH' else "⚪")
    
    text = f"""👑 <b>[CHIẾN LƯỢC BITCOIN (BTC/USDT)]</b> 👑
━━━━━━━━━━━━━━━━━━
💰 Giá hiện tại: <b>${bias['btc_price']:,.2f}</b>
🎯 Market Bias: <b>{bias['bias']}</b> {emoji_bias}
📈 Đánh giá: <i>{bias['desc']}</i>
📊 RSI: H1: <b>{bias['h1_rsi']:.1f}</b> | H4: <b>{bias['h4_rsi']:.1f}</b>
🌊 Điểm dòng tiền (Flow): <b>{bias['flow_score']}/100</b>
━━━━━━━━━━━━━━━━━━"""

    if sig and sig['has_signal']:
        s_emoji = "🟢 LONG" if sig['type'] == 'LONG' else "🔴 SHORT"
        text += f"""
🚀 <b>TÍN HIỆU ĐƯỢC KÍCH HOẠT: {s_emoji}</b>
• Entry: <b>${sig['entry']:,.2f}</b>
• Cắt lỗ (SL): <b>${sig['sl']:,.2f}</b> (-{sig['sl_percent']:.2f}%)
• Chốt lời 1 (TP1 - R:R 1:2): <b>${sig['tp1']:,.2f}</b>
• Chốt lời 2 (TP2 - R:R 1:3): <b>${sig['tp2']:,.2f}</b>

🛡️ <b>QUẢN LÝ VỐN CHUẨN (Vốn mẫu: ${CONFIG['ACCOUNT_BALANCE']:,.0f}):</b>
• Rủi ro tối đa mỗi lệnh: <b>{sig['risk_percent']}% (${CONFIG['ACCOUNT_BALANCE']*sig['risk_percent']/100:.1f})</b>
• Khối lượng vị thế (Size): <b>${sig['position_size_usd']:,.1f}</b>
• Đòn bẩy khuyến nghị: <b>{sig['suggested_leverage']}</b>
• Ký quỹ (Margin): <b>${sig['margin_usd']:,.1f} (~{sig['margin_percent']:.1f}% tài khoản)</b>"""
    else:
        text += f"\n\n⏳ <b>Khuyến nghị:</b> Hiện tại chưa có điểm vào lệnh R:R tối ưu trên khung 15m. Hãy kiên nhẫn chờ nến hồi về kiểm tra EMA hoặc theo dõi nến đóng cửa."
        
    send_telegram(text, reply_markup=get_main_keyboard())

def handle_gold():
    send_telegram("⏳ Đang phân tích biểu đồ OANDA:XAUUSD trực tiếp từ TradingView...")
    sig = analyze_major_asset('XAU/USDT', risk_capital_percent=CONFIG['RISK_PER_TRADE'], account_balance=CONFIG['ACCOUNT_BALANCE'])
    
    if not sig:
        send_telegram("⚠️ Không thể tải dữ liệu Vàng (OANDA:XAUUSD) lúc này.")
        return
        
    text = f"""🥇 <b>[CHIẾN LƯỢC VÀNG THẾ GIỚI (OANDA:XAUUSD)]</b> 🥇
━━━━━━━━━━━━━━━━━━
📊 Nguồn biểu đồ: <b>TradingView (OANDA)</b>
💰 Giá Vàng hiện tại: <b>${sig.get('price', sig.get('entry', 0)):,.2f}</b>
📈 RSI M15: <b>{sig['rsi']:.1f}</b>
🌊 Tick Volume M15: <b>{sig.get('volume', 0):,}</b>
━━━━━━━━━━━━━━━━━━"""

    if sig['has_signal']:
        s_emoji = "🟢 LONG" if sig['type'] == 'LONG' else "🔴 SHORT"
        text += f"""
🚀 <b>TÍN HIỆU VÀNG: {s_emoji}</b>
• Giá hiện tại: <b>${sig['market_price']:,.2f}</b>
👉 <b>Vùng LIMIT đón râu:</b> <code>${sig['entry_limit']:,.2f}</code>
👉 <b>Điểm STOP phá cản:</b> <code>${sig['entry_stop']:,.2f}</code>
• Cắt lỗ (SL): <b>${sig['sl']:,.2f}</b> (-{sig['sl_percent']:.2f}%)
• Chốt lời 1 (TP1 - R:R 1:2): <b>${sig['tp1']:,.2f}</b>
• Chốt lời 2 (TP2 - R:R 1:3.5): <b>${sig['tp2']:,.2f}</b>

🛡️ <b>QUẢN LÝ VỐN (Vốn mẫu: ${CONFIG['ACCOUNT_BALANCE']:,.0f}):</b>
• Rủi ro: <b>{sig['risk_percent']}% (${CONFIG['ACCOUNT_BALANCE']*sig['risk_percent']/100:.1f})</b>
• Quy mô vị thế: <b>${sig['position_size_usd']:,.1f}</b>
• Đòn bẩy đề xuất: <b>{sig['suggested_leverage']}</b>
• Ký quỹ (Margin): <b>${sig['margin_usd']:,.1f}</b>"""
    else:
        text += f"\n\n📈 Xu hướng tổng thể: <b>{sig.get('trend')}</b>\n👉 Gợi ý vùng Limit đón râu nến (EMA20): <code>${sig.get('suggested_limit', 0):,.2f}</code>\n⏳ Đang theo dõi nén biên độ quanh hỗ trợ / kháng cự."
        
    send_telegram(text, reply_markup=get_main_keyboard())

def handle_check():
    send_telegram("🔍 Đang kiểm tra trạng thái các lệnh và tạo Báo Cáo Ngày...")
    from check_trades import check_trades
    try:
        check_trades()
    except Exception as e:
        send_telegram(f"Lỗi kiểm tra lệnh: {e}", reply_markup=get_main_keyboard())

def handle_scan(mode='long'):
    action_text = "TĂNG (LONG)" if mode == 'long' else "GIẢM (SHORT)"
    send_telegram(f"🔍 <b>Đang quét siêu tốc các coin {action_text} có thanh khoản lớn & R:R tốt...</b>")
    
    results = quick_scan_market(mode=mode, limit=3)
    if not results:
        send_telegram("⚠️ Thị trường đang giằng co mạnh, chưa có coin nào thỏa mãn R:R 1:2 tối ưu.")
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
🎯 <b>Trạng thái cấu trúc:</b> <i>{r.get('stop_status', 'Bình thường')}</i>
👉 <b>{r['limit_label']}:</b> <code>{r['entry_limit']}</code>
👉 <b>{r['stop_label']}:</b> <code>{r['entry_stop']}</code>
🛡️ <b>Cắt lỗ (SL bảo vệ):</b> <code>{r['sl']:.4f}</code> (-{r['sl_pct']:.1f}%)
🎯 <b>Chốt lời (TP1 - R:R 1:2):</b> <code>{r['tp1']:.4f}</code>
🎯 <b>Chốt lời (TP2 - R:R 1:3.5):</b> <code>{r['tp2']:.4f}</code>"""

    msg += "\n━━━━━━━━━━━━━━━━━━\n<i>🛡️ Lưu ý: Chỉ vào lệnh STOP khi trạng thái ghi nhận 'ĐÃ TẠO CHoCH + TEST RÂU' để tránh tuyệt đối việc cản tàu!</i>"
    
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
