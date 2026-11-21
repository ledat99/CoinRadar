import json
import os
import ccxt
import time
import requests

# --- CONFIGURATION ---
ACTIVE_TRADES_FILE = 'active_trades.json'
TELEGRAM_BOT_TOKEN = '9051874352:AAFrnfJ8Mm0QF4wBlz8V3vYjYiqz5_sIVF8'
TELEGRAM_CHAT_ID = '6022180065'

# Khởi tạo sàn Binance
binance = ccxt.binance({
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

def check_trades():
    trades = load_active_trades()
    if not trades:
        print("Trống! Không có lệnh nào đang mở để kiểm tra.")
        return
    
    remaining_trades = []
    print(f"\n🔍 Đang kiểm tra trạng thái {len(trades)} lệnh cũ...")
    
    for trade in trades:
        symbol = trade['symbol']
        try:
            ohlcv = binance.fetch_ohlcv(symbol, '15m', limit=2)
            if not ohlcv or len(ohlcv) < 2:
                remaining_trades.append(trade)
                continue
                
            current_candle = ohlcv[-1]
            high = current_candle[2]
            low = current_candle[3]
            
            status = None
            pnl_percent = 0
            
            if trade['type'] == 'LONG':
                if low <= trade['sl']:
                    status = 'LOSS'
                    pnl_percent = (trade['sl'] - trade['entry']) / trade['entry'] * 100
                elif high >= trade['tp1']:
                    status = 'WIN'
                    pnl_percent = (trade['tp1'] - trade['entry']) / trade['entry'] * 100
            else: # SHORT
                if high >= trade['sl']:
                    status = 'LOSS'
                    pnl_percent = (trade['entry'] - trade['sl']) / trade['entry'] * 100
                elif low <= trade['tp1']:
                    status = 'WIN'
                    pnl_percent = (trade['entry'] - trade['tp1']) / trade['entry'] * 100
                    
            if status:
                emoji = "🟢" if status == "WIN" else "🔴"
                result_text = "CHỐT LỜI (TP1)" if status == "WIN" else "CẮT LỖ (SL)"
                msg = f"""{emoji} <b>[KẾT QUẢ LỆNH {trade['type']}]</b> {emoji}
📌 Coin: <b>{symbol}</b>
📊 Trạng thái: Đã chạm <b>{result_text}</b>
💰 PnL: <b>{pnl_percent:+.2f}%</b>

Giá vào: {trade['entry']}
SL: {trade['sl']}
TP1: {trade['tp1']}
"""
                send_telegram_message(msg)
                print(f"[{status}] {symbol} đã xong ({pnl_percent:+.2f}%)")
            else:
                print(f"[ĐANG CHỜ] {symbol} chưa chạm TP hay SL.")
                remaining_trades.append(trade)
                
        except Exception as e:
            print(f"Lỗi kiểm tra {symbol}: {e}")
            remaining_trades.append(trade)
            
        time.sleep(0.2)
        
    save_active_trades(remaining_trades)
    print("✅ Hoàn tất kiểm tra!")

if __name__ == '__main__':
    check_trades()
