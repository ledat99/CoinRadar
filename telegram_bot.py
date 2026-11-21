import os
import json
import time
import requests
import urllib.parse
from datetime import datetime

# Import các công cụ phân tích
from bias_analyzer import get_market_bias, analyze_major_asset
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
            [{"text": "🔍 Kiểm Tra Lệnh (SL/TP)"}, {"text": "⚙️ Menu Hỗ Trợ"}]
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
    send_telegram("⏳ Đang phân tích thị trường Vàng thế giới (XAU/USDT - Volume > 4 Tỷ USD)...")
    sig = analyze_major_asset('XAU/USDT', risk_capital_percent=CONFIG['RISK_PER_TRADE'], account_balance=CONFIG['ACCOUNT_BALANCE'])
    
    if not sig:
        send_telegram("⚠️ Không thể tải dữ liệu Vàng (XAU/USDT) lúc này.")
        return
        
    text = f"""🥇 <b>[CHIẾN LƯỢC VÀNG THẾ GIỚI (XAU/USDT)]</b> 🥇
━━━━━━━━━━━━━━━━━━
💰 Giá Vàng thế giới: <b>${sig.get('price', sig.get('entry', 0)):,.2f}</b>
📊 RSI M15: <b>{sig['rsi']:.1f}</b>
🌊 Thanh khoản: <b>Khủng (> $4 Tỷ USD / 24h)</b>
━━━━━━━━━━━━━━━━━━"""

    if sig['has_signal']:
        s_emoji = "🟢 LONG" if sig['type'] == 'LONG' else "🔴 SHORT"
        text += f"""
🚀 <b>TÍN HIỆU VÀNG: {s_emoji}</b>
• Entry: <b>${sig['entry']:,.2f}</b>
• Cắt lỗ (SL): <b>${sig['sl']:,.2f}</b> (-{sig['sl_percent']:.2f}%)
• Chốt lời 1 (TP1 - R:R 1:2): <b>${sig['tp1']:,.2f}</b>
• Chốt lời 2 (TP2 - R:R 1:3): <b>${sig['tp2']:,.2f}</b>

🛡️ <b>QUẢN LÝ VỐN (Vốn mẫu: ${CONFIG['ACCOUNT_BALANCE']:,.0f}):</b>
• Rủi ro: <b>{sig['risk_percent']}% (${CONFIG['ACCOUNT_BALANCE']*sig['risk_percent']/100:.1f})</b>
• Quy mô lệnh (Size): <b>${sig['position_size_usd']:,.1f}</b>
• Đòn bẩy đề xuất: <b>{sig['suggested_leverage']}</b>
• Margin cần dùng: <b>${sig['margin_usd']:,.1f}</b>"""
    else:
        trend_vi = "TĂNG" if sig.get('trend') == 'UPTREND' else "GIẢM"
        text += f"\n\n📈 Xu hướng tổng thể: <b>{trend_vi}</b>\n⏳ Chưa có tín hiệu vào lệnh đẹp. Tiếp tục theo dõi vùng hỗ trợ / kháng cự."
        
    send_telegram(text, reply_markup=get_main_keyboard())

def handle_check():
    send_telegram("🔍 Đang chạy kiểm tra các lệnh cũ trong danh sách...")
    import subprocess
    try:
        output = subprocess.check_output(["py", "check_trades.py"], text=True, timeout=60)
        # check_trades tự gửi Telegram nếu có kết quả
        send_telegram("✅ Đã hoàn tất kiểm tra trạng thái lệnh!", reply_markup=get_main_keyboard())
    except Exception as e:
        send_telegram(f"Lỗi kiểm tra lệnh: {e}", reply_markup=get_main_keyboard())

def handle_scan(mode='long'):
    action_text = "TĂNG (LONG / Tích lũy gom hàng)" if mode == 'long' else "GIẢM (SHORT / Phân phối xả hàng)"
    send_telegram(f"🔍 <b>Đang kích hoạt bộ lọc Coin {action_text}...</b>\nBot đang quét toàn thị trường và đối chiếu dòng tiền 4h/12h + Market Bias...")
    import subprocess
    try:
        # Chạy scanner với tham số
        subprocess.Popen(["py", "crypto_scanner.py", f"--mode={mode}"])
        send_telegram("🚀 Scanner đang chạy ngầm, ngay khi phát hiện coin có điểm vào đẹp và dòng tiền đồng thuận sẽ báo ngay cho bạn!", reply_markup=get_main_keyboard())
    except Exception as e:
        send_telegram(f"Lỗi kích hoạt scanner: {e}", reply_markup=get_main_keyboard())

def run_bot():
    print("🤖 Bot Telegram đang khởi động và lắng nghe lệnh...")
    url = f"https://api.telegram.org/bot{CONFIG['TELEGRAM_BOT_TOKEN']}/getUpdates"
    
    # Xoá sạch toàn bộ tin nhắn tồn đọng trước khi bot khởi động để tránh lặp
    try:
        init_resp = requests.get(url, params={"offset": -1}, timeout=10).json()
        if init_resp.get("result"):
            last_update_id = init_resp["result"][-1]["update_id"]
            requests.get(url, params={"offset": last_update_id + 1}, timeout=10)
        else:
            last_update_id = 0
    except Exception as e:
        last_update_id = 0
        
    send_telegram(
        "👋 <b>Bot đã sẵn sàng!</b>\n"
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
                    elif text in ["/gold", "🥇 Phân Tích VÀNG (XAU)", "🥇 Phân Tích VÀNG (PAXG)", "gold", "vang", "Vàng"]:
                        handle_gold()
                    elif text in ["/check", "🔍 Kiểm Tra Lệnh (SL/TP)", "check"]:
                        handle_check()
                    elif text in ["/long", "📈 Tìm Coin TĂNG (LONG)", "/scan", "📊 Quét Coin Rác (Có Bias)", "scan", "long"]:
                        handle_scan(mode='long')
                    elif text in ["/short", "📉 Tìm Coin GIẢM (SHORT)", "📉 Tìm Coin Xả (SHORT)", "short"]:
                        handle_scan(mode='short')
            time.sleep(1)
        except Exception as e:
            print(f"Lỗi vòng lặp bot: {e}")
            time.sleep(3)

if __name__ == '__main__':
    run_bot()

