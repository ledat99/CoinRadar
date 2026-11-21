import json
import os
import ccxt
import time
import requests
from datetime import datetime

# --- CONFIGURATION ---
ACTIVE_TRADES_FILE = 'active_trades.json'
TRADE_HISTORY_FILE = 'trade_history.json'
TELEGRAM_BOT_TOKEN = '9051874352:AAFrnfJ8Mm0QF4wBlz8V3vYjYiqz5_sIVF8'
TELEGRAM_CHAT_ID = '6022180065'

# Khởi tạo sàn Binance Futures & Spot
binance = ccxt.binance({
    'enableRateLimit': True,
    'options': {'defaultType': 'future'}
})

def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Lỗi gửi Telegram: {e}")

def load_json(filepath):
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_json(filepath, data):
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Lỗi lưu file {filepath}: {e}")

def check_trades():
    trades = load_json(ACTIVE_TRADES_FILE)
    history = load_json(TRADE_HISTORY_FILE)
    today_str = datetime.now().strftime('%Y-%m-%d')
    
    if not trades:
        msg = "ℹ️ <b>Danh sách lệnh theo dõi hiện tại đang trống.</b>\nHãy bấm quét coin hoặc phân tích BTC/Vàng để thêm lệnh theo dõi mới."
        send_telegram_message(msg)
        return
    
    remaining_trades = []
    closed_today = []
    
    for trade in trades:
        symbol = trade['symbol']
        try:
            # Chuẩn hoá symbol
            fetch_sym = f"{symbol}:USDT" if ':USDT' not in symbol and '/' in symbol else symbol
            ohlcv = binance.fetch_ohlcv(fetch_sym, '15m', limit=2)
            if not ohlcv or len(ohlcv) < 2:
                remaining_trades.append(trade)
                continue
                
            current_candle = ohlcv[-1]
            high = current_candle[2]
            low = current_candle[3]
            curr_price = current_candle[4]
            
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
                
                # Lưu vào lịch sử
                trade_record = {
                    'symbol': symbol,
                    'type': trade['type'],
                    'entry': trade['entry'],
                    'exit': trade['tp1'] if status == 'WIN' else trade['sl'],
                    'status': status,
                    'pnl_percent': pnl_percent,
                    'closed_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'date': today_str
                }
                history.append(trade_record)
                closed_today.append(trade_record)
                
                msg = f"""{emoji} <b>[KẾT QUẢ LỆNH {trade['type']}]</b> {emoji}
📌 Cặp: <b>{symbol}</b>
📊 Trạng thái: Đã chạm <b>{result_text}</b>
💰 PnL: <b>{pnl_percent:+.2f}%</b>

• Giá vào (Entry): {trade['entry']}
• Cắt lỗ (SL): {trade['sl']}
• Chốt lời (TP1): {trade['tp1']}"""
                send_telegram_message(msg)
            else:
                # Tính tạm floating PnL
                if trade['type'] == 'LONG':
                    float_pnl = (curr_price - trade['entry']) / trade['entry'] * 100
                else:
                    float_pnl = (trade['entry'] - curr_price) / trade['entry'] * 100
                trade['current_price'] = curr_price
                trade['floating_pnl'] = float_pnl
                remaining_trades.append(trade)
                
            time.sleep(0.1)
        except Exception as e:
            remaining_trades.append(trade)
            
    # Lưu lại danh sách lệnh còn mở và lịch sử
    save_json(ACTIVE_TRADES_FILE, remaining_trades)
    save_json(TRADE_HISTORY_FILE, history)
    
    # Tạo bảng BÁO CÁO TỔNG KẾT THEO NGÀY
    send_daily_summary(today_str, remaining_trades, history)

def send_daily_summary(today_str, remaining_trades, history):
    today_trades = [t for t in history if t.get('date') == today_str]
    win_count = len([t for t in today_trades if t['status'] == 'WIN'])
    loss_count = len([t for t in today_trades if t['status'] == 'LOSS'])
    total_closed = win_count + loss_count
    
    win_rate = (win_count / total_closed * 100) if total_closed > 0 else 0
    total_pnl = sum([t['pnl_percent'] for t in today_trades])
    
    status_emoji = "🟢" if total_pnl > 0 else ("🔴" if total_pnl < 0 else "⚪")
    
    report = f"""📊 <b>[TỔNG KẾT GIAO DỊCH HÔM NAY - {today_str}]</b>
━━━━━━━━━━━━━━━━━━
🎯 Tổng lệnh đã đóng: <b>{total_closed}</b>
✅ Thắng (TP): <b>{win_count}</b> | ❌ Thua (SL): <b>{loss_count}</b>
📈 Tỷ lệ thắng (Winrate): <b>{win_rate:.1f}%</b>
💰 Tổng Lợi Nhuận ròng: <b>{total_pnl:+.2f}%</b> {status_emoji}
⏳ Số lệnh đang chạy: <b>{len(remaining_trades)}</b>
━━━━━━━━━━━━━━━━━━"""

    if remaining_trades:
        report += "\n\n📌 <b>Các lệnh đang chạy (Floating PnL):</b>"
        for t in remaining_trades[:6]:
            fpnl = t.get('floating_pnl', 0)
            f_emoji = "🟢" if fpnl >= 0 else "🔴"
            report += f"\n• {t['symbol']} ({t['type']}): <b>{fpnl:+.2f}%</b> {f_emoji}"
            
    send_telegram_message(report)

if __name__ == "__main__":
    check_trades()
