import os
import json
import time
import datetime
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

TZ_VN = datetime.timezone(datetime.timedelta(hours=7))
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

# Cache lưu trữ các mức cản H4 để cố định điểm vào lệnh trong phiên H4
PLAN_CACHE = {
    'BTC': {'candle_time': 0, 'data': None},
    'GOLD': {'candle_time': 0, 'data': None},
    'COINS_LONG': {'time': 0, 'data': []},
    'COINS_SHORT': {'time': 0, 'data': []}
}

LAST_ALERT_TIME = {
    'GOLD': 0,
    'BTC': 0
}

VIP_TRADES_FILE = os.path.join(os.path.dirname(__file__), 'vip_active_trades.json')
VIP_HISTORY_FILE = os.path.join(os.path.dirname(__file__), 'vip_trade_history.json')

def load_vip_trades():
    try:
        if os.path.exists(VIP_TRADES_FILE):
            with open(VIP_TRADES_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        print(f"Lỗi load_vip_trades: {e}")
    return []

def save_vip_trades(trades):
    try:
        with open(VIP_TRADES_FILE, 'w', encoding='utf-8') as f:
            json.dump(trades, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Lỗi save_vip_trades: {e}")

def load_vip_history():
    try:
        if os.path.exists(VIP_HISTORY_FILE):
            with open(VIP_HISTORY_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        print(f"Lỗi load_vip_history: {e}")
    return []

def save_vip_history(history):
    try:
        with open(VIP_HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Lỗi save_vip_history: {e}")

def record_new_vip_trade(asset, symbol, signal, entry_price, entry_stop, sl, tp1, tp2, sl_dist):
    trades = load_vip_trades()
    # Chỉ cho phép duy nhất 1 lệnh active cho mỗi symbol để chống spam tuyệt đối
    trades = [t for t in trades if t.get('symbol') != symbol]
    now_dt = datetime.datetime.now(TZ_VN)
    new_t = {
        'id': f"{asset}_{int(time.time())}",
        'asset': asset,
        'symbol': symbol,
        'signal': signal,
        'entry_price': entry_price,
        'entry_stop': entry_stop,
        'sl': sl,
        'orig_sl': sl,
        'tp1': tp1,
        'tp2': tp2,
        'sl_dist': sl_dist,
        'tp1_hit': False,
        'tp2_hit': False,
        'entry_time': now_dt.strftime('%H:%M %d/%m'),
        'entry_timestamp': time.time(),
        'status': 'RUNNING'
    }
    trades.append(new_t)
    save_vip_trades(trades)
    return new_t

def check_and_update_vip_trades(curr_gold_p, curr_btc_p):
    trades = load_vip_trades()
    if not trades:
        return
    history = load_vip_history()
    now_dt = datetime.datetime.now(TZ_VN)
    time_str = now_dt.strftime('%H:%M %d/%m')
    remaining = []

    for t in trades:
        is_gold = (t['asset'] == 'GOLD')
        curr_p = curr_gold_p if is_gold else curr_btc_p
        if not curr_p:
            remaining.append(t)
            continue

        sym_name = "Vàng (OANDA:XAUUSD MT5)" if is_gold else "Bitcoin (BTCUSDT)"
        unit = "Giá" if is_gold else "USDT"
        dec = 2 if is_gold else 1
        signal = t['signal']
        entry_p = t['entry_price']
        sl = t['sl']
        tp1 = t['tp1']
        tp2 = t['tp2']

        # 1. KIỂM TRA LỆNH SHORT
        if signal == 'SHORT':
            profit = round(entry_p - curr_p, dec)
            # A. Chạm TP1
            if not t.get('tp1_hit') and curr_p <= tp1:
                t['tp1_hit'] = True
                t['sl'] = entry_p # Dời SL về hoà vốn
                t['status'] = 'TP1_HIT_RISK_FREE'
                save_vip_trades(trades)
                msg = f"""🎯 <b>[VIP CHỐT LỜI 1 (TP1) - ĐÃ ĐẠT R:R 1:1.2]</b> 🎯
━━━━━━━━━━━━━━━━━━
💰 Tài sản: <b>{sym_name}</b>
📈 Lệnh: <b>🔴 SHORT</b> từ <code>${entry_p:,.{dec}f}</code>
🎯 Giá hiện tại: <b>${curr_p:,.{dec}f}</b> (Đã chạm mốc TP1 <code>${tp1:,.{dec}f}</code>)
🔥 <b>LỢI NHUẬN TP1: +{abs(profit):,.{dec}f} {unit}!</b>
━━━━━━━━━━━━━━━━━━
✅ <b>HÀNH ĐỘNG KHUYẾN NGHỊ:</b>
1. Chốt lời <b>50% khối lượng</b> để bảo toàn thành quả!
2. Hệ thống đã tự động dời <b>SL về Hoà Vốn (Entry: ${entry_p:,.{dec}f})</b>.
🛡️ <b>LỆNH HIỆN TẠI ĐÃ FREE-RISK (KHÔNG THỂ THUA ĐƯỢC NỮA)!</b>
🚀 Tiếp tục gồng 50% còn lại về mốc <b>TP2: ${tp2:,.{dec}f}</b>!"""
                send_telegram(msg, reply_markup=get_main_keyboard())
                remaining.append(t)
                continue

            # B. Chạm TP2 (Đóng lệnh toàn bộ)
            if t.get('tp1_hit') and curr_p <= tp2:
                t['tp2_hit'] = True
                t['close_price'] = curr_p
                t['close_time'] = time_str
                t['profit'] = round(entry_p - curr_p, dec)
                t['status'] = 'CLOSED_TP2'
                history.append(t)
                save_vip_history(history)
                msg = f"""🎉 <b>[VIP CHỐT LỜI 2 (TP2) - FULL TAKE PROFIT ĐỈNH CAO]</b> 🎉
━━━━━━━━━━━━━━━━━━
💰 Tài sản: <b>{sym_name}</b>
📈 Lệnh: <b>🔴 SHORT</b> từ <code>${entry_p:,.{dec}f}</code>
🎯 Giá hiện tại: <b>${curr_p:,.{dec}f}</b> (Đã chạm mốc TP2 <code>${tp2:,.{dec}f}</code>)
🔥 <b>TỔNG LỢI NHUẬN TRỌN VẸN: +{abs(t['profit']):,.{dec}f} {unit} (R:R 1:2.5)!</b>
━━━━━━━━━━━━━━━━━━
🏁 <b>KẾT THÚC KÈO VIP HOÀN HẢO:</b>
• Đã bỏ túi toàn bộ lợi nhuận từ con sóng sập!
🟢 Hệ thống đã giải phóng vị thế, sẵn sàng đón kèo VIP tiếp theo khi có nến M5 kích Volume!"""
                send_telegram(msg, reply_markup=get_main_keyboard())
                continue

            # C. Chạm SL (Cắt lỗ hoặc Hoà Vốn)
            if curr_p >= sl:
                t['close_price'] = curr_p
                t['close_time'] = time_str
                if t.get('tp1_hit'):
                    t['status'] = 'CLOSED_BREAKEVEN'
                    t['profit'] = round(abs(entry_p - tp1) * 0.5, dec) # Đã ăn 50% ở TP1
                    msg = f"""🛡️ <b>[VIP ĐÓNG LỆNH HOÀ VỐN - BẢO TOÀN LÃI TP1]</b> 🛡️
━━━━━━━━━━━━━━━━━━
💰 Tài sản: <b>{sym_name}</b>
📈 Lệnh: <b>🔴 SHORT</b> từ <code>${entry_p:,.{dec}f}</code>
⚠️ Giá quay về đá SL Hoà Vốn tại: <b>${curr_p:,.{dec}f}</b>
🎉 <b>KẾT QUẢ CUỐI CÙNG: VẪN CÓ LÃI!</b>
• 50% khối lượng đã bỏ túi tại TP1 (+{abs(entry_p - tp1):,.{dec}f} {unit}).
• 50% khối lượng còn lại thoát giá Hoà Vốn (Risk = $0).
🟢 Hệ thống đã giải phóng slot, chờ đón cơ hội đẹp tiếp theo!"""
                else:
                    t['status'] = 'CLOSED_SL'
                    t['profit'] = -round(curr_p - entry_p, dec)
                    msg = f"""⚠️ <b>[VIP CHẠM CẮT LỖ (SL) - BẢO VỆ TÀI KHOẢN]</b> ⚠️
━━━━━━━━━━━━━━━━━━
💰 Tài sản: <b>{sym_name}</b>
📈 Lệnh: <b>🔴 SHORT</b> từ <code>${entry_p:,.{dec}f}</code>
🛑 Đã chạm SL tại: <b>${curr_p:,.{dec}f}</b> (-{abs(t['profit']):,.{dec}f} {unit})
🛡️ Đúng kỷ luật theo tôn chỉ FX DREAM: Sai là cắt ngay tại chóp râu M5, không gồng lỗ!
🟢 Hệ thống sẵn sàng tìm kiếm điểm vào mới."""
                history.append(t)
                save_vip_history(history)
                send_telegram(msg, reply_markup=get_main_keyboard())
                continue

            remaining.append(t)

        # 2. KIỂM TRA LỆNH LONG
        elif signal == 'LONG':
            profit = round(curr_p - entry_p, dec)
            # A. Chạm TP1
            if not t.get('tp1_hit') and curr_p >= tp1:
                t['tp1_hit'] = True
                t['sl'] = entry_p
                t['status'] = 'TP1_HIT_RISK_FREE'
                save_vip_trades(trades)
                msg = f"""🎯 <b>[VIP CHỐT LỜI 1 (TP1) - ĐÃ ĐẠT R:R 1:1.2]</b> 🎯
━━━━━━━━━━━━━━━━━━
💰 Tài sản: <b>{sym_name}</b>
📈 Lệnh: <b>🟢 LONG</b> từ <code>${entry_p:,.{dec}f}</code>
🎯 Giá hiện tại: <b>${curr_p:,.{dec}f}</b> (Đã chạm mốc TP1 <code>${tp1:,.{dec}f}</code>)
🔥 <b>LỢI NHUẬN TP1: +{abs(profit):,.{dec}f} {unit}!</b>
━━━━━━━━━━━━━━━━━━
✅ <b>HÀNH ĐỘNG KHUYẾN NGHỊ:</b>
1. Chốt lời <b>50% khối lượng</b> để bảo toàn thành quả!
2. Hệ thống đã tự động dời <b>SL về Hoà Vốn (Entry: ${entry_p:,.{dec}f})</b>.
🛡️ <b>LỆNH HIỆN TẠI ĐÃ FREE-RISK (KHÔNG THỂ THUA ĐƯỢC NỮA)!</b>
🚀 Tiếp tục gồng 50% còn lại về mốc <b>TP2: ${tp2:,.{dec}f}</b>!"""
                send_telegram(msg, reply_markup=get_main_keyboard())
                remaining.append(t)
                continue

            # B. Chạm TP2
            if t.get('tp1_hit') and curr_p >= tp2:
                t['tp2_hit'] = True
                t['close_price'] = curr_p
                t['close_time'] = time_str
                t['profit'] = round(curr_p - entry_p, dec)
                t['status'] = 'CLOSED_TP2'
                history.append(t)
                save_vip_history(history)
                msg = f"""🎉 <b>[VIP CHỐT LỜI 2 (TP2) - FULL TAKE PROFIT ĐỈNH CAO]</b> 🎉
━━━━━━━━━━━━━━━━━━
💰 Tài sản: <b>{sym_name}</b>
📈 Lệnh: <b>🟢 LONG</b> từ <code>${entry_p:,.{dec}f}</code>
🎯 Giá hiện tại: <b>${curr_p:,.{dec}f}</b> (Đã chạm mốc TP2 <code>${tp2:,.{dec}f}</code>)
🔥 <b>TỔNG LỢI NHUẬN TRỌN VẸN: +{abs(t['profit']):,.{dec}f} {unit} (R:R 1:2.5)!</b>
━━━━━━━━━━━━━━━━━━
🏁 <b>KẾT THÚC KÈO VIP HOÀN HẢO:</b>
• Đã bỏ túi toàn bộ lợi nhuận từ con sóng tăng!
🟢 Hệ thống đã giải phóng vị thế, sẵn sàng đón kèo VIP tiếp theo khi có nến M5 kích Volume!"""
                send_telegram(msg, reply_markup=get_main_keyboard())
                continue

            # C. Chạm SL
            if curr_p <= sl:
                t['close_price'] = curr_p
                t['close_time'] = time_str
                if t.get('tp1_hit'):
                    t['status'] = 'CLOSED_BREAKEVEN'
                    t['profit'] = round(abs(tp1 - entry_p) * 0.5, dec)
                    msg = f"""🛡️ <b>[VIP ĐÓNG LỆNH HOÀ VỐN - BẢO TOÀN LÃI TP1]</b> 🛡️
━━━━━━━━━━━━━━━━━━
💰 Tài sản: <b>{sym_name}</b>
📈 Lệnh: <b>🟢 LONG</b> từ <code>${entry_p:,.{dec}f}</code>
⚠️ Giá quay về đá SL Hoà Vốn tại: <b>${curr_p:,.{dec}f}</b>
🎉 <b>KẾT QUẢ CUỐI CÙNG: VẪN CÓ LÃI!</b>
• 50% khối lượng đã bỏ túi tại TP1 (+{abs(tp1 - entry_p):,.{dec}f} {unit}).
• 50% khối lượng còn lại thoát giá Hoà Vốn (Risk = $0).
🟢 Hệ thống đã giải phóng slot, chờ đón cơ hội đẹp tiếp theo!"""
                else:
                    t['status'] = 'CLOSED_SL'
                    t['profit'] = -round(entry_p - curr_p, dec)
                    msg = f"""⚠️ <b>[VIP CHẠM CẮT LỖ (SL) - BẢO VỆ TÀI KHOẢN]</b> ⚠️
━━━━━━━━━━━━━━━━━━
💰 Tài sản: <b>{sym_name}</b>
📈 Lệnh: <b>🟢 LONG</b> từ <code>${entry_p:,.{dec}f}</code>
🛑 Đã chạm SL tại: <b>${curr_p:,.{dec}f}</b> (-{abs(t['profit']):,.{dec}f} {unit})
🛡️ Đúng kỷ luật theo tôn chỉ FX DREAM: Sai là cắt ngay tại chóp râu M5, không gồng lỗ!
🟢 Hệ thống sẵn sàng tìm kiếm điểm vào mới."""
                history.append(t)
                save_vip_history(history)
                send_telegram(msg, reply_markup=get_main_keyboard())
                continue

            remaining.append(t)

    save_vip_trades(remaining)

def handle_check_vip_trades():
    try:
        trades = load_vip_trades()
        history = load_vip_history()

        plan_gold = calculate_gold_h4_plan()
        plan_btc = calculate_btc_h4_plan()
        p_gold = plan_gold['current_price']
        p_btc = plan_btc['current_price']

        msg = "🔍 <b>[BÁO CÁO TRẠNG THÁI LỆNH VIP & LỊCH SỬ GIAO DỊCH]</b>\n━━━━━━━━━━━━━━━━━━\n"

        if not trades:
            msg += "🟢 <b>Lệnh VIP Đang Chạy:</b> <i>Không có lệnh nào đang chạy!</i>\n"
            msg += "• Hệ thống đang theo dõi sát sao cản OB H1 và nến M5 để đón cơ hội vào lệnh duy nhất.\n"
        else:
            msg += f"🔥 <b>Lệnh VIP Đang Theo Dõi ({len(trades)} lệnh):</b>\n\n"
            for i, t in enumerate(trades, 1):
                is_gold = (t['asset'] == 'GOLD')
                curr_p = p_gold if is_gold else p_btc
                dec = 2 if is_gold else 1
                unit = "Giá" if is_gold else "$"
                sym = "🥇 VÀNG (XAUUSD)" if is_gold else "👑 BITCOIN"
                sgn = "🔴 SHORT" if t['signal'] == 'SHORT' else "🟢 LONG"
                
                # Tính PnL tạm tính
                if t['signal'] == 'SHORT':
                    diff = t['entry_price'] - curr_p
                else:
                    diff = curr_p - t['entry_price']
                pnl_str = f"+{diff:,.{dec}f} {unit}" if diff >= 0 else f"-{abs(diff):,.{dec}f} {unit}"
                pnl_emoji = "🟢" if diff >= 0 else "🔴"
                
                status_txt = "🛡️ Đã Dời SL Hoà Vốn (Free-Risk)" if t.get('tp1_hit') else "⏳ Đang Chạy (Chờ TP1)"

                msg += f"<b>{i}. {sym} - {sgn}</b>\n"
                msg += f"• Thời gian vào: <code>{t.get('entry_time', '')}</code>\n"
                msg += f"• Giá vào (Entry): <code>${t['entry_price']:,.{dec}f}</code>\n"
                msg += f"• Giá hiện tại: <code>${curr_p:,.{dec}f}</code>\n"
                msg += f"• Lãi/Lỗ tạm tính: {pnl_emoji} <b>{pnl_str}</b>\n"
                msg += f"• Trạng thái: <b>{status_txt}</b>\n"
                msg += f"• Stop Loss: <code>${t['sl']:,.{dec}f}</code>\n"
                msg += f"• Mốc TP1: <code>${t['tp1']:,.{dec}f}</code> {'(✅ Đã Chạm)' if t.get('tp1_hit') else ''}\n"
                msg += f"• Mốc TP2: <code>${t['tp2']:,.{dec}f}</code>\n\n"

        # Tóm tắt lịch sử lệnh đã đóng
        msg += "━━━━━━━━━━━━━━━━━━\n📊 <b>TỔNG KẾT KÈO ĐÃ ĐÓNG:</b>\n"
        if not history:
            msg += "• Chưa có lệnh nào được chốt trong chu kỳ hiện tại.\n"
        else:
            total_closed = len(history)
            wins = [h for h in history if 'TP' in h.get('status', '') or h.get('status') == 'CLOSED_BREAKEVEN' or h.get('profit', 0) > 0]
            win_rate = (len(wins) / total_closed) * 100.0
            msg += f"• Tổng số kèo: <b>{total_closed}</b> | Thắng: <b>{len(wins)}</b> | Thua: <b>{total_closed - len(wins)}</b>\n"
            msg += f"• Tỷ lệ Winrate: <b>{win_rate:.1f}%</b> 🔥\n"
            msg += "• 3 lệnh gần nhất:\n"
            for h in history[-3:]:
                sym = "VÀNG" if h.get('asset') == 'GOLD' else "BTC"
                p_val = h.get('profit', 0)
                sgn_p = f"+{p_val}" if p_val >= 0 else f"{p_val}"
                st = "✅ TP Full" if h.get('status') == 'CLOSED_TP2' else ("🛡️ Hoà Vốn" if h.get('status') == 'CLOSED_BREAKEVEN' else "🛑 Cắt Lỗ")
                msg += f"  - {sym} {h.get('signal')}: {st} ({sgn_p}) [{h.get('close_time', '')}]\n"

        send_telegram(msg, reply_markup=get_main_keyboard())
    except Exception as e:
        send_telegram(f"Lỗi kiểm tra lệnh: {e}", reply_markup=get_main_keyboard())

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
# 1. KẾ HOẠCH BITCOIN: ĐỒNG PHA BIAS TUẦN/NGÀY + ENTRY POC M15 & STOP ĐUA SÓNG
# ==========================================
def find_smc_swings_and_ob(klines_desc, is_gold=False):
    """
    Xác định đỉnh/đáy cấu trúc uy tín (Major Swing Point) và Khối Lệnh Order Block (OB)
    chuẩn SMC & FX Dream KeyVolume trên khung H1 (loại bỏ hoàn toàn nhiễu M15):
    - ĐẶC ĐIỂM CỐT LÕI (FX DREAM): Khối OB là vùng giá CHẠY MẠNH (DISPLACEMENT) CHƯA QUAY LẠI TEST hợp lưu với Swing High/Low:
      1. Khối Bearish OB (Kháng cự H1): Cú xả mạnh (>= 15 giá Vàng, >= 800 giá BTC) từ đỉnh Swing High chưa từng bị quay lại test.
         Vùng OB là vùng chân sóng / hỗ trợ bị bẻ gãy (BOS) trước cú xả (ví dụ 3571 - 3577 của ngày 20/11).
      2. Khối Bullish OB (Hỗ trợ H1): Cú bơm mạnh (>= 15 giá Vàng, >= 800 giá BTC) từ đáy Swing Low chưa từng bị quay lại test.
      3. Biên độ OB hợp lý: dày 2.5 - 6.0 giá Vàng, hoặc 150 - 400 giá BTC.
    """
    chrono = list(reversed(klines_desc))
    n = len(chrono)
    if n < 6:
        return {'time': 'H1', 'high': 0, 'low': 0, 'filter': 'Mặc định'}, {'top': 0, 'bottom': 0, 'mid': 0}, {'time': 'H1', 'high': 0, 'low': 0, 'filter': 'Mặc định'}, {'top': 0, 'bottom': 0, 'mid': 0}
        
    curr_p = float(chrono[-1][4])
    min_disp = 15.0 if is_gold else 800.0

    vols = [float(k[5]) for k in chrono]
    avg_vol = (sum(vols) / len(vols)) if vols else 1.0

    # 1. Tìm Major Bearish OB có cú xả mạnh (Displacement) và CHƯA BỊ TEST LẠI (Unmitigated)
    major_bear_obs = []
    for i in range(len(chrono) - 3, 2, -1):
        c = chrono[i]
        h = float(c[2])
        v = float(c[5])
        o = float(c[1])
        cl = float(c[4])
        if h > curr_p:
            # Kiểm tra đỉnh Swing High hoặc Cây Nến Xung Lực KeyVolume đỏ (như hình mẫu nến 23:00)
            is_peak = all(h >= float(chrono[j][2]) for j in range(max(0, i - 2), min(n, i + 3)))
            is_key_vol_bar = (v >= avg_vol * 1.2 and o > cl)
            if is_peak or is_key_vol_bar:
                future_low = min(float(chrono[j][3]) for j in range(i + 1, min(n, i + 10)))
                drop = h - future_low
                if drop >= min_disp:
                    # Kiểm tra chưa bị nến nào sau đó đóng cửa vượt đỉnh
                    if not any(float(chrono[k][4]) > h for k in range(i + 1, n)):
                        t = datetime.datetime.fromtimestamp(int(c[0])/1000, tz=TZ_VN).strftime('%H:%M %d/%m')
                        if is_key_vol_bar and not is_peak:
                            # Cây nến Key Volume như hình vẽ chart: Lấy râu đỉnh và thân nến
                            ob_top = round(h, 2 if is_gold else 1)
                            ob_bot = round(min(o, cl), 2 if is_gold else 1)
                            filter_name = 'H1 KeyVolume OB'
                        else:
                            # Vùng chân sóng / hỗ trợ bị bẻ gãy (BOS) trước cú xả
                            prev_bars = chrono[max(0, i - 6): i]
                            if prev_bars:
                                base_support = min(float(b[3]) for b in prev_bars)
                                base_close = min(float(b[4]) for b in prev_bars)
                                ob_bot = round(max(base_support, base_close - 3.0), 2 if is_gold else 1)
                                ob_top = round(ob_bot + (6.0 if is_gold else 400.0), 2 if is_gold else 1)
                            else:
                                ob_top = round(h, 2 if is_gold else 1)
                                ob_bot = round(h - (6.0 if is_gold else 400.0), 2 if is_gold else 1)
                            filter_name = 'H1 Major Unmitigated OB'
                        
                        # Kiểm tra xem từ sau cú xả (i+2 trở đi) giá có chạm lại vùng này chưa
                        retested = any(float(chrono[m][2]) >= ob_bot for m in range(i + 2, n))
                        if not retested:
                            major_bear_obs.append({
                                'time': t, 'high': h, 'ob_bot': ob_bot, 'ob_top': ob_top,
                                'mid': round((ob_top + ob_bot) / 2.0, 2 if is_gold else 1),
                                'filter': filter_name
                            })

    # 2. Tìm Major Bullish OB có cú bơm mạnh (Displacement) và CHƯA BỊ TEST LẠI (Unmitigated)
    major_bull_obs = []
    for i in range(len(chrono) - 3, 2, -1):
        c = chrono[i]
        l = float(c[3])
        v = float(c[5])
        o = float(c[1])
        cl = float(c[4])
        if l < curr_p:
            is_trough = all(l <= float(chrono[j][3]) for j in range(max(0, i - 2), min(n, i + 3)))
            is_key_vol_bar = (v >= avg_vol * 1.2 and cl > o)
            if is_trough or is_key_vol_bar:
                future_high = max(float(chrono[j][2]) for j in range(i + 1, min(n, i + 10)))
                pump = future_high - l
                if pump >= min_disp:
                    if not any(float(chrono[k][4]) < l for k in range(i + 1, n)):
                        t = datetime.datetime.fromtimestamp(int(c[0])/1000, tz=TZ_VN).strftime('%H:%M %d/%m')
                        if is_key_vol_bar and not is_trough:
                            ob_bot = round(l, 2 if is_gold else 1)
                            ob_top = round(max(o, cl), 2 if is_gold else 1)
                            filter_name = 'H1 KeyVolume OB'
                        else:
                            ob_bot = round(l, 2 if is_gold else 1)
                            ob_top = round(l + (6.0 if is_gold else 400.0), 2 if is_gold else 1)
                            filter_name = 'H1 Major Unmitigated OB'
                        retested = any(float(chrono[m][3]) <= ob_top for m in range(i + 2, n))
                        if not retested:
                            major_bull_obs.append({
                                'time': t, 'low': l, 'ob_bot': ob_bot, 'ob_top': ob_top,
                                'mid': round((ob_top + ob_bot) / 2.0, 2 if is_gold else 1),
                                'filter': filter_name
                            })

    # Nếu tìm được Major OB theo Displacement thì ưu tiên lấy Major OB gần nhất trên/dưới giá
    if major_bear_obs:
        valid_sh_data = major_bear_obs[0]
        valid_sh = {'time': valid_sh_data['time'], 'high': valid_sh_data['high'], 'filter': valid_sh_data['filter']}
        bearish_ob = {'top': valid_sh_data['ob_top'], 'bottom': valid_sh_data['ob_bot'], 'mid': valid_sh_data['mid'], 'time': valid_sh_data['time'], 'filter': valid_sh_data['filter']}
    else:
        # Fallback
        valid_sh = {'time': 'H1', 'high': round(curr_p + (20.0 if is_gold else 1000.0), 2 if is_gold else 1), 'filter': 'Mặc định'}
        bearish_ob = {'top': valid_sh['high'], 'bottom': round(valid_sh['high'] - (6.0 if is_gold else 400.0), 2 if is_gold else 1), 'mid': round(valid_sh['high'] - (3.0 if is_gold else 200.0), 2 if is_gold else 1), 'time': 'H1', 'filter': 'Mặc định'}

    if major_bull_obs:
        valid_sl_data = major_bull_obs[0]
        valid_sl = {'time': valid_sl_data['time'], 'low': valid_sl_data['low'], 'filter': valid_sl_data['filter']}
        bullish_ob = {'top': valid_sl_data['ob_top'], 'bottom': valid_sl_data['ob_bot'], 'mid': valid_sl_data['mid'], 'time': valid_sl_data['time'], 'filter': valid_sl_data['filter']}
    else:
        valid_sl = {'time': 'H1', 'low': round(curr_p - (20.0 if is_gold else 1000.0), 2 if is_gold else 1), 'filter': 'Mặc định'}
        bullish_ob = {'top': round(valid_sl['low'] + (6.0 if is_gold else 400.0), 2 if is_gold else 1), 'bottom': valid_sl['low'], 'mid': round(valid_sl['low'] + (3.0 if is_gold else 200.0), 2 if is_gold else 1), 'time': 'H1', 'filter': 'Mặc định'}

    return valid_sh, bearish_ob, valid_sl, bullish_ob

def analyze_m5_entry(m5_klines_desc):
    """
    Phân tích khung M5 (Khung vào lệnh Entry theo chuẩn FX Dream KeyVolume):
    - TÔN CHỈ BẤT DI BẤT DỊCH: Tuyệt đối KHÔNG chạm là vào, mà PHẢI có sự đồng thuận xác nhận của NẾN và VOLUME!
    1. Xác nhận NẾN: Nến M5 test cản phải rút râu từ chối (Rejection Wick >= 35% chiều dài nến) hoặc nến đảo chiều.
    2. Xác nhận VOLUME: Cây nến từ chối đó phải KÍCH VOLUME (Volume >= 1.25x Volume trung bình 15 nến).
    -> Chỉ khi CẢ 2 yếu tố (Nến + Kích Vol) cùng xuất hiện mới DUYỆT TÍN HIỆU VÀO LỆNH (CONFIRMED ENTRY)!
    """
    chrono = list(reversed(m5_klines_desc))
    recent = chrono[-15:]
    curr_p = float(recent[-1][4])
    
    vols = [float(c[5]) for c in recent]
    avg_vol = (sum(vols) / len(vols)) if vols else 1.0
    
    confirmed_bear_rejection = None
    confirmed_bull_rejection = None
    
    # Quét các nến M5 gần nhất xem có nến nào Kích Vol + Rút Râu không
    for c in reversed(recent[-8:]):
        o, h, l, cl, v = float(c[1]), float(c[2]), float(c[3]), float(c[4]), float(c[5])
        rng = h - l
        if rng <= 0:
            continue
        upper_wick = h - max(o, cl)
        lower_wick = min(o, cl) - l
        is_vol_spike = (v >= avg_vol * 1.25)
        
        # Bearish confirmation: Râu trên dài + Kích Vol + Nến đóng cửa dội xuống
        if (upper_wick / rng >= 0.35) and is_vol_spike and not confirmed_bear_rejection:
            t = datetime.datetime.fromtimestamp(int(c[0])/1000, tz=TZ_VN).strftime('%H:%M')
            confirmed_bear_rejection = {
                'time': t, 'high': h, 'close': cl, 'wick_pct': round((upper_wick / rng)*100, 1),
                'vol_ratio': round(v / avg_vol, 2)
            }
            
        # Bullish confirmation: Râu dưới dài + Kích Vol + Nến rút chân đi lên
        if (lower_wick / rng >= 0.35) and is_vol_spike and not confirmed_bull_rejection:
            t = datetime.datetime.fromtimestamp(int(c[0])/1000, tz=TZ_VN).strftime('%H:%M')
            confirmed_bull_rejection = {
                'time': t, 'low': l, 'close': cl, 'wick_pct': round((lower_wick / rng)*100, 1),
                'vol_ratio': round(v / avg_vol, 2)
            }

    m5_high = max(float(c[2]) for c in recent)
    m5_low = min(float(c[3]) for c in recent)
    
    return {
        'curr_p': curr_p,
        'm5_high': m5_high,
        'm5_low': m5_low,
        'avg_vol': avg_vol,
        'confirmed_bear_rejection': confirmed_bear_rejection,
        'confirmed_bull_rejection': confirmed_bull_rejection,
        'is_confirmed_entry_bear': confirmed_bear_rejection is not None,
        'is_confirmed_entry_bull': confirmed_bull_rejection is not None
    }

def analyze_m15_structure(m15_klines_desc, delta=0.0, is_gold=False):
    """
    Phân tích Cấu Trúc Khung M15 (Structure Timeframe) theo chuẩn SMC & FX DREAM:
    - NGUYÊN TẮC VÀNG CHỐNG CẢN TÀU (QUYẾT ĐỊNH WINRATE):
      1. Kèo SHORT tại Bearish OB H1: Giá tiếp cận cản H1 là một con sóng tăng trên M15.
         -> Bắt buộc M15 phải PHÁ VỠ CẤU TRÚC (BOS / CHoCH Giảm): Giá phải sập thủng Đáy Swing Low gần nhất của M15 (đáy hỗ trợ tạo nên đỉnh cao nhất).
         -> Chỉ khi M15 đã bẻ gãy cấu trúc tăng này thì mới được phép tìm điểm vào lệnh M5! Nếu chưa thủng -> CẤM BÁN (CẢN TÀU)!
      2. Kèo LONG tại Bullish OB H1: Giá tiếp cận cản H1 là một con sóng giảm trên M15.
         -> Bắt buộc M15 phải PHÁ VỠ CẤU TRÚC (BOS / CHoCH Tăng): Giá phải đục thủng Đỉnh Swing High gần nhất của M15.
         -> Chỉ khi M15 đã bẻ gãy cấu trúc giảm này thì mới được phép tìm điểm vào lệnh M5! Nếu chưa vượt -> CẤM MUA (BẮT DAO RƠI / CẢN TÀU)!
    """
    if not m15_klines_desc or len(m15_klines_desc) < 6:
        return {
            'has_bear_bos': False,
            'has_bull_bos': False,
            'choch_bear_level': 0.0,
            'choch_bull_level': 0.0,
            'curr_p': 0.0
        }
        
    chrono = list(reversed(m15_klines_desc))
    curr_p = float(chrono[-1][4]) + delta
    highs = [float(c[2]) + delta for c in chrono]
    lows = [float(c[3]) + delta for c in chrono]
    closes = [float(c[4]) + delta for c in chrono]
    n = len(chrono)
    
    # 1. Tìm đỉnh gần nhất trong 15 nến M15 và đáy Swing Low tạo nên đỉnh đó (M15 Bearish CHoCH level)
    recent_len = min(15, n)
    recent_highs = highs[-recent_len:]
    max_h_idx = (n - recent_len) + int(np.argmax(recent_highs))
    
    # Đáy tạo nên đỉnh này nằm trong các nến trước max_h_idx
    prior_lows = lows[max(0, max_h_idx - 6): max_h_idx]
    if prior_lows:
        choch_bear_level = round(min(prior_lows), 2 if is_gold else 1)
    else:
        choch_bear_level = round(lows[max(0, max_h_idx - 1)], 2 if is_gold else 1)
        
    # Kiểm tra xem nến từ sau đỉnh có nến nào đóng cửa hoặc giá hiện tại đâm thủng đáy này chưa
    has_bear_bos = (curr_p < choch_bear_level) or any(c < choch_bear_level for c in closes[max_h_idx:])
    
    # 2. Tìm đáy gần nhất trong 15 nến M15 và đỉnh Swing High tạo nên đáy đó (M15 Bullish CHoCH level)
    recent_lows = lows[-recent_len:]
    min_l_idx = (n - recent_len) + int(np.argmin(recent_lows))
    
    # Đỉnh tạo nên đáy này nằm trong các nến trước min_l_idx
    prior_highs = highs[max(0, min_l_idx - 6): min_l_idx]
    if prior_highs:
        choch_bull_level = round(max(prior_highs), 2 if is_gold else 1)
    else:
        choch_bull_level = round(highs[max(0, min_l_idx - 1)], 2 if is_gold else 1)
        
    has_bull_bos = (curr_p > choch_bull_level) or any(c > choch_bull_level for c in closes[min_l_idx:])
    
    return {
        'has_bear_bos': has_bear_bos,
        'has_bull_bos': has_bull_bos,
        'choch_bear_level': choch_bear_level,
        'choch_bull_level': choch_bull_level,
        'curr_p': curr_p
    }

def calculate_keyvolume_nodes(klines, n_bins=20):
    """
    Tính Volume Profile & Xác định vùng High Volume Node (HVN) và Low Volume Node (LVN)
    theo Lý thuyết về Giá của FX DREAM TRADING.
    """
    prices = []
    weights = []
    for k in klines:
        h = float(k[2])
        l = float(k[3])
        v = float(k[5])
        for p in np.linspace(l, h, 5):
            prices.append(p)
            weights.append(v / 5.0)
    hist, bin_edges = np.histogram(prices, bins=n_bins, weights=weights)
    max_idx = np.argmax(hist)
    poc = round((bin_edges[max_idx] + bin_edges[max_idx + 1]) / 2, 2)
    threshold = hist[max_idx] * 0.5
    hvn_bins = [i for i, vol in enumerate(hist) if vol >= threshold]
    hvn_lower = round(bin_edges[min(hvn_bins)], 2)
    hvn_upper = round(bin_edges[max(hvn_bins) + 1], 2)
    return poc, hvn_lower, hvn_upper

def calculate_btc_h4_plan():
    now = time.time()
    # Cache giữ nguyên trong 4 phút (đồng bộ chu kỳ nến M5)
    if PLAN_CACHE['BTC']['data'] and (now - PLAN_CACHE['BTC']['candle_time'] < 240):
        return PLAN_CACHE['BTC']['data']
        
    try:
        def get_kline(interval='15', limit=30):
            url = f'https://api.bybit.com/v5/market/kline?category=linear&symbol=BTCUSDT&interval={interval}&limit={limit}'
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=8) as r:
                return json.loads(r.read().decode())['result']['list']

        w_klines = get_kline('W', 25)
        d_klines = get_kline('D', 25)
        h1_klines = get_kline('60', 60)
        m15_klines = get_kline('15', 30)
        m5_klines = get_kline('5', 30)

        current_price = float(m5_klines[0][4])
        m5_info = analyze_m5_entry(m5_klines)
        
        # 1. Bias Đa Khung (Tuần W1 & Ngày D1)
        w_closes = [float(k[4]) for k in reversed(w_klines)]
        w_ema20 = sum(w_closes[-20:]) / 20.0
        w1_bear = current_price < w_ema20
        w1_bias = "🔴 GIẢM (BEARISH)" if w1_bear else "🟢 TĂNG (BULLISH)"

        d_closes = [float(k[4]) for k in reversed(d_klines)]
        d_ema20 = sum(d_closes[-20:]) / 20.0
        d1_bear = current_price < d_ema20
        d1_bias = "🔴 GIẢM (BEARISH)" if d1_bear else "🟢 TĂNG (BULLISH)"

        # 2. Cấu Trúc SMC & Order Block (OB H1 Chuẩn - Khung Lớn Không Nhiễu)
        valid_sh, bearish_ob, valid_sl, bullish_ob = find_smc_swings_and_ob(h1_klines, is_gold=False)
        swing_high = round(valid_sh['high'], 1)
        sh_time = valid_sh['time']
        sh_filter = valid_sh['filter']
        swing_low = round(valid_sl['low'], 1)
        sl_time = valid_sl['time']
        sl_filter = valid_sl['filter']

        # 3. Phân tích cấu trúc M15 (Structure Timeframe - Chống Cản Tàu) & Vùng HVN/POC
        m15_struct = analyze_m15_structure(m15_klines, delta=0.0, is_gold=False)
        poc_m15, hvn_lower, hvn_upper = calculate_keyvolume_nodes(m15_klines, n_bins=20)

        # XÁC ĐỊNH HƯỚNG ĐÁNH THEO BIAS VĨ MÔ & TEST CẢN
        # ĐIỀU KIỆN TIÊN QUYẾT: M15 BẮT BUỘC PHẢI PHÁ VỠ CẤU TRÚC (BOS/CHoCH) TRƯỚC!
        is_bear_confirmed = m15_struct['has_bear_bos'] and m5_info['is_confirmed_entry_bear']
        is_bull_confirmed = m15_struct['has_bull_bos'] and m5_info['is_confirmed_entry_bull']

        if is_bull_confirmed and not (w1_bear and d1_bear):
            signal = "LONG"
            setup_desc = f"M15 BOS Tăng + M5 Rút Chân Kích Volume tại Khối Bullish OB ${swing_low:,.1f} ({sl_time})"
            diamond_note = "⭐ ĐẢO CHIỀU UY TÍN (CÂN BẰNG QUÂN LỰC): M15 đã phá cấu trúc + M5 kích Volume xác nhận!"
        elif is_bear_confirmed or (w1_bear and d1_bear):
            signal = "SHORT"
            m5_txt = " + M15 BOS & Kích Vol M5" if is_bear_confirmed else " (Đang Chờ M15 BOS)"
            setup_desc = f"Đồng Pha Giảm Tuần/Ngày - Test Khối Bearish OB H1 ${bearish_ob['mid']:,.1f}{m5_txt}"
            diamond_note = "⭐ ĐỒNG PHA TUẦN + NGÀY (CẢN TO H1): Tuyệt đối không cản tàu, chờ M15 phá vỡ cấu trúc!"
        else:
            signal = "SHORT" if d1_bear else "LONG"
            setup_desc = f"Cấu Trúc KeyVolume H1 tại Khối OB ${bearish_ob['mid']:,.1f}"
            diamond_note = "⚡ Quản lý vốn theo từng mốc cản."

        # Tính thông số chi tiết cho cả 2 VÙNG CANH SELL và VÙNG CANH BUY
        # 1. Kịch bản CANH SELL (tại Kháng Cự H1)
        sell_conf = m5_info['confirmed_bear_rejection']
        sell_entry = round(bearish_ob['bottom'], 1)
        if m15_struct['has_bear_bos'] and sell_conf:
            sell_entry = round(current_price, 1)
            sell_sl = round(sell_conf['high'] + 120.0, 1)
        else:
            sell_sl = round(max(bearish_ob['top'] + 200.0, swing_high + 120.0), 1)
        sell_risk = round(sell_sl - sell_entry, 1)
        if sell_risk < 250.0:
            sell_sl = round(sell_entry + 300.0, 1)
            sell_risk = round(sell_sl - sell_entry, 1)
        sell_tp1 = round(sell_entry - (sell_risk * 1.2), 1)
        sell_tp2 = round(sell_entry - (sell_risk * 2.5), 1)

        # 2. Kịch bản CANH BUY (tại Hỗ Trợ H1)
        buy_conf = m5_info['confirmed_bull_rejection']
        buy_entry = round(bullish_ob['top'], 1)
        if m15_struct['has_bull_bos'] and buy_conf:
            buy_entry = round(current_price, 1)
            buy_sl = round(buy_conf['low'] - 120.0, 1)
        else:
            buy_sl = round(min(bullish_ob['bottom'] - 200.0, swing_low - 120.0), 1)
        buy_risk = round(buy_entry - buy_sl, 1)
        if buy_risk < 250.0:
            buy_sl = round(buy_entry - 300.0, 1)
            buy_risk = round(buy_entry - buy_sl, 1)
        buy_tp1 = round(buy_entry + (buy_risk * 1.2), 1)
        buy_tp2 = round(buy_entry + (buy_risk * 2.5), 1)

        # Hướng ưu tiên theo xu hướng Tuần/Ngày
        priority_dir = "🔴 CANH SELL (Ưu tiên theo xu hướng Giảm W1/D1)" if (w1_bear and d1_bear) else ("🟢 CANH BUY (Ưu tiên theo xu hướng Tăng)" if (not w1_bear and not d1_bear) else "⚡ LINH HOẠT (Đánh theo phản ứng tại 2 Vùng Cản)")

        # Trạng thái hiện tại
        if signal == "SHORT":
            is_confirmed = is_bear_confirmed
            entry_limit = sell_entry
            entry_stop = round(swing_low * 0.998, 1)
            sl = sell_sl
            sl_dist = sell_risk
            tp1 = sell_tp1
            tp2 = sell_tp2
            if not m15_struct['has_bear_bos']:
                confirm_badge = "⏳ CHỜ M15 PHÁ VỠ CẤU TRÚC (TRÁNH CẢN TÀU)"
                action_advice = f"Giá đang trong nhịp tăng tiếp cận Vùng Sell. M15 chưa gãy cấu trúc (chưa thủng đáy ${m15_struct['choch_bear_level']:,.1f}). Đứng ngoài quan sát, tuyệt đối không cản tàu!"
            elif sell_conf:
                confirm_badge = "🔥 ĐÃ PHÁ VỠ CẤU TRÚC M15 (BOS) + KÍCH VOLUME M5"
                action_advice = f"M15 đã gãy cấu trúc tăng + Nến M5 lúc {sell_conf['time']} rút râu {sell_conf['wick_pct']}% kích Volume {sell_conf['vol_ratio']}x! Đủ điều kiện vào lệnh Sell ngay!"
            else:
                confirm_badge = "⏳ ĐÃ GÃY CẤU TRÚC M15 (CHỜ M5 RETEST KÍCH VOL)"
                action_advice = f"M15 đã bẻ gãy cấu trúc tăng (thủng ${m15_struct['choch_bear_level']:,.1f}). Đang chờ nến M5 hồi retest cản rút râu kích Volume để vào lệnh Sell."
        else: # LONG
            is_confirmed = is_bull_confirmed
            entry_limit = buy_entry
            entry_stop = round(swing_high * 1.002, 1)
            sl = buy_sl
            sl_dist = buy_risk
            tp1 = buy_tp1
            tp2 = buy_tp2
            if not m15_struct['has_bull_bos']:
                confirm_badge = "⏳ CHỜ M15 PHÁ VỠ CẤU TRÚC (TRÁNH BẮT DAO RƠI)"
                action_advice = f"Giá đang trong nhịp giảm tiếp cận Vùng Buy. M15 chưa đảo chiều tăng (chưa vượt đỉnh ${m15_struct['choch_bull_level']:,.1f}). Đứng ngoài quan sát, tuyệt đối không bắt dao rơi!"
            elif buy_conf:
                confirm_badge = "🔥 ĐÃ PHÁ VỠ CẤU TRÚC M15 (BOS) + KÍCH VOLUME M5"
                action_advice = f"M15 đã đảo chiều tăng + Nến M5 lúc {buy_conf['time']} rút chân {buy_conf['wick_pct']}% kích Volume {buy_conf['vol_ratio']}x! Đủ điều kiện vào lệnh Buy ngay!"
            else:
                confirm_badge = "⏳ ĐÃ GÃY CẤU TRÚC M15 (CHỜ M5 RETEST KÍCH VOL)"
                action_advice = f"M15 đã bẻ gãy cấu trúc giảm (vượt ${m15_struct['choch_bull_level']:,.1f}). Đang chờ nến M5 hồi retest cản rút chân kích Volume để vào lệnh Buy."

        plan = {
            'signal': signal,
            'current_price': current_price,
            'w1_bias': w1_bias,
            'd1_bias': d1_bias,
            'priority_dir': priority_dir,
            'diamond_note': diamond_note,
            'setup_desc': setup_desc,
            'confirm_badge': confirm_badge,
            'action_advice': action_advice,
            'is_confirmed': is_confirmed,
            'poc': poc_m15,
            'hvn_lower': hvn_lower,
            'hvn_upper': hvn_upper,
            'swing_high': swing_high,
            'sh_time': sh_time,
            'sh_filter': sh_filter,
            'b_ob_top': bearish_ob['top'],
            'b_ob_bot': bearish_ob['bottom'],
            'b_ob_mid': bearish_ob['mid'],
            'swing_low': swing_low,
            'sl_time': sl_time,
            'sl_filter': sl_filter,
            'bull_ob_top': bullish_ob['top'],
            'bull_ob_bot': bullish_ob['bottom'],
            'bull_ob_mid': bullish_ob['mid'],
            'm15_status': "✅ Đã Phá Vỡ Cấu Trúc (BOS)" if (m15_struct['has_bear_bos'] if signal == 'SHORT' else m15_struct['has_bull_bos']) else "⛔ Chưa Phá Vỡ (Đang Chờ BOS)",
            'm15_choch_bear': m15_struct['choch_bear_level'],
            'm15_choch_bull': m15_struct['choch_bull_level'],
            'm15_choch_level': m15_struct['choch_bear_level'] if signal == 'SHORT' else m15_struct['choch_bull_level'],
            'sell_entry': sell_entry,
            'sell_sl': sell_sl,
            'sell_risk': sell_risk,
            'sell_tp1': sell_tp1,
            'sell_tp2': sell_tp2,
            'buy_entry': buy_entry,
            'buy_sl': buy_sl,
            'buy_risk': buy_risk,
            'buy_tp1': buy_tp1,
            'buy_tp2': buy_tp2,
            'entry_limit': entry_limit,
            'entry_stop': entry_stop,
            'sl': sl,
            'sl_dist': sl_dist,
            'sl_pct': round((sl_dist / entry_limit) * 100.0, 2),
            'tp1': tp1,
            'tp2': tp2,
            'advice': action_advice
        }
        PLAN_CACHE['BTC']['data'] = plan
        PLAN_CACHE['BTC']['candle_time'] = now
        return plan
    except Exception as e:
        print(f"Lỗi tính plan BTC: {e}")
        raise e

def handle_btc():
    try:
        plan = calculate_btc_h4_plan()
        text = f"""👑 <b>[KẾ HOẠCH GIAO DỊCH BITCOIN - BTCUSDT]</b> 👑
━━━━━━━━━━━━━━━━━━
💰 <b>Giá BTC hiện tại:</b> <code>${plan['current_price']:,.1f}</code>
📊 <b>Xu hướng chính:</b> Tuần: {plan['w1_bias']} | Ngày: {plan['d1_bias']}
🎯 <b>Định hướng:</b> <b>{plan['priority_dir']}</b>

━━━━━━━━━━━━━━━━━━
🔴 <b>1. VÙNG CANH SELL (Kháng Cự H1):</b>
• <b>Vùng giá:</b> <code>[${plan['b_ob_bot']:,.1f} - ${plan['b_ob_top']:,.1f}]</code>
• <b>Kích hoạt khi:</b> M15 thủng đáy <code>${plan['m15_choch_bear']:,.1f}</code> + M5 rút râu kích Vol
👉 <b>Entry Sell:</b> <code>${plan['sell_entry']:,.1f}</code>
🛡️ <b>Stop Loss:</b> <code>${plan['sell_sl']:,.1f}</code> (~{plan['sell_risk']:,.1f} USD)
🎯 <b>TP1 (Ăn {plan['sell_risk']*1.2:,.1f} USD | Chốt 50% & Dời Hoà):</b> <code>${plan['sell_tp1']:,.1f}</code>
🎯 <b>TP2 (Ăn {plan['sell_risk']*2.5:,.1f} USD):</b> <code>${plan['sell_tp2']:,.1f}</code>

━━━━━━━━━━━━━━━━━━
🟢 <b>2. VÙNG CANH BUY (Hỗ Trợ H1):</b>
• <b>Vùng giá:</b> <code>[${plan['bull_ob_bot']:,.1f} - ${plan['bull_ob_top']:,.1f}]</code>
• <b>Kích hoạt khi:</b> M15 vượt đỉnh <code>${plan['m15_choch_bull']:,.1f}</code> + M5 rút chân kích Vol
👉 <b>Entry Buy:</b> <code>${plan['buy_entry']:,.1f}</code>
🛡️ <b>Stop Loss:</b> <code>${plan['buy_sl']:,.1f}</code> (~{plan['buy_risk']:,.1f} USD)
🎯 <b>TP1 (Ăn {plan['buy_risk']*1.2:,.1f} USD | Chốt 50% & Dời Hoà):</b> <code>${plan['buy_tp1']:,.1f}</code>
🎯 <b>TP2 (Ăn {plan['buy_risk']*2.5:,.1f} USD):</b> <code>${plan['buy_tp2']:,.1f}</code>

━━━━━━━━━━━━━━━━━━
⚡ <b>TRẠNG THÁI HIỆN TẠI & HÀNH ĐỘNG:</b>
• <b>Tín hiệu vào lệnh:</b> <b>{plan['confirm_badge']}</b>
• <b>Cấu trúc M15:</b> {plan['m15_status']}
• <b>Khuyến nghị:</b> {plan['action_advice']}
━━━━━━━━━━━━━━━━━━
<i>🛡️ Quản lý vốn: Rủi ro tối đa 2% ($20.0 trên tài khoản $1,000).</i>"""
        send_telegram(text, reply_markup=get_main_keyboard())
    except Exception as e:
        send_telegram(f"Lỗi BTC POC: {e}", reply_markup=get_main_keyboard())
        send_telegram(text, reply_markup=get_main_keyboard())
    except Exception as e:
        send_telegram(f"Lỗi BTC POC: {e}", reply_markup=get_main_keyboard())

# ==========================================
# 2. KẾ HOẠCH VÀNG (SMC) - NGUỒN OANDA:XAUUSD (CHUẨN MT5)
# ==========================================
def calculate_gold_h4_plan():
    now = time.time()
    # Cache giữ nguyên trong 4 phút (đồng bộ chu kỳ nến M5)
    if PLAN_CACHE['GOLD']['data'] and (now - PLAN_CACHE['GOLD']['candle_time'] < 240):
        return PLAN_CACHE['GOLD']['data']
        
    confirm_badge = "⏳ ĐANG CHỜ XÁC NHẬN (CHƯA VÀO LỆNH)"
    is_bear_confirmed = False
    is_bull_confirmed = False
    m5_entry_high = 3547.0
    m5_entry_low = 3508.0

    try:
        # Lấy dữ liệu đa khung thời gian từ TradingView cho OANDA:XAUUSD
        url = 'https://scanner.tradingview.com/cfd/scan'
        cols = [
            'close', 'open', 'high', 'low', 'bid', 'ask', 'EMA20', 'EMA50', 'Recommend.All',
            'close|1W', 'EMA20|1W', 'EMA50|1W', 'Recommend.All|1W',
            'open|5', 'high|5', 'low|5', 'close|5', 'EMA20|5',
            'open[1]|5', 'high[1]|5', 'low[1]|5', 'close[1]|5',
            'open|15', 'high|15', 'low|15', 'close|15', 'EMA20|15',
            'open[1]|15', 'high[1]|15', 'low[1]|15', 'close[1]|15',
            'open|60', 'high|60', 'low|60', 'close|60', 'EMA20|60',
            'open|240', 'high|240', 'low|240', 'close|240', 'EMA20|240',
            'ATR|15', 'RSI|15', 'Recommend.All|15'
        ]
        payload = json.dumps({'symbols': {'tickers': ['OANDA:XAUUSD']}, 'columns': cols}).encode()
        req = urllib.request.Request(url, data=payload, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.loads(r.read().decode())['data'][0]['d']

        data = dict(zip(cols, d))
        current_gold = round(data['close'], 2)
        bid = round(data.get('bid') or (current_gold - 0.35), 2)
        ask = round(data.get('ask') or (current_gold + 0.35), 2)
        data_source = "TradingView (OANDA:XAUUSD - Chuẩn MT5)"
        
        # 1. BIAS ĐA KHUNG (TUẦN W1 & NGÀY D1)
        w1_bear = data['close|1W'] < data['EMA20|1W']
        d1_bear = data['close'] < data['EMA20']
        w1_bias = "🔴 GIẢM (BEARISH)" if w1_bear else "🟢 TĂNG (BULLISH)"
        d1_bias = "🔴 GIẢM (BEARISH)" if d1_bear else "🟢 TĂNG (BULLISH)"
        
        # 2. Lấy dữ liệu H1 klines từ Bybit XAUUSDT và tính Valid Swing High / Low & Order Block (OB) SMC
        url_gold_kline = 'https://api.bybit.com/v5/market/kline?category=linear&symbol=XAUUSDT&interval=60&limit=60'
        req_g = urllib.request.Request(url_gold_kline, headers=HEADERS)
        with urllib.request.urlopen(req_g, timeout=8) as r:
            gold_h1_klines = json.loads(r.read().decode())['result']['list']

        sh_raw, b_ob_raw, sl_raw, bull_ob_raw = find_smc_swings_and_ob(gold_h1_klines, is_gold=True)
        delta = current_gold - float(gold_h1_klines[0][4])
        
        major_res = round(sh_raw['high'] + delta, 2)
        b_ob_top = round(b_ob_raw['top'] + delta, 2)
        b_ob_bot = round(b_ob_raw['bottom'] + delta, 2)
        b_ob_mid = round(b_ob_raw['mid'] + delta, 2)
        sh_time = sh_raw['time']
        sh_filter = sh_raw.get('filter', 'Duyệt Qua InsideBar')

        major_sup = round(sl_raw['low'] + delta, 2)
        bull_ob_top = round(bull_ob_raw['top'] + delta, 2)
        bull_ob_bot = round(bull_ob_raw['bottom'] + delta, 2)
        bull_ob_mid = round(bull_ob_raw['mid'] + delta, 2)
        sl_time = sl_raw['time']
        sl_filter = sl_raw.get('filter', 'Duyệt Qua InsideBar')

        m5_high = round(data['high|5'], 2)
        m15_high = round(data['high|15'], 2)
        m15_low = round(data['low|15'], 2)
        m15_ema20 = round(data['EMA20|15'], 2)
        h4_ema20 = round(data['EMA20|240'], 2)
        
        # 3. Phân tích cấu trúc M15 (Structure Timeframe - Chống Cản Tàu) & Vùng HVN/POC
        try:
            url_gold_m15 = 'https://api.bybit.com/v5/market/kline?category=linear&symbol=XAUUSDT&interval=15&limit=30'
            req_gm15 = urllib.request.Request(url_gold_m15, headers=HEADERS)
            with urllib.request.urlopen(req_gm15, timeout=8) as r:
                gold_m15_klines = json.loads(r.read().decode())['result']['list']
            poc_raw, hvn_l_raw, hvn_u_raw = calculate_keyvolume_nodes(gold_m15_klines)
            poc_gold_m15 = round(poc_raw + delta, 2)
            hvn_lower = round(hvn_l_raw + delta, 2)
            hvn_upper = round(hvn_u_raw + delta, 2)
            m15_struct = analyze_m15_structure(gold_m15_klines, delta=delta, is_gold=True)
        except Exception:
            poc_gold_m15 = round((m15_high + m15_low + m15_ema20) / 3.0, 2)
            hvn_lower = round(m15_low, 2)
            hvn_upper = round(m15_high, 2)
            gold_m15_klines = []
            m15_struct = {'has_bear_bos': False, 'has_bull_bos': False, 'choch_bear_level': m15_low, 'choch_bull_level': m15_high}
        
        # 4. Phân tích khung M5 (Khung vào lệnh Entry theo chuẩn SMC)
        try:
            url_gold_m5 = 'https://api.bybit.com/v5/market/kline?category=linear&symbol=XAUUSDT&interval=5&limit=30'
            req_gm5 = urllib.request.Request(url_gold_m5, headers=HEADERS)
            with urllib.request.urlopen(req_gm5, timeout=8) as r:
                gold_m5_klines = json.loads(r.read().decode())['result']['list']
            m5_info = analyze_m5_entry(gold_m5_klines)
            m5_entry_high = round(m5_info['m5_high'] + delta, 2)
            m5_entry_low = round(m5_info['m5_low'] + delta, 2)
        except Exception:
            m5_info = {
                'has_multi_tops': False,
                'has_multi_bottoms': False,
                'upper_wicks_count': 0,
                'lower_wicks_count': 0,
                'is_confirmed_entry_bear': False,
                'is_confirmed_entry_bull': False,
                'confirmed_bear_rejection': None,
                'confirmed_bull_rejection': None,
                'm5_high': m5_high,
                'm5_low': m15_low
            }
            m5_entry_high = m5_high
            m5_entry_low = m15_low

        # XÁC ĐỊNH HƯỚNG ĐÁNH THEO BIAS VĨ MÔ & TEST CẢN
        # ĐIỀU KIỆN TIÊN QUYẾT: M15 BẮT BUỘC PHẢI PHÁ VỠ CẤU TRÚC (BOS/CHoCH) TRƯỚC!
        is_bear_confirmed = m15_struct['has_bear_bos'] and m5_info['is_confirmed_entry_bear']
        is_bull_confirmed = m15_struct['has_bull_bos'] and m5_info['is_confirmed_entry_bull']
        
        if is_bull_confirmed and not (w1_bear and d1_bear):
            signal = "LONG"
            setup_desc = f"M15 BOS Tăng + M5 Rút Chân Kích Volume tại Khối Bullish OB ${major_sup:,.2f} ({sl_time})"
            diamond_note = "⭐ ĐẢO CHIỀU UY TÍN (CÂN BẰNG QUÂN LỰC): M15 đã phá cấu trúc + M5 kích Volume xác nhận!"
        elif is_bear_confirmed or (w1_bear and d1_bear):
            signal = "SHORT"
            m5_txt = " + M15 BOS & Kích Vol M5" if is_bear_confirmed else " (Đang Chờ M15 BOS)"
            setup_desc = f"Đồng Pha Giảm Tuần/Ngày - Test Khối Bearish OB H1 ${b_ob_mid:,.2f}{m5_txt}"
            diamond_note = "⭐ ĐỒNG PHA TUẦN + NGÀY (CẢN TO H1): Tuyệt đối không cản tàu, chờ M15 phá vỡ cấu trúc!"
        else:
            signal = "SHORT" if d1_bear else "LONG"
            setup_desc = f"Cấu Trúc KeyVolume H1 tại Khối OB ${b_ob_mid:,.2f}"
            diamond_note = "⚡ Quản lý vốn chặt chẽ theo cản."
        
        # Tính thông số chi tiết cho cả 2 VÙNG CANH SELL và VÙNG CANH BUY
        # 1. Kịch bản CANH SELL (tại Kháng Cự H1)
        sell_conf = m5_info['confirmed_bear_rejection']
        sell_entry = round(b_ob_bot, 2)
        if m15_struct['has_bear_bos'] and sell_conf:
            sell_entry = round(current_gold, 2)
            sell_sl = round(max(sell_conf['high'] + 2.5, major_res + 2.0), 2)
        else:
            sell_sl = round(max(b_ob_top + 6.0, major_res + 2.5), 2)
        sell_risk = round(sell_sl - sell_entry, 2)
        if sell_risk < 6.0:
            sell_sl = round(sell_entry + 8.0, 2)
            sell_risk = round(sell_sl - sell_entry, 2)
        elif sell_risk > 35.0:
            sell_sl = round(sell_entry + 25.0, 2)
            sell_risk = round(sell_sl - sell_entry, 2)
        sell_tp1 = round(sell_entry - (sell_risk * 1.2), 2)
        sell_tp2 = round(sell_entry - (sell_risk * 2.5), 2)

        # 2. Kịch bản CANH BUY (tại Hỗ Trợ H1)
        buy_conf = m5_info['confirmed_bull_rejection']
        buy_entry = round(bull_ob_top, 2)
        if m15_struct['has_bull_bos'] and buy_conf:
            buy_entry = round(current_gold, 2)
            buy_sl = round(min(buy_conf['low'] - 2.5, major_sup - 2.0), 2)
        else:
            buy_sl = round(min(bull_ob_bot - 6.0, major_sup - 2.5), 2)
        buy_risk = round(buy_entry - buy_sl, 2)
        if buy_risk < 6.0:
            buy_sl = round(buy_entry - 8.0, 2)
            buy_risk = round(buy_entry - buy_sl, 2)
        elif buy_risk > 35.0:
            buy_sl = round(buy_entry - 25.0, 2)
            buy_risk = round(buy_entry - buy_sl, 2)
        buy_tp1 = round(buy_entry + (buy_risk * 1.2), 2)
        buy_tp2 = round(buy_entry + (buy_risk * 2.5), 2)

        # Hướng ưu tiên theo xu hướng Tuần/Ngày
        priority_dir = "🔴 CANH SELL (Ưu tiên theo xu hướng Giảm W1/D1)" if (w1_bear and d1_bear) else ("🟢 CANH BUY (Ưu tiên theo xu hướng Tăng)" if (not w1_bear and not d1_bear) else "⚡ LINH HOẠT (Đánh theo phản ứng tại 2 Vùng Cản)")

        # Trạng thái hiện tại
        if signal == "SHORT":
            is_confirmed = is_bear_confirmed
            entry_limit = sell_entry
            entry_stop = round(major_sup - 1.2, 2)
            sl = sell_sl
            sl_dist = sell_risk
            tp1 = sell_tp1
            tp2 = sell_tp2
            if not m15_struct['has_bear_bos']:
                confirm_badge = "⏳ CHỜ M15 PHÁ VỠ CẤU TRÚC (TRÁNH CẢN TÀU)"
                action_advice = f"Giá Vàng đang trong nhịp tăng tiếp cận Vùng Sell. M15 chưa gãy cấu trúc (chưa thủng đáy ${m15_struct['choch_bear_level']:,.2f}). Đứng ngoài quan sát, tuyệt đối không cản tàu!"
            elif sell_conf:
                confirm_badge = "🔥 ĐÃ PHÁ VỠ CẤU TRÚC M15 (BOS) + KÍCH VOLUME M5"
                action_advice = f"M15 đã gãy cấu trúc tăng + Nến M5 lúc {sell_conf['time']} rút râu {sell_conf['wick_pct']}% kích Volume {sell_conf['vol_ratio']}x! Đủ điều kiện vào lệnh Sell ngay!"
            else:
                confirm_badge = "⏳ ĐÃ GÃY CẤU TRÚC M15 (CHỜ M5 RETEST KÍCH VOL)"
                action_advice = f"M15 đã bẻ gãy cấu trúc tăng (thủng ${m15_struct['choch_bear_level']:,.2f}). Đang chờ nến M5 hồi retest cản rút râu kích Volume để vào lệnh Sell."
        else: # LONG
            is_confirmed = is_bull_confirmed
            entry_limit = buy_entry
            entry_stop = round(major_res + 1.2, 2)
            sl = buy_sl
            sl_dist = buy_risk
            tp1 = buy_tp1
            tp2 = buy_tp2
            if not m15_struct['has_bull_bos']:
                confirm_badge = "⏳ CHỜ M15 PHÁ VỠ CẤU TRÚC (TRÁNH BẮT DAO RƠI)"
                action_advice = f"Giá Vàng đang trong nhịp giảm tiếp cận Vùng Buy. M15 chưa đảo chiều tăng (chưa vượt đỉnh ${m15_struct['choch_bull_level']:,.2f}). Đứng ngoài quan sát, tuyệt đối không bắt dao rơi!"
            elif buy_conf:
                confirm_badge = "🔥 ĐÃ PHÁ VỠ CẤU TRÚC M15 (BOS) + KÍCH VOLUME M5"
                action_advice = f"M15 đã đảo chiều tăng + Nến M5 lúc {buy_conf['time']} rút chân {buy_conf['wick_pct']}% kích Volume {buy_conf['vol_ratio']}x! Đủ điều kiện vào lệnh Buy ngay!"
            else:
                confirm_badge = "⏳ ĐÃ GÃY CẤU TRÚC M15 (CHỜ M5 RETEST KÍCH VOL)"
                action_advice = f"M15 đã bẻ gãy cấu trúc giảm (vượt ${m15_struct['choch_bull_level']:,.2f}). Đang chờ nến M5 hồi retest cản rút chân kích Volume để vào lệnh Buy."

        plan = {
            'signal': signal,
            'current_price': current_gold,
            'bid': bid,
            'ask': ask,
            'data_source': data_source,
            'w1_bias': w1_bias,
            'd1_bias': d1_bias,
            'priority_dir': priority_dir,
            'diamond_note': diamond_note,
            'setup_desc': setup_desc,
            'confirm_badge': confirm_badge,
            'action_advice': action_advice,
            'is_confirmed': is_confirmed,
            'poc_m15': poc_gold_m15,
            'hvn_lower': hvn_lower,
            'hvn_upper': hvn_upper,
            'swing_high': major_res,
            'sh_time': sh_time,
            'sh_filter': sh_filter,
            'b_ob_top': b_ob_top,
            'b_ob_bot': b_ob_bot,
            'b_ob_mid': b_ob_mid,
            'swing_low': major_sup,
            'sl_time': sl_time,
            'sl_filter': sl_filter,
            'bull_ob_top': bull_ob_top,
            'bull_ob_bot': bull_ob_bot,
            'bull_ob_mid': bull_ob_mid,
            'm15_status': "✅ Đã Phá Vỡ Cấu Trúc (BOS)" if (m15_struct['has_bear_bos'] if signal == 'SHORT' else m15_struct['has_bull_bos']) else "⛔ Chưa Phá Vỡ (Đang Chờ BOS)",
            'm15_choch_bear': m15_struct['choch_bear_level'],
            'm15_choch_bull': m15_struct['choch_bull_level'],
            'm15_choch_level': m15_struct['choch_bear_level'] if signal == 'SHORT' else m15_struct['choch_bull_level'],
            'sell_entry': sell_entry,
            'sell_sl': sell_sl,
            'sell_risk': sell_risk,
            'sell_tp1': sell_tp1,
            'sell_tp2': sell_tp2,
            'buy_entry': buy_entry,
            'buy_sl': buy_sl,
            'buy_risk': buy_risk,
            'buy_tp1': buy_tp1,
            'buy_tp2': buy_tp2,
            'entry_limit': entry_limit,
            'entry_stop': entry_stop,
            'sl': sl,
            'sl_dist': sl_dist,
            'tp1': tp1,
            'tp2': tp2,
            'advice': action_advice
        }
        PLAN_CACHE['GOLD']['data'] = plan
        PLAN_CACHE['GOLD']['candle_time'] = now
        return plan
    except Exception as e:
        print(f"Lỗi tính plan Vàng: {e}")
        raise e

def handle_gold():
    try:
        plan = calculate_gold_h4_plan()
        text = f"""🥇 <b>[KẾ HOẠCH GIAO DỊCH VÀNG - XAUUSD]</b> 🥇
━━━━━━━━━━━━━━━━━━
💰 <b>Giá Vàng hiện tại:</b> <code>${plan['current_price']:,.2f}</code> (Bid: ${plan['bid']:,.2f} | Ask: ${plan['ask']:,.2f})
📊 <b>Xu hướng chính:</b> Tuần: {plan['w1_bias']} | Ngày: {plan['d1_bias']}
🎯 <b>Định hướng:</b> <b>{plan['priority_dir']}</b>

━━━━━━━━━━━━━━━━━━
🔴 <b>1. VÙNG CANH SELL (Kháng Cự H1):</b>
• <b>Vùng giá:</b> <code>[${plan['b_ob_bot']:,.2f} - ${plan['b_ob_top']:,.2f}]</code>
• <b>Kích hoạt khi:</b> M15 thủng đáy <code>${plan['m15_choch_bear']:,.2f}</code> + M5 rút râu kích Vol
👉 <b>Entry Sell:</b> <code>${plan['sell_entry']:,.2f}</code>
🛡️ <b>Stop Loss:</b> <code>${plan['sell_sl']:,.2f}</code> (~{plan['sell_risk']:,.1f} Giá)
🎯 <b>TP1 (Ăn {plan['sell_risk']*1.2:,.1f} Giá | Chốt 50% & Dời Hoà):</b> <code>${plan['sell_tp1']:,.2f}</code>
🎯 <b>TP2 (Ăn {plan['sell_risk']*2.5:,.1f} Giá):</b> <code>${plan['sell_tp2']:,.2f}</code>

━━━━━━━━━━━━━━━━━━
🟢 <b>2. VÙNG CANH BUY (Hỗ Trợ H1):</b>
• <b>Vùng giá:</b> <code>[${plan['bull_ob_bot']:,.2f} - ${plan['bull_ob_top']:,.2f}]</code>
• <b>Kích hoạt khi:</b> M15 vượt đỉnh <code>${plan['m15_choch_bull']:,.2f}</code> + M5 rút chân kích Vol
👉 <b>Entry Buy:</b> <code>${plan['buy_entry']:,.2f}</code>
🛡️ <b>Stop Loss:</b> <code>${plan['buy_sl']:,.2f}</code> (~{plan['buy_risk']:,.1f} Giá)
🎯 <b>TP1 (Ăn {plan['buy_risk']*1.2:,.1f} Giá | Chốt 50% & Dời Hoà):</b> <code>${plan['buy_tp1']:,.2f}</code>
🎯 <b>TP2 (Ăn {plan['buy_risk']*2.5:,.1f} Giá):</b> <code>${plan['buy_tp2']:,.2f}</code>

━━━━━━━━━━━━━━━━━━
⚡ <b>TRẠNG THÁI HIỆN TẠI & HÀNH ĐỘNG:</b>
• <b>Tín hiệu vào lệnh:</b> <b>{plan['confirm_badge']}</b>
• <b>Cấu trúc M15:</b> {plan['m15_status']}
• <b>Khuyến nghị:</b> {plan['action_advice']}
━━━━━━━━━━━━━━━━━━
<i>🛡️ Quản lý vốn MT5: Rủi ro tối đa 2% ($20.0 trên tài khoản $1,000 ~ 0.01-0.02 lot).</i>"""
        send_telegram(text, reply_markup=get_main_keyboard())
    except Exception as e:
        send_telegram(f"Lỗi phân tích Vàng: {e}", reply_markup=get_main_keyboard())
        send_telegram(text, reply_markup=get_main_keyboard())
    except Exception as e:
        send_telegram(f"Lỗi phân tích Vàng: {e}", reply_markup=get_main_keyboard())

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
                    elif text in ["/check", "check", "🔍 Kiểm Tra Lệnh & Báo Cáo Ngày"]:
                        handle_check_vip_trades()
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

def sleep_until_next_m5():
    """Chờ đồng bộ đến đúng thời điểm nến M5 vừa đóng cửa (giây thứ 5 của các mốc :00, :05, :10, :15, :20, :25, :30, :35, :40, :45, :50, :55)"""
    now = time.time()
    remainder = now % 300
    sleep_sec = (300 - remainder) + 5
    if sleep_sec < 5:
        sleep_sec += 300
    return sleep_sec

def auto_diamond_alert_worker():
    """
    Quét tự động ngầm đồng bộ chuẩn M5 (mỗi 5 phút tại các mốc giờ chẵn :00, :05, :10, :15...)
    Đúng giây thứ 5 sau khi nến M5 chốt, quét ngay để đón Entry đẹp nhất ở đầu nến mới!
    """
    time.sleep(10) # Chờ bot khởi động ổn định 10 giây
    while True:
        try:
            # 1. Chờ đúng thời điểm nến M5 vừa đóng cửa (chu kỳ 5 phút các mốc chẵn)
            sleep_time = sleep_until_next_m5()
            time.sleep(sleep_time)

            now = time.time()
            # Xoá cache để luôn tính toán nến M5 mới nhất vừa đóng
            PLAN_CACHE['GOLD']['data'] = None
            PLAN_CACHE['BTC']['data'] = None
            
            # 2. Lấy kế hoạch nến M5 mới nhất cho Vàng và BTC
            plan_gold = calculate_gold_h4_plan()
            plan_btc = calculate_btc_h4_plan()

            # 3. THEO DÕI VÀ CẬP NHẬT TRẠNG THÁI CÁC LỆNH VIP ĐANG CHẠY (TP1, TP2, SL)
            check_and_update_vip_trades(plan_gold['current_price'], plan_btc['current_price'])
            active_trades = load_vip_trades()

            # 4. QUÉT TỰ ĐỘNG VÀNG (OANDA:XAUUSD - Chuẩn MT5)
            # TÔN CHỈ CHỐNG SPAM & CHỐNG CẢN TÀU:
            # 1. Nếu đang có lệnh Vàng chạy -> KHÔNG BẮN THÊM KÈO MỚI!
            # 2. BẮT BUỘC M15 PHẢI BỊ BẺ GÃY CẤU TRÚC (BOS/CHoCH) + NẾN M5 RETEST KÍCH VOL MỚI ĐƯỢC VÀO LỆNH!
            has_active_gold = any(t.get('symbol') == 'XAUUSD' for t in active_trades)
            dist_to_cản_gold = abs(plan_gold['current_price'] - plan_gold['entry_limit'])

            if not has_active_gold and plan_gold.get('is_confirmed') and ('ĐÃ PHÁ VỠ CẤU TRÚC M15' in plan_gold.get('confirm_badge', '')) and (dist_to_cản_gold <= 8.0):
                if now - LAST_ALERT_TIME['GOLD'] > 1200: # Cooldown giữa các kèo
                    price_gold = plan_gold['current_price']
                    entry_gold = plan_gold['entry_limit']
                    s_emoji = "🔴 SHORT (BÁN)" if plan_gold['signal'] == 'SHORT' else "🟢 LONG (MUA)"
                    action_l = "LỆNH VÀO NGAY (M15 Đã Gãy Cấu Trúc + M5 Retest Kích Vol):"
                    msg = f"""🚨 <b>[TỰ ĐỘNG BÁO KÈO VIP: ĐÃ PHÁ VỠ CẤU TRÚC M15 & KÍCH VOL M5]</b> 🚨
━━━━━━━━━━━━━━━━━━
📊 Nguồn biểu đồ: <b>TradingView (OANDA:XAUUSD - Chuẩn MT5)</b>
💰 Giá Vàng hiện tại: <b>${price_gold:,.2f}</b>
🎯 <b>Trạng thái:</b> <b>{plan_gold.get('confirm_badge', 'ĐÃ XÁC NHẬN')}</b>
📊 <b>Cản To Khung H1:</b> <code>${plan_gold['swing_high']:,.2f}</code> ({plan_gold.get('sh_time', '')})
   🧱 <b>Khối Bearish OB H1:</b> <code>[${plan_gold['b_ob_bot']:,.2f} - ${plan_gold['b_ob_top']:,.2f}]</code>
📉 <b>Hỗ Trợ Khung H1:</b> <code>${plan_gold['swing_low']:,.2f}</code> ({plan_gold.get('sl_time', '')})
   🧱 <b>Khối Bullish OB H1:</b> <code>[${plan_gold['bull_ob_bot']:,.2f} - ${plan_gold['bull_ob_top']:,.2f}]</code>
⚡ <b>Cấu Trúc Khung M15:</b> <b>{plan_gold.get('m15_status')}</b> (Mốc BOS: <code>${plan_gold.get('m15_choch_level', 0):,.2f}</code>)
━━━━━━━━━━━━━━━━━━
💎 <b>ĐỒNG PHA BIAS ĐA KHUNG (WINRATE CAO):</b>
• <b>Bias Tuần (W1):</b> {plan_gold['w1_bias']}
• <b>Bias Ngày (D1):</b> {plan_gold['d1_bias']}
<i>🔥 Tín hiệu tuyệt đẹp: M15 đã bẻ gãy cấu trúc (BOS) + Nến M5 retest kích Volume, TUYỆT ĐỐI KHÔNG CẢN TÀU!</i>
━━━━━━━━━━━━━━━━━━
🚀 <b>KHUYẾN NGHỊ VÀO LỆNH: {s_emoji}</b>
👉 <b>{action_l}</b>
   <code>${entry_gold:,.2f}</code>
👉 <b>LỆNH STOP NHỒI SÓNG TIẾP DIỄN:</b>
   <code>${plan_gold['entry_stop']:,.2f}</code>

🛡️ <b>Cắt lỗ (SL Ngoài Râu M5):</b>
   <code>${plan_gold['sl']:,.2f}</code> (~{plan_gold['sl_dist']:.1f} Giá)
🎯 <b>Chốt lời 1 (TP1 - R:R 1:1.2 | Chốt 50% & Dời Hoà):</b> <code>${plan_gold['tp1']:,.2f}</code>
🎯 <b>Chốt lời 2 (TP2 - R:R 1:2.5 | Gồng Về Cản):</b> <code>${plan_gold['tp2']:,.2f}</code>

🧠 <b>Kế hoạch xử lý:</b>
{plan_gold['advice']}

🛡️ <b>QUẢN LÝ VỐN VÀNG MT5 (${CONFIG['ACCOUNT_BALANCE']:,.0f}):</b>
• Rủi ro tối đa 2%: <b>$20.0</b> (tương đương 0.01 - 0.02 lot trên MT5)"""
                    send_telegram(msg)
                    LAST_ALERT_TIME['GOLD'] = now
                    # Ghi nhận lệnh vào hệ thống theo dõi duy nhất 1 lệnh
                    record_new_vip_trade(
                        asset='GOLD',
                        symbol='XAUUSD',
                        signal=plan_gold['signal'],
                        entry_price=entry_gold,
                        entry_stop=plan_gold['entry_stop'],
                        sl=plan_gold['sl'],
                        tp1=plan_gold['tp1'],
                        tp2=plan_gold['tp2'],
                        sl_dist=plan_gold['sl_dist']
                    )

            # 5. QUÉT TỰ ĐỘNG BITCOIN (BTCUSDT)
            # TÔN CHỈ CHỐNG SPAM & CHỐNG CẢN TÀU:
            has_active_btc = any(t.get('symbol') == 'BTCUSDT' for t in active_trades)
            dist_to_cản_btc = abs(plan_btc['current_price'] - plan_btc['entry_limit'])

            if not has_active_btc and plan_btc.get('is_confirmed') and ('ĐÃ PHÁ VỠ CẤU TRÚC M15' in plan_btc.get('confirm_badge', '')) and (dist_to_cản_btc <= 300.0):
                if now - LAST_ALERT_TIME['BTC'] > 1200:
                    price_btc = plan_btc['current_price']
                    entry_l = plan_btc['entry_limit']
                    entry_s = plan_btc['entry_stop']
                    s_emoji = "🔴 SHORT (BÁN)" if plan_btc['signal'] == 'SHORT' else "🟢 LONG (MUA)"
                    action_l = "LỆNH VÀO NGAY (M15 Đã Gãy Cấu Trúc + M5 Retest Kích Vol):"
                    action_s = "LỆNH STOP ĐUA SÓNG:"
                    msg = f"""🚨 <b>[TỰ ĐỘNG BÁO KÈO VIP: ĐÃ PHÁ VỠ CẤU TRÚC M15 & KÍCH VOL M5]</b> 🚨
━━━━━━━━━━━━━━━━━━
💰 Giá BTC hiện tại: <b>${price_btc:,.1f}</b>
🎯 <b>Trạng thái:</b> <b>{plan_btc.get('confirm_badge', 'ĐÃ XÁC NHẬN')}</b>
📊 <b>Cản To Khung H1:</b> <code>${plan_btc['swing_high']:,.1f}</code> ({plan_btc.get('sh_time', '')})
   🧱 <b>Khối Bearish OB H1:</b> <code>[${plan_btc['b_ob_bot']:,.1f} - ${plan_btc['b_ob_top']:,.1f}]</code>
📉 <b>Hỗ Trợ Khung H1:</b> <code>${plan_btc['swing_low']:,.1f}</code> ({plan_btc.get('sl_time', '')})
   🧱 <b>Khối Bullish OB H1:</b> <code>[${plan_btc['bull_ob_bot']:,.1f} - ${plan_btc['bull_ob_top']:,.1f}]</code>
⚡ <b>Cấu Trúc Khung M15:</b> <b>{plan_btc.get('m15_status')}</b> (Mốc BOS: <code>${plan_btc.get('m15_choch_level', 0):,.1f}</code>)
━━━━━━━━━━━━━━━━━━
💎 <b>ĐỒNG PHA BIAS ĐA KHUNG (WINRATE CAO):</b>
• <b>Bias Tuần (W1):</b> {plan_btc['w1_bias']}
• <b>Bias Ngày (D1):</b> {plan_btc['d1_bias']}
<i>🔥 Tín hiệu tuyệt đẹp: M15 đã bẻ gãy cấu trúc (BOS) + Nến M5 retest kích Volume, TUYỆT ĐỐI KHÔNG CẢN TÀU!</i>
━━━━━━━━━━━━━━━━━━
🚀 <b>KHUYẾN NGHỊ VÀO LỆNH: {s_emoji}</b>
👉 <b>{action_l}:</b>
   <code>${entry_l:,.1f}</code>
👉 <b>{action_s}:</b>
   <code>${entry_s:,.1f}</code>

🛡️ <b>Cắt lỗ (SL Ngoài Râu M5):</b> <code>${plan_btc['sl']:,.1f}</code> (-{plan_btc['sl_pct']}%)
🎯 <b>Chốt lời 1 (TP1 - R:R 1:1.2 | Chốt 50% & Dời Hoà):</b> <code>${plan_btc['tp1']:,.1f}</code>
🎯 <b>Chốt lời 2 (TP2 - R:R 1:2.5 | Gồng Theo Sóng):</b> <code>${plan_btc['tp2']:,.1f}</code>

🧠 <b>Kế hoạch xử lý:</b>
{plan_btc['advice']}

🛡️ <b>QUẢN LÝ VỐN (${CONFIG['ACCOUNT_BALANCE']:,.0f}):</b>
• Rủi ro tối đa 2%: <b>$20.0</b> | Khối lượng: <b>$1,000.0</b> | Đòn bẩy: <b>5x</b>"""
                    send_telegram(msg)
                    LAST_ALERT_TIME['BTC'] = now
                    record_new_vip_trade(
                        asset='BTC',
                        symbol='BTCUSDT',
                        signal=plan_btc['signal'],
                        entry_price=entry_l,
                        entry_stop=entry_s,
                        sl=plan_btc['sl'],
                        tp1=plan_btc['tp1'],
                        tp2=plan_btc['tp2'],
                        sl_dist=abs(entry_l - plan_btc['sl'])
                    )
                    send_telegram(msg)
                    LAST_ALERT_TIME['BTC'] = now
                    record_new_vip_trade(
                        asset='BTC',
                        symbol='BTCUSDT',
                        signal=plan_btc['signal'],
                        entry_price=entry_l,
                        entry_stop=entry_s,
                        sl=plan_btc['sl'],
                        tp1=plan_btc['tp1'],
                        tp2=plan_btc['tp2'],
                        sl_dist=abs(entry_l - plan_btc['sl'])
                    )

        except Exception as e:
            print(f"Lỗi worker quét tự động: {e}")
            time.sleep(10)

if __name__ == '__main__':
    threading.Thread(target=start_health_server, daemon=True).start()
    threading.Thread(target=self_ping_worker, daemon=True).start()
    threading.Thread(target=auto_diamond_alert_worker, daemon=True).start()
    run_bot()
