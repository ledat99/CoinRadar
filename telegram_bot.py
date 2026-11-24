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
    'ACCOUNT_BALANCE': 2000.0,
    'RISK_PER_TRADE': 2.0,
}

TZ_VN = datetime.timezone(datetime.timedelta(hours=7))
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

# Cache lưu trữ các mức cản H4 để cố định điểm vào lệnh trong phiên H4
PLAN_CACHE = {
    'BTC': {'candle_time': 0, 'data': None},
    'GOLD': {'candle_time': 0, 'data': None},
    'COINS_LONG': {'time': 0, 'data': []},
    'COINS_SHORT': {'time': 0, 'data': []},
    'VN_STOCKS': {'time': 0, 'data': None},
    'VP_SCALP': {'time': 0, 'data': None},
    'MEME_COINS': {'time': 0, 'data': []}
}

LAST_ALERT_TIME = {
    'GOLD': 0,
    'BTC': 0,
    'GOLD_SCALP': 0,
    'BTC_SCALP': 0
}

LAST_RADAR_ALERT = {
    'BTC_BEAR': 0,
    'BTC_BULL': 0,
    'GOLD_BEAR': 0,
    'GOLD_BULL': 0
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

def handle_check_vip_trades(chat_id=None):
    try:
        trades = load_vip_trades()
        history = load_vip_history()

        plan_gold = calculate_gold_h4_plan()
        plan_btc = calculate_btc_h4_plan()
        p_gold_vp = analyze_scalp_vp_plan('GOLD')
        p_btc_vp = analyze_scalp_vp_plan('BTC')

        p_gold = plan_gold['current_price']
        p_btc = plan_btc['current_price']

        msg = "🔍 <b>[BÁO CÁO THỜI GIAN THỰC & THEO DÕI TÍN HIỆU BOT]</b>\n━━━━━━━━━━━━━━━━━━\n"

        # 1. PHẦN LỆNH ĐANG CHẠY (NẾU CÓ)
        if trades:
            msg += f"🔥 <b>LỆNH VIP ĐANG CHẠY ({len(trades)} lệnh):</b>\n\n"
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
                msg += f"• Giá vào (Entry): <code>${t['entry_price']:,.{dec}f}</code> | Hiện tại: <b>${curr_p:,.{dec}f}</b>\n"
                msg += f"• Lãi/Lỗ tạm tính: {pnl_emoji} <b>{pnl_str}</b>\n"
                msg += f"• Trạng thái: <b>{status_txt}</b>\n"
                msg += f"• Stop Loss: <code>${t['sl']:,.{dec}f}</code>\n"
                msg += f"• Mốc TP1: <code>${t['tp1']:,.{dec}f}</code> {'(✅ Đã Chạm)' if t.get('tp1_hit') else ''}\n"
                msg += f"• Mốc TP2: <code>${t['tp2']:,.{dec}f}</code>\n\n"
        else:
            msg += "🟢 <b>Lệnh Đang Chạy:</b> <i>Chưa có lệnh mở (Đang rình điểm đẹp).</i>\n\n"

        # 2. RADAR GIÁM SÁT THỜI GIAN THỰC (LIVE RADAR MONITOR)
        msg += "📡 <b>RADAR GIÁM SÁT THỊ TRƯỜNG & VÙNG CẢN:</b>\n"
        
        # Vàng Radar
        dist_do_g = p_gold - p_gold_vp['daily_open']
        dist_poc_g = p_gold - p_gold_vp['poc']
        msg += f"""\n🥇 <b>VÀNG (XAUUSD MT5):</b> <b>${p_gold:,.2f}</b>
• 🧭 <b>Bias Ngày:</b> {p_gold_vp['daily_bias']}
• 🏛️ <b>Hôm Trước:</b> {p_gold_vp['y_shape']} [yVAL <code>${p_gold_vp['y_val']:,.1f}</code> | yPOC <code>${p_gold_vp['y_poc']:,.1f}</code> | yVAH <code>${p_gold_vp['y_vah']:,.1f}</code>]
• 🌅 <b>Daily Open:</b> <code>${p_gold_vp['daily_open']:,.2f}</code> (Cách {abs(dist_do_g):.1f} giá)
• 📍 <b>dPOC Hôm Nay:</b> <code>${p_gold_vp['poc']:,.2f}</code> (Cách {abs(dist_poc_g):.1f} giá)
• 🧱 <b>Khối Kháng Cự H1:</b> <code>[${plan_gold['b_ob_bot']:,.1f} - ${plan_gold['b_ob_top']:,.1f}]</code>
• 🧱 <b>Khối Hỗ Trợ H1:</b> <code>[${plan_gold['bull_ob_bot']:,.1f} - ${plan_gold['bull_ob_top']:,.1f}]</code>
• ⚡ <b>Hành động M5:</b> <i>{p_gold_vp['wick_info']}</i>
👉 <b>Kèo Gợi Ý:</b> <b>{p_gold_vp['signal']}</b>
   Entry: <code>${p_gold_vp['entry']:,.2f}</code> | SL: <code>${p_gold_vp['sl']:,.2f}</code> | TP1: <code>${p_gold_vp['tp1']:,.2f}</code> | TP2: <code>${p_gold_vp['tp2']:,.2f}</code>\n"""

        # BTC Radar
        dist_do_b = p_btc - p_btc_vp['daily_open']
        dist_poc_b = p_btc - p_btc_vp['poc']
        msg += f"""\n👑 <b>BITCOIN (BTCUSDT):</b> <b>${p_btc:,.1f}</b>
• 🧭 <b>Bias Ngày:</b> {p_btc_vp['daily_bias']}
• 🏛️ <b>Hôm Trước:</b> {p_btc_vp['y_shape']} [yVAL <code>${p_btc_vp['y_val']:,.1f}</code> | yPOC <code>${p_btc_vp['y_poc']:,.1f}</code> | yVAH <code>${p_btc_vp['y_vah']:,.1f}</code>]
• 🌅 <b>Daily Open:</b> <code>${p_btc_vp['daily_open']:,.1f}</code> (Cách {abs(dist_do_b):.1f} USD)
• 📍 <b>dPOC Hôm Nay:</b> <code>${p_btc_vp['poc']:,.1f}</code> (Cách {abs(dist_poc_b):.1f} USD)
• 🧱 <b>Khối Kháng Cự H1:</b> <code>[${plan_btc['b_ob_bot']:,.1f} - ${plan_btc['b_ob_top']:,.1f}]</code>
• 🧱 <b>Khối Hỗ Trợ H1:</b> <code>[${plan_btc['bull_ob_bot']:,.1f} - ${plan_btc['bull_ob_top']:,.1f}]</code>
• ⚡ <b>Hành động M5:</b> <i>{p_btc_vp['wick_info']}</i>
👉 <b>Kèo Gợi Ý:</b> <b>{p_btc_vp['signal']}</b>
   Entry: <code>${p_btc_vp['entry']:,.1f}</code> | SL: <code>${p_btc_vp['sl']:,.1f}</code> | TP1: <code>${p_btc_vp['tp1']:,.1f}</code> | TP2: <code>${p_btc_vp['tp2']:,.1f}</code>\n"""

        # 3. LỊCH SỬ KÈO & TỶ LỆ THẮNG
        msg += "━━━━━━━━━━━━━━━━━━\n📜 <b>LỊCH SỬ GIAO DỊCH ĐÃ CHỐT:</b>\n"
        if not history:
            msg += "• Chưa có lệnh nào được chốt trong chu kỳ hôm nay.\n"
            msg += "<i>💡 Bot tự động rà quét mỗi 5 phút tại các mốc nến M5 chốt. Khi nến M5 chạm dPOC/OB H1 và rút râu nổ Volume, Bot sẽ tự động bắn kèo và ghi nhận ngay vào đây!</i>"
        else:
            total_closed = len(history)
            wins = [h for h in history if 'TP' in h.get('status', '') or h.get('status') == 'CLOSED_BREAKEVEN' or h.get('profit', 0) > 0]
            win_rate = (len(wins) / total_closed) * 100.0
            msg += f"• Tổng số kèo: <b>{total_closed}</b> | Thắng: <b>{len(wins)}</b> | Thua: <b>{total_closed - len(wins)}</b>\n"
            msg += f"• Tỷ lệ Winrate: <b>{win_rate:.1f}%</b> 🔥\n"
            msg += "• Các lệnh gần nhất:\n"
            for h in history[-5:]:
                sym = "VÀNG" if h.get('asset') == 'GOLD' else "BTC"
                p_val = h.get('profit', 0)
                sgn_p = f"+{p_val}" if p_val >= 0 else f"{p_val}"
                st = "✅ TP Full" if h.get('status') == 'CLOSED_TP2' else ("🛡️ Hoà Vốn" if h.get('status') == 'CLOSED_BREAKEVEN' else "🛑 Cắt Lỗ")
                msg += f"  - {sym} {h.get('signal')}: {st} ({sgn_p}) [{h.get('close_time', '')}]\n"

        send_telegram(msg, reply_markup=get_main_keyboard(), target_chat_id=chat_id)
    except Exception as e:
        send_telegram(f"Lỗi kiểm tra lệnh: {e}", reply_markup=get_main_keyboard(), target_chat_id=chat_id)

USERS_FILE = os.path.join(os.path.dirname(__file__), 'authorized_users.json')
ADMIN_ID = str(CONFIG['TELEGRAM_CHAT_ID'])

def load_authorized_users():
    """Load danh sách người dùng được duyệt sử dụng bot"""
    users = {ADMIN_ID: {'name': 'Chủ Sở Hữu (Admin)', 'role': 'admin', 'date': 'Gốc'}}
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, 'r', encoding='utf-8') as f:
                saved = json.load(f)
                users.update(saved)
        except Exception as e:
            print(f"Lỗi load authorized users: {e}")
    return users

def save_authorized_users(users):
    try:
        with open(USERS_FILE, 'w', encoding='utf-8') as f:
            json.dump(users, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Lỗi save authorized users: {e}")

def is_user_approved(chat_id):
    users = load_authorized_users()
    return str(chat_id) in users

def add_approved_user(chat_id, name="User"):
    users = load_authorized_users()
    chat_id = str(chat_id)
    users[chat_id] = {
        'name': name,
        'role': 'user',
        'date': datetime.datetime.now(TZ_VN).strftime('%H:%M %d/%m/%Y')
    }
    save_authorized_users(users)

def remove_approved_user(chat_id):
    users = load_authorized_users()
    chat_id = str(chat_id)
    if chat_id == ADMIN_ID:
        return False
    if chat_id in users:
        del users[chat_id]
        save_authorized_users(users)
        return True
    return False

def send_telegram(text, reply_markup=None, target_chat_id=None):
    """
    Gửi tin nhắn Telegram:
    - Nếu có target_chat_id: Gửi riêng cho người dùng cụ thể.
    - Nếu target_chat_id=None: Phát sóng (broadcast) đồng loạt cho TẤT CẢ thành viên được Admin duyệt!
    - Tự động gắn bàn phím get_main_keyboard() nếu reply_markup không được chỉ định rõ.
    """
    if reply_markup is None:
        reply_markup = get_main_keyboard()
    url = f"https://api.telegram.org/bot{CONFIG['TELEGRAM_BOT_TOKEN']}/sendMessage"
    
    if target_chat_id is not None:
        payload = {
            "chat_id": str(target_chat_id),
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        try:
            requests.post(url, json=payload, timeout=10)
        except Exception as e:
            print(f"Lỗi gửi Telegram tới {target_chat_id}: {e}")
        return

    # Broadcast cho toàn bộ thành viên được duyệt
    users = load_authorized_users()
    for uid in users.keys():
        payload = {
            "chat_id": str(uid),
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        try:
            requests.post(url, json=payload, timeout=10)
        except Exception as e:
            print(f"Lỗi broadcast tới {uid}: {e}")

def get_main_keyboard():
    return {
        "keyboard": [
            [{"text": "👑 Phân Tích BTC"}, {"text": "🥇 Phân Tích VÀNG (XAU)"}],
            [{"text": "🎯 Scalping Volume Profile M5"}, {"text": "⚡ Tuyệt Chiêu H4 Lưỡng Lự"}],
            [{"text": "💣 Săn Coin Rác (Vol > $100M)"}],
            [{"text": "📈 Tìm Coin TĂNG (LONG)"}, {"text": "📉 Tìm Coin GIẢM (SHORT)"}],
            [{"text": "🇻🇳 Đánh Giá Cổ Phiếu VN"}, {"text": "🔍 Kiểm Tra Lệnh & Báo Cáo Ngày"}],
            [{"text": "⚙️ Menu Hỗ Trợ"}]
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
    prior_lows = lows[max(0, max_h_idx - 3): max_h_idx]
    if prior_lows:
        choch_bear_level = round(min(prior_lows[-2:]) if len(prior_lows) >= 2 else prior_lows[0], 2 if is_gold else 1)
    else:
        choch_bear_level = round(lows[max(0, max_h_idx - 1)], 2 if is_gold else 1)
        
    # Kiểm tra xem nến từ sau đỉnh có nến nào đóng cửa hoặc giá hiện tại đâm thủng đáy này chưa
    has_bear_bos = (curr_p < choch_bear_level) or any(c < choch_bear_level for c in closes[max_h_idx:])
    
    # 2. Tìm đáy gần nhất trong 15 nến M15 và đỉnh Swing High tạo nên đáy đó (M15 Bullish CHoCH level)
    recent_lows = lows[-recent_len:]
    min_l_idx = (n - recent_len) + int(np.argmin(recent_lows))
    
    # Đỉnh tạo nên đáy này nằm trong các nến trước min_l_idx
    prior_highs = highs[max(0, min_l_idx - 3): min_l_idx]
    if prior_highs:
        choch_bull_level = round(max(prior_highs[-2:]) if len(prior_highs) >= 2 else prior_highs[0], 2 if is_gold else 1)
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
            with urllib.request.urlopen(req, timeout=12) as r:
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

        # Kiểm tra khoảng cách giá tới 2 Khối OB H1 (tiếp cận hoặc nến M5 quét cản)
        is_near_bear_ob = abs(current_price - bearish_ob['bottom']) <= 300.0 or (current_price >= bearish_ob['bottom'] and current_price <= bearish_ob['top'] + 150.0)
        is_near_bull_ob = abs(current_price - bullish_ob['top']) <= 300.0 or (current_price <= bullish_ob['top'] and current_price >= bullish_ob['bottom'] - 150.0)

        # 1. Phát hiện Rejection KeyVolume M5 sớm tại cản OB H1 (Bắt Đảo Chiều Đỉnh Cao với SL Siêu Ngắn):
        sell_conf = m5_info['confirmed_bear_rejection']
        buy_conf = m5_info['confirmed_bull_rejection']

        touched_bear_ob = (current_price >= bearish_ob['bottom'] - 50.0 and current_price <= bearish_ob['top'] + 200.0) or (m5_info['m5_high'] >= bearish_ob['bottom'] - 20.0 and current_price >= bearish_ob['bottom'] - 350.0)
        touched_bull_ob = (current_price <= bullish_ob['top'] + 50.0 and current_price >= bullish_ob['bottom'] - 200.0) or (m5_info['m5_low'] <= bullish_ob['top'] + 20.0 and current_price <= bullish_ob['top'] + 350.0)

        is_early_bear = touched_bear_ob and (sell_conf is not None) and (sell_conf['wick_pct'] >= 35.0 and sell_conf['vol_ratio'] >= 1.25)
        is_early_bull = touched_bull_ob and (buy_conf is not None) and (buy_conf['wick_pct'] >= 35.0 and buy_conf['vol_ratio'] >= 1.25)

        # XÁC ĐỊNH HƯỚNG ĐÁNH THEO BIAS VĨ MÔ & TEST CẢN
        # ĐIỀU KIỆN XÁC NHẬN: REJECTION KEYVOLUME M5 TẠI OB HOẶC M15 PHÁ VỠ CẤU TRÚC (BOS) + M5 RÚT RÂU!
        is_bear_confirmed = is_early_bear or (is_near_bear_ob and m15_struct['has_bear_bos'] and m5_info['is_confirmed_entry_bear'])
        is_bull_confirmed = is_early_bull or (is_near_bull_ob and m15_struct['has_bull_bos'] and m5_info['is_confirmed_entry_bull'])

        if is_bull_confirmed and not (w1_bear and d1_bear):
            signal = "LONG"
            if is_early_bull:
                setup_desc = f"Rejection KeyVolume M5 tại Khối Bullish OB ${bullish_ob['mid']:,.1f} (Rút chân {buy_conf['wick_pct']}%, Vol {buy_conf['vol_ratio']}x)"
                diamond_note = "⭐ BẮT ĐẢO CHIỀU TẠI CẢN: Nến M5 rút chân nổ Volume tại Hỗ Trợ H1, SL siêu ngắn!"
            else:
                setup_desc = f"M15 BOS Tăng + M5 Rút Chân Kích Volume tại Khối Bullish OB ${swing_low:,.1f} ({sl_time})"
                diamond_note = "⭐ ĐẢO CHIỀU UY TÍN (CÂN BẰNG QUÂN LỰC): M15 đã phá cấu trúc + M5 kích Volume xác nhận!"
        elif is_bear_confirmed or (w1_bear and d1_bear):
            signal = "SHORT"
            if is_early_bear:
                setup_desc = f"Rejection KeyVolume M5 tại Khối Bearish OB ${bearish_ob['mid']:,.1f} (Rút râu {sell_conf['wick_pct']}%, Vol {sell_conf['vol_ratio']}x)"
                diamond_note = "⭐ BẮT ĐẢO CHIỀU TẠI CẢN: Nến M5 rút râu nổ Volume tại Kháng Cự H1, SL siêu ngắn!"
            else:
                m5_txt = " + M15 BOS & Kích Vol M5" if is_bear_confirmed else " (Đang Chờ M15 BOS)"
                setup_desc = f"Đồng Pha Giảm Tuần/Ngày - Test Khối Bearish OB H1 ${bearish_ob['mid']:,.1f}{m5_txt}"
                diamond_note = "⭐ ĐỒNG PHA TUẦN + NGÀY (CẢN TO H1): Tuyệt đối không cản tàu, chờ M15 phá vỡ cấu trúc!"
        else:
            signal = "SHORT" if d1_bear else "LONG"
            setup_desc = f"Cấu Trúc KeyVolume H1 tại Khối OB ${bearish_ob['mid']:,.1f}"
            diamond_note = "⚡ Quản lý vốn theo từng mốc cản."

        # Tính thông số chi tiết chuẩn xác cho cả 2 VÙNG CANH SELL và VÙNG CANH BUY
        # 1. Kịch bản CANH SELL (tại Kháng Cự H1):
        if is_early_bear and sell_conf:
            sell_entry = round(current_price, 1)
            sell_sl = round(max(sell_conf['high'] + 50.0, bearish_ob['top'] + 50.0), 1)
            sell_risk = round(sell_sl - sell_entry, 1)
            if sell_risk < 150.0:
                sell_sl = round(sell_entry + 200.0, 1)
                sell_risk = round(sell_sl - sell_entry, 1)
            sell_tp1 = round(sell_entry - (sell_risk * 1.5), 1)
            sell_tp2 = round(sell_entry - (sell_risk * 3.0), 1)
        else:
            sell_entry = round(bearish_ob['bottom'], 1)
            sell_sl = round(max(bearish_ob['top'] + 150.0, swing_high + 100.0), 1)
            sell_risk = round(sell_sl - sell_entry, 1)
            if sell_risk < 250.0:
                sell_sl = round(sell_entry + 300.0, 1)
                sell_risk = round(sell_sl - sell_entry, 1)
            sell_tp1 = round(sell_entry - (sell_risk * 1.2), 1)
            sell_tp2 = round(sell_entry - (sell_risk * 2.5), 1)

        # 2. Kịch bản CANH BUY (tại Hỗ Trợ H1):
        if is_early_bull and buy_conf:
            buy_entry = round(current_price, 1)
            buy_sl = round(min(buy_conf['low'] - 50.0, bullish_ob['bottom'] - 50.0), 1)
            buy_risk = round(buy_entry - buy_sl, 1)
            if buy_risk < 150.0:
                buy_sl = round(buy_entry - 200.0, 1)
                buy_risk = round(buy_entry - buy_sl, 1)
            buy_tp1 = round(buy_entry + (buy_risk * 1.5), 1)
            buy_tp2 = round(buy_entry + (buy_risk * 3.0), 1)
        else:
            buy_entry = round(bullish_ob['top'], 1)
            buy_sl = round(min(bullish_ob['bottom'] - 150.0, swing_low - 100.0), 1)
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
            if is_early_bear:
                confirm_badge = "🔥 REJECTION KEYVOLUME M5 TẠI OB H1 (RÚT RÂU & NỔ VOL)"
                action_advice = f"Nến M5 lúc {sell_conf['time']} test Bearish OB H1 rút râu {sell_conf['wick_pct']}% kích Volume {sell_conf['vol_ratio']}x! Đủ điều kiện vào lệnh Sell ngay tại chóp râu M5!"
            elif not is_near_bear_ob:
                confirm_badge = "⏳ CHỜ GIÁ TIẾP CẬN VÙNG CANH SELL (OB H1)"
                action_advice = f"Giá BTC (${current_price:,.1f}) đang cách Vùng Sell [${bearish_ob['bottom']:,.1f} - ${bearish_ob['top']:,.1f}] khoảng {abs(current_price - bearish_ob['bottom']):,.1f} USD. Chưa chạm cản, đứng ngoài quan sát!"
            elif not m15_struct['has_bear_bos']:
                confirm_badge = "⏳ ĐÃ VÀO VÙNG CẢN - CHỜ M15 PHÁ VỠ CẤU TRÚC (TRÁNH CẢN TÀU)"
                action_advice = f"Giá đang chạm Vùng Sell nhưng M15 chưa gãy cấu trúc (chưa thủng đáy ${m15_struct['choch_bear_level']:,.1f}). Đứng ngoài quan sát, tuyệt đối không cản tàu!"
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
            if is_early_bull:
                confirm_badge = "🔥 REJECTION KEYVOLUME M5 TẠI OB H1 (RÚT RÂU & NỔ VOL)"
                action_advice = f"Nến M5 lúc {buy_conf['time']} test Bullish OB H1 rút chân {buy_conf['wick_pct']}% kích Volume {buy_conf['vol_ratio']}x! Đủ điều kiện vào lệnh Buy ngay tại chóp râu M5!"
            elif not is_near_bull_ob:
                confirm_badge = "⏳ CHỜ GIÁ TIẾP CẬN VÙNG CANH BUY (OB H1)"
                action_advice = f"Giá BTC (${current_price:,.1f}) đang cách Vùng Buy [${bullish_ob['bottom']:,.1f} - ${bullish_ob['top']:,.1f}] khoảng {abs(current_price - bullish_ob['top']):,.1f} USD. Chưa chạm hỗ trợ, đứng ngoài quan sát!"
            elif not m15_struct['has_bull_bos']:
                confirm_badge = "⏳ ĐÃ VÀO VÙNG HỖ TRỢ - CHỜ M15 PHÁ VỠ CẤU TRÚC (TRÁNH BẮT DAO RƠI)"
                action_advice = f"Giá đang chạm Vùng Buy nhưng M15 chưa đảo chiều tăng (chưa vượt đỉnh ${m15_struct['choch_bull_level']:,.1f}). Đứng ngoài quan sát, tuyệt đối không bắt dao rơi!"
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

def handle_btc(chat_id=None):
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
• <b>Cách đánh:</b> Chờ giá hồi lên chạm vùng này ──> Nến M5 rút râu từ chối + Kích Volume thì SELL!
👉 <b>Entry Sell:</b> <code>${plan['sell_entry']:,.1f}</code>
🛡️ <b>Stop Loss:</b> <code>${plan['sell_sl']:,.1f}</code> (~{plan['sell_risk']:,.1f} USD)
🎯 <b>TP1 (Ăn {plan['sell_risk']*1.2:,.1f} USD | Chốt 50% & Dời Hoà):</b> <code>${plan['sell_tp1']:,.1f}</code>
🎯 <b>TP2 (Ăn {plan['sell_risk']*2.5:,.1f} USD):</b> <code>${plan['sell_tp2']:,.1f}</code>

━━━━━━━━━━━━━━━━━━
🟢 <b>2. VÙNG CANH BUY (Hỗ Trợ H1):</b>
• <b>Vùng giá:</b> <code>[${plan['bull_ob_bot']:,.1f} - ${plan['bull_ob_top']:,.1f}]</code>
• <b>Cách đánh:</b> Chờ giá đạp về chạm vùng này ──> Nến M5 rút chân đẩy lên + Kích Volume thì BUY!
👉 <b>Entry Buy:</b> <code>${plan['buy_entry']:,.1f}</code>
🛡️ <b>Stop Loss:</b> <code>${plan['buy_sl']:,.1f}</code> (~{plan['buy_risk']:,.1f} USD)
🎯 <b>TP1 (Ăn {plan['buy_risk']*1.2:,.1f} USD | Chốt 50% & Dời Hoà):</b> <code>${plan['buy_tp1']:,.1f}</code>
🎯 <b>TP2 (Ăn {plan['buy_risk']*2.5:,.1f} USD):</b> <code>${plan['buy_tp2']:,.1f}</code>

━━━━━━━━━━━━━━━━━━
🧠 <b>TRẠNG THÁI HIỆN TẠI:</b>
• <b>Tín hiệu vào lệnh:</b> <b>{plan['confirm_badge']}</b>
• <b>Cấu trúc M15:</b> {plan['m15_status']}
• <b>Nhận định:</b> {plan['action_advice']}
━━━━━━━━━━━━━━━━━━
<i>🛡️ Quản lý vốn: Rủi ro tối đa 2% ($40.0 trên tài khoản $2,000).</i>"""
        send_telegram(text, reply_markup=get_main_keyboard(), target_chat_id=chat_id)
    except Exception as e:
        send_telegram(f"Lỗi BTC POC: {e}", reply_markup=get_main_keyboard(), target_chat_id=chat_id)

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
            with urllib.request.urlopen(req_gm5, timeout=12) as r:
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

        # Kiểm tra khoảng cách giá Vàng tới 2 Khối OB H1 (tiếp cận hoặc nến M5 quét cản)
        is_near_bear_ob = abs(current_gold - b_ob_bot) <= 8.0 or (current_gold >= b_ob_bot and current_gold <= b_ob_top + 4.0)
        is_near_bull_ob = abs(current_gold - bull_ob_top) <= 8.0 or (current_gold <= bull_ob_top and current_gold >= bull_ob_bot - 4.0)

        # 1. Phát hiện Rejection KeyVolume M5 sớm tại cản OB H1 (Bắt Đảo Chiều Đỉnh Cao với SL Siêu Ngắn):
        sell_conf = m5_info['confirmed_bear_rejection']
        buy_conf = m5_info['confirmed_bull_rejection']

        touched_bear_ob = (current_gold >= b_ob_bot - 1.5 and current_gold <= b_ob_top + 4.0) or (m5_info['m5_high'] >= b_ob_bot - 0.5 and current_gold >= b_ob_bot - 8.0)
        touched_bull_ob = (current_gold <= bull_ob_top + 1.5 and current_gold >= bull_ob_bot - 4.0) or (m5_info['m5_low'] <= bull_ob_top + 0.5 and current_gold <= bull_ob_top + 8.0)

        is_early_bear = touched_bear_ob and (sell_conf is not None) and (sell_conf['wick_pct'] >= 35.0 and sell_conf['vol_ratio'] >= 1.25)
        is_early_bull = touched_bull_ob and (buy_conf is not None) and (buy_conf['wick_pct'] >= 35.0 and buy_conf['vol_ratio'] >= 1.25)

        # XÁC ĐỊNH HƯỚNG ĐÁNH THEO BIAS VĨ MÔ & TEST CẢN
        # ĐIỀU KIỆN XÁC NHẬN: REJECTION KEYVOLUME M5 TẠI OB HOẶC M15 PHÁ VỠ CẤU TRÚC (BOS) + M5 RÚT RÂU!
        is_bear_confirmed = is_early_bear or (is_near_bear_ob and m15_struct['has_bear_bos'] and m5_info['is_confirmed_entry_bear'])
        is_bull_confirmed = is_early_bull or (is_near_bull_ob and m15_struct['has_bull_bos'] and m5_info['is_confirmed_entry_bull'])
        
        if is_bull_confirmed and not (w1_bear and d1_bear):
            signal = "LONG"
            if is_early_bull:
                setup_desc = f"Rejection KeyVolume M5 tại Khối Bullish OB ${bull_ob_mid:,.2f} (Rút chân {buy_conf['wick_pct']}%, Vol {buy_conf['vol_ratio']}x)"
                diamond_note = "⭐ BẮT ĐẢO CHIỀU TẠI CẢN: Nến M5 rút chân nổ Volume tại Hỗ Trợ H1, SL siêu ngắn!"
            else:
                setup_desc = f"M15 BOS Tăng + M5 Rút Chân Kích Volume tại Khối Bullish OB ${major_sup:,.2f} ({sl_time})"
                diamond_note = "⭐ ĐẢO CHIỀU UY TÍN (CÂN BẰNG QUÂN LỰC): M15 đã phá cấu trúc + M5 kích Volume xác nhận!"
        elif is_bear_confirmed or (w1_bear and d1_bear):
            signal = "SHORT"
            if is_early_bear:
                setup_desc = f"Rejection KeyVolume M5 tại Khối Bearish OB ${b_ob_mid:,.2f} (Rút râu {sell_conf['wick_pct']}%, Vol {sell_conf['vol_ratio']}x)"
                diamond_note = "⭐ BẮT ĐẢO CHIỀU TẠI CẢN: Nến M5 rút râu nổ Volume tại Kháng Cự H1, SL siêu ngắn!"
            else:
                m5_txt = " + M15 BOS & Kích Vol M5" if is_bear_confirmed else " (Đang Chờ M15 BOS)"
                setup_desc = f"Đồng Pha Giảm Tuần/Ngày - Test Khối Bearish OB H1 ${b_ob_mid:,.2f}{m5_txt}"
                diamond_note = "⭐ ĐỒNG PHA TUẦN + NGÀY (CẢN TO H1): Tuyệt đối không cản tàu, chờ M15 phá vỡ cấu trúc!"
        else:
            signal = "SHORT" if d1_bear else "LONG"
            setup_desc = f"Cấu Trúc KeyVolume H1 tại Khối OB ${b_ob_mid:,.2f}"
            diamond_note = "⚡ Quản lý vốn chặt chẽ theo cản."
        
        # Tính thông số chi tiết chuẩn xác cho cả 2 VÙNG CANH SELL và VÙNG CANH BUY
        # 1. Kịch bản CANH SELL (tại Kháng Cự H1):
        if is_early_bear and sell_conf:
            sell_entry = round(current_gold, 2)
            sell_sl = round(max(sell_conf['high'] + 1.5, b_ob_top + 1.5), 2)
            sell_risk = round(sell_sl - sell_entry, 2)
            if sell_risk < 3.5:
                sell_sl = round(sell_entry + 5.0, 2)
                sell_risk = round(sell_sl - sell_entry, 2)
            sell_tp1 = round(sell_entry - (sell_risk * 1.5), 2)
            sell_tp2 = round(sell_entry - (sell_risk * 3.0), 2)
        else:
            sell_entry = round(b_ob_bot, 2)
            sell_sl = round(max(b_ob_top + 4.0, major_res + 2.5), 2)
            sell_risk = round(sell_sl - sell_entry, 2)
            if sell_risk < 6.0:
                sell_sl = round(sell_entry + 8.0, 2)
                sell_risk = round(sell_sl - sell_entry, 2)
            elif sell_risk > 25.0:
                sell_sl = round(sell_entry + 20.0, 2)
                sell_risk = round(sell_sl - sell_entry, 2)
            sell_tp1 = round(sell_entry - (sell_risk * 1.2), 2)
            sell_tp2 = round(sell_entry - (sell_risk * 2.5), 2)

        # 2. Kịch bản CANH BUY (tại Hỗ Trợ H1):
        if is_early_bull and buy_conf:
            buy_entry = round(current_gold, 2)
            buy_sl = round(min(buy_conf['low'] - 1.5, bull_ob_bot - 1.5), 2)
            buy_risk = round(buy_entry - buy_sl, 2)
            if buy_risk < 3.5:
                buy_sl = round(buy_entry - 5.0, 2)
                buy_risk = round(buy_entry - buy_sl, 2)
            buy_tp1 = round(buy_entry + (buy_risk * 1.5), 2)
            buy_tp2 = round(buy_entry + (buy_risk * 3.0), 2)
        else:
            buy_entry = round(bull_ob_top, 2)
            buy_sl = round(min(bull_ob_bot - 4.0, major_sup - 2.5), 2)
            buy_risk = round(buy_entry - buy_sl, 2)
            if buy_risk < 6.0:
                buy_sl = round(buy_entry - 8.0, 2)
                buy_risk = round(buy_entry - buy_sl, 2)
            elif buy_risk > 25.0:
                buy_sl = round(buy_entry - 20.0, 2)
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
            if is_early_bear:
                confirm_badge = "🔥 REJECTION KEYVOLUME M5 TẠI OB H1 (RÚT RÂU & NỔ VOL)"
                action_advice = f"Nến M5 lúc {sell_conf['time']} test Bearish OB H1 rút râu {sell_conf['wick_pct']}% kích Volume {sell_conf['vol_ratio']}x! Đủ điều kiện vào lệnh Sell ngay tại chóp râu M5!"
            elif not is_near_bear_ob:
                confirm_badge = "⏳ CHỜ GIÁ TIẾP CẬN VÙNG CANH SELL (OB H1)"
                action_advice = f"Giá Vàng (${current_gold:,.2f}) đang cách Vùng Sell [${b_ob_bot:,.2f} - ${b_ob_top:,.2f}] khoảng {abs(current_gold - b_ob_bot):.1f} giá. Chưa chạm cản, đứng ngoài quan sát!"
            elif not m15_struct['has_bear_bos']:
                confirm_badge = "⏳ ĐÃ VÀO VÙNG CẢN - CHỜ M15 PHÁ VỠ CẤU TRÚC (TRÁNH CẢN TÀU)"
                action_advice = f"Giá Vàng đang phản ứng tại Vùng Sell. M15 chưa gãy cấu trúc (chưa thủng đáy ${m15_struct['choch_bear_level']:,.2f}). Đứng ngoài quan sát, tuyệt đối không cản tàu!"
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
            if is_early_bull:
                confirm_badge = "🔥 REJECTION KEYVOLUME M5 TẠI OB H1 (RÚT RÂU & NỔ VOL)"
                action_advice = f"Nến M5 lúc {buy_conf['time']} test Bullish OB H1 rút chân {buy_conf['wick_pct']}% kích Volume {buy_conf['vol_ratio']}x! Đủ điều kiện vào lệnh Buy ngay tại chóp râu M5!"
            elif not is_near_bull_ob:
                confirm_badge = "⏳ CHỜ GIÁ TIẾP CẬN VÙNG CANH BUY (OB H1)"
                action_advice = f"Giá Vàng (${current_gold:,.2f}) đang cách Vùng Buy [${bull_ob_bot:,.2f} - ${bull_ob_top:,.2f}] khoảng {abs(current_gold - bull_ob_top):.1f} giá. Chưa chạm hỗ trợ, đứng ngoài quan sát!"
            elif not m15_struct['has_bull_bos']:
                confirm_badge = "⏳ ĐÃ VÀO VÙNG HỖ TRỢ - CHỜ M15 PHÁ VỠ CẤU TRÚC (TRÁNH BẮT DAO RƠI)"
                action_advice = f"Giá Vàng đang phản ứng tại Vùng Buy. M15 chưa đảo chiều tăng (chưa vượt đỉnh ${m15_struct['choch_bull_level']:,.2f}). Đứng ngoài quan sát, tuyệt đối không bắt dao rơi!"
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

def handle_gold(chat_id=None):
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
• <b>Cách đánh:</b> Chờ giá hồi lên chạm vùng này ──> Nến M5 rút râu từ chối + Kích Volume thì SELL!
👉 <b>Entry Sell:</b> <code>${plan['sell_entry']:,.2f}</code>
🛡️ <b>Stop Loss:</b> <code>${plan['sell_sl']:,.2f}</code> (~{plan['sell_risk']:,.1f} Giá)
🎯 <b>TP1 (Ăn {plan['sell_risk']*1.2:,.1f} Giá | Chốt 50% & Dời Hoà):</b> <code>${plan['sell_tp1']:,.2f}</code>
🎯 <b>TP2 (Ăn {plan['sell_risk']*2.5:,.1f} Giá):</b> <code>${plan['sell_tp2']:,.2f}</code>

━━━━━━━━━━━━━━━━━━
🟢 <b>2. VÙNG CANH BUY (Hỗ Trợ H1):</b>
• <b>Vùng giá:</b> <code>[${plan['bull_ob_bot']:,.2f} - ${plan['bull_ob_top']:,.2f}]</code>
• <b>Cách đánh:</b> Chờ giá đạp về chạm vùng này ──> Nến M5 rút chân đẩy lên + Kích Volume thì BUY!
👉 <b>Entry Buy:</b> <code>${plan['buy_entry']:,.2f}</code>
🛡️ <b>Stop Loss:</b> <code>${plan['buy_sl']:,.2f}</code> (~{plan['buy_risk']:,.1f} Giá)
🎯 <b>TP1 (Ăn {plan['buy_risk']*1.2:,.1f} Giá | Chốt 50% & Dời Hoà):</b> <code>${plan['buy_tp1']:,.2f}</code>
🎯 <b>TP2 (Ăn {plan['buy_risk']*2.5:,.1f} Giá):</b> <code>${plan['buy_tp2']:,.2f}</code>

━━━━━━━━━━━━━━━━━━
🧠 <b>TRẠNG THÁI HIỆN TẠI:</b>
• <b>Tín hiệu vào lệnh:</b> <b>{plan['confirm_badge']}</b>
• <b>Cấu trúc M15:</b> {plan['m15_status']}
• <b>Nhận định:</b> {plan['action_advice']}
━━━━━━━━━━━━━━━━━━
<i>🛡️ Quản lý vốn MT5: Rủi ro tối đa 2% ($40.0 trên tài khoản $2,000 ~ 0.02-0.04 lot).</i>"""
        send_telegram(text, reply_markup=get_main_keyboard(), target_chat_id=chat_id)
    except Exception as e:
        send_telegram(f"Lỗi phân tích Vàng: {e}", reply_markup=get_main_keyboard(), target_chat_id=chat_id)

# ==========================================
# 3. TUYỆT CHIÊU H4 LƯỠNG LỰ: BREAKOUT BUY STOP / SELL STOP
# ==========================================
def calculate_h4_breakout_plan(symbol='BTCUSDT', is_gold=False):
    """
    Tính toán Tuyệt Chiêu H4 Lưỡng Lự (Breakout Buy Stop & Sell Stop):
    - Tự động nhận diện nến Doji, Inside Bar, Con Xoay Spinning Top khung H4
    - Xác định Hộp Nén H4 [Low - High] và điểm Equilibrium 50%
    - Thiết lập Entry Buy Stop, Sell Stop, SL, TP1 (R:R 1:1.5), TP2 (R:R 1:3.0)
    """
    try:
        delta = 0.0
        if is_gold:
            # Đồng bộ giá Vàng theo OANDA:XAUUSD
            plan_gold = calculate_gold_h4_plan()
            curr_gold_ref = plan_gold['current_price']
            url = 'https://api.bybit.com/v5/market/kline?category=linear&symbol=XAUUSDT&interval=240&limit=5'
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=10) as resp:
                klines = json.loads(resp.read().decode())['result']['list']
            bybit_close = float(klines[0][4])
            delta = curr_gold_ref - bybit_close
            curr_p = curr_gold_ref
        else:
            url = 'https://api.bybit.com/v5/market/kline?category=linear&symbol=BTCUSDT&interval=240&limit=5'
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=10) as resp:
                klines = json.loads(resp.read().decode())['result']['list']
            curr_p = float(klines[0][4])

        c0, c1, c2 = klines[0], klines[1], klines[2]
        
        h1 = float(c1[2]) + delta
        l1 = float(c1[3]) + delta
        o1 = float(c1[1]) + delta
        cl1 = float(c1[4]) + delta
        
        h2 = float(c2[2]) + delta
        l2 = float(c2[3]) + delta
        
        rng1 = h1 - l1
        body1 = abs(cl1 - o1)
        up_wick1 = h1 - max(o1, cl1)
        low_wick1 = min(o1, cl1) - l1
        
        is_inside = (h1 <= h2) and (l1 >= l2)
        is_doji = (body1 <= rng1 * 0.45) and (up_wick1 >= rng1 * 0.18) and (low_wick1 >= rng1 * 0.18)
        is_spinning = (body1 <= rng1 * 0.5) and (up_wick1 >= rng1 * 0.15) and (low_wick1 >= rng1 * 0.15)
        
        if is_inside:
            pattern = "Nến Inside Bar (Nén Trong Nến Trước)"
            note = "Sức nén cực mạnh, thị trường sắp bùng nổ theo hướng phá vỡ!"
        elif is_doji:
            pattern = "Nến Doji / Con Xoay (Lưỡng Lự Cực Độ)"
            note = "Phe Mua và Bán giằng co bất phân thắng bại, râu nến 2 đầu cân bằng."
        elif is_spinning:
            pattern = "Nến Lưỡng Lự Spinning Top"
            note = "Biên độ nén hẹp, phe Mua và Bán đang tích lũy năng lượng."
        else:
            pattern = "Hộp Biên Độ H4 Gần Nhất"
            note = "Vùng tích lũy biên độ nến H4 trước khi tạo xu hướng mới."

        dec = 2 if is_gold else 1
        unit = "Giá" if is_gold else "USD"
        buffer = 0.6 if is_gold else 50.0

        box_high = round(h1, dec)
        box_low = round(l1, dec)
        box_mid = round((box_high + box_low) / 2.0, dec)
        box_rng = round(box_high - box_low, dec)

        # Kịch bản BUY STOP (Vượt đỉnh H4)
        buy_entry = round(box_high + buffer, dec)
        if is_gold:
            buy_sl = round(box_low - 0.5, dec) if box_rng <= 15.0 else round(box_mid - 0.5, dec)
        else:
            buy_sl = round(box_low - 50.0, dec) if box_rng <= 1200.0 else round(box_mid - 50.0, dec)
        buy_risk = round(buy_entry - buy_sl, dec)
        buy_tp1 = round(buy_entry + (buy_risk * 1.5), dec)
        buy_tp2 = round(buy_entry + (buy_risk * 3.0), dec)

        # Kịch bản SELL STOP (Sập đáy H4)
        sell_entry = round(box_low - buffer, dec)
        if is_gold:
            sell_sl = round(box_high + 0.5, dec) if box_rng <= 15.0 else round(box_mid + 0.5, dec)
        else:
            sell_sl = round(box_high + 50.0, dec) if box_rng <= 1200.0 else round(box_mid + 50.0, dec)
        sell_risk = round(sell_sl - sell_entry, dec)
        sell_tp1 = round(sell_entry - (sell_risk * 1.5), dec)
        sell_tp2 = round(sell_entry - (sell_risk * 3.0), dec)

        # Trạng thái giá hiện tại so với Hộp H4
        if curr_p >= box_high:
            status = "🚀 ĐÃ BÙNG NỔ VƯỢT ĐỈNH H4"
            status_desc = f"Giá (${curr_p:,.{dec}f}) đã phá vỡ đỉnh H4 (${box_high:,.{dec}f}). Nếu đã khớp Buy Stop, gồng tiếp về TP1/TP2!"
        elif curr_p <= box_low:
            status = "📉 ĐÃ SẬP THỦNG ĐÁY H4"
            status_desc = f"Giá (${curr_p:,.{dec}f}) đã phá vỡ đáy H4 (${box_low:,.{dec}f}). Nếu đã khớp Sell Stop, gồng tiếp về TP1/TP2!"
        else:
            status = "⏳ ĐANG NÉN TRONG HỘP H4 (CÀI SẴN 2 ĐẦU STOP)"
            status_desc = f"Giá (${curr_p:,.{dec}f}) đang tích lũy nén trong hộp H4 [${box_low:,.{dec}f} - ${box_high:,.{dec}f}]. Thời điểm vàng để cài sẵn cả 2 đầu!"

        return {
            'symbol': 'XAUUSD' if is_gold else 'BTCUSDT',
            'is_gold': is_gold,
            'curr_p': curr_p,
            'pattern': pattern,
            'note': note,
            'box_high': box_high,
            'box_low': box_low,
            'box_mid': box_mid,
            'box_rng': box_rng,
            'buy_entry': buy_entry,
            'buy_sl': buy_sl,
            'buy_risk': buy_risk,
            'buy_tp1': buy_tp1,
            'buy_tp2': buy_tp2,
            'sell_entry': sell_entry,
            'sell_sl': sell_sl,
            'sell_risk': sell_risk,
            'sell_tp1': sell_tp1,
            'sell_tp2': sell_tp2,
            'status': status,
            'status_desc': status_desc,
            'dec': dec,
            'unit': unit
        }
    except Exception as e:
        print(f"Lỗi calculate_h4_breakout_plan: {e}")
        raise e

def handle_h4_breakout(chat_id=None):
    try:
        p_gold = calculate_h4_breakout_plan(symbol='XAUUSD', is_gold=True)
        p_btc = calculate_h4_breakout_plan(symbol='BTCUSDT', is_gold=False)
        
        text = f"""⚡ <b>[TUYỆT CHIÊU BREAKOUT NẾN H4 LƯỠNG LỰ]</b> ⚡
━━━━━━━━━━━━━━━━━━
💡 <b>Nguyên lý cốt lõi:</b> Khi cây nến H4 xuất hiện dạng <i>Lưỡng Lự (Doji, Con Xoay, Inside Bar)</i>, thị trường tích lũy nén giá cực độ. Phá vỡ theo hướng nào sẽ bung sóng cực mạnh theo hướng đó!

🥇 <b>1. VÀNG (OANDA:XAUUSD - Chuẩn MT5)</b>
• 💰 Giá hiện tại: <code>${p_gold['curr_p']:,.2f}</code>
• 📦 Hình thái H4: <b>{p_gold['pattern']}</b>
• 🧱 Hộp nén H4: <code>[${p_gold['box_low']:,.2f} - ${p_gold['box_high']:,.2f}]</code> (Biên độ {p_gold['box_rng']} Giá)
• ⚖️ Cân bằng 50%: <code>${p_gold['box_mid']:,.2f}</code>
• 🎯 Trạng thái: <b>{p_gold['status']}</b>

🟢 <b>KỊCH BẢN BUY STOP (Phá Đỉnh H4):</b>
👉 <b>Entry Buy Stop:</b> <code>${p_gold['buy_entry']:,.2f}</code>
🛡️ <b>Stop Loss:</b> <code>${p_gold['buy_sl']:,.2f}</code> (~{p_gold['buy_risk']} Giá)
🎯 <b>TP1 (R:R 1:1.5 | Chốt 50% & Dời Hoà):</b> <code>${p_gold['buy_tp1']:,.2f}</code>
🎯 <b>TP2 (R:R 1:3.0 | Gồng Trọn Sóng Bung):</b> <code>${p_gold['buy_tp2']:,.2f}</code>

🔴 <b>KỊCH BẢN SELL STOP (Phá Đáy H4):</b>
👉 <b>Entry Sell Stop:</b> <code>${p_gold['sell_entry']:,.2f}</code>
🛡️ <b>Stop Loss:</b> <code>${p_gold['sell_sl']:,.2f}</code> (~{p_gold['sell_risk']} Giá)
🎯 <b>TP1 (R:R 1:1.5 | Chốt 50% & Dời Hoà):</b> <code>${p_gold['sell_tp1']:,.2f}</code>
🎯 <b>TP2 (R:R 1:3.0 | Gồng Trọn Sóng Bung):</b> <code>${p_gold['sell_tp2']:,.2f}</code>

━━━━━━━━━━━━━━━━━━
👑 <b>2. BITCOIN (BTCUSDT)</b>
• 💰 Giá hiện tại: <code>${p_btc['curr_p']:,.1f}</code>
• 📦 Hình thái H4: <b>{p_btc['pattern']}</b>
• 🧱 Hộp nén H4: <code>[${p_btc['box_low']:,.1f} - ${p_btc['box_high']:,.1f}]</code> (Biên độ {p_btc['box_rng']:,.1f} USD)
• ⚖️ Cân bằng 50%: <code>${p_btc['box_mid']:,.1f}</code>
• 🎯 Trạng thái: <b>{p_btc['status']}</b>

🟢 <b>KỊCH BẢN BUY STOP (Phá Đỉnh H4):</b>
👉 <b>Entry Buy Stop:</b> <code>${p_btc['buy_entry']:,.1f}</code>
🛡️ <b>Stop Loss:</b> <code>${p_btc['buy_sl']:,.1f}</code> (~{p_btc['buy_risk']:,.1f} USD)
🎯 <b>TP1 (R:R 1:1.5 | Chốt 50% & Dời Hoà):</b> <code>${p_btc['buy_tp1']:,.1f}</code>
🎯 <b>TP2 (R:R 1:3.0 | Gồng Trọn Sóng Bung):</b> <code>${p_btc['buy_tp2']:,.1f}</code>

🔴 <b>KỊCH BẢN SELL STOP (Phá Đáy H4):</b>
👉 <b>Entry Sell Stop:</b> <code>${p_btc['sell_entry']:,.1f}</code>
🛡️ <b>Stop Loss:</b> <code>${p_btc['sell_sl']:,.1f}</code> (~{p_btc['sell_risk']:,.1f} USD)
🎯 <b>TP1 (R:R 1:1.5 | Chốt 50% & Dời Hoà):</b> <code>${p_btc['sell_tp1']:,.1f}</code>
🎯 <b>TP2 (R:R 1:3.0 | Gồng Trọn Sóng Bung):</b> <code>${p_btc['sell_tp2']:,.1f}</code>

━━━━━━━━━━━━━━━━━━
🧠 <b>CHIẾN THUẬT ĐẶT LỆNH 2 ĐẦU:</b>
1. Khi giá đang nén trong hộp H4: Cài sẵn đồng thời cả 2 lệnh chờ <b>BUY STOP</b> và <b>SELL STOP</b>.
2. <b>Khi 1 đầu khớp lệnh:</b> Ngay lập tức <b>HỦY</b> lệnh chờ ở đầu còn lại!
3. <b>Khi giá đạt mốc TP1:</b> Chốt 50% khối lượng, đồng thời dời Stop Loss về giá Entry (Hoà vốn - Risk Free) để gồng tiếp về TP2!"""
        send_telegram(text, reply_markup=get_main_keyboard(), target_chat_id=chat_id)
    except Exception as e:
        send_telegram(f"Lỗi kiểm tra H4 Breakout: {e}", reply_markup=get_main_keyboard(), target_chat_id=chat_id)

# ==========================================
# 2.3 TUYỆT CHIÊU SCALPING VOLUME PROFILE M5 & TEST RÂU NẾN (HVN REBOUND)
# ==========================================
def compute_volume_profile(klines_desc, bins_count=50):
    """Tính Fixed Range Volume Profile (FRVP) phân bổ khối lượng theo mức giá"""
    try:
        klines = list(reversed(klines_desc))
        lows = [float(k[3]) for k in klines]
        highs = [float(k[2]) for k in klines]
        min_p = min(lows)
        max_p = max(highs)
        if max_p == min_p:
            return None
        bin_size = (max_p - min_p) / bins_count
        bins = [0.0] * bins_count
        total_vol = 0.0
        for k in klines:
            l, h = float(k[3]), float(k[2])
            v = float(k[5])
            total_vol += v
            start_bin = max(0, min(bins_count - 1, int((l - min_p) / bin_size)))
            end_bin = max(0, min(bins_count - 1, int((h - min_p) / bin_size)))
            num_bins = end_bin - start_bin + 1
            vol_per_bin = v / num_bins
            for b in range(start_bin, end_bin + 1):
                bins[b] += vol_per_bin

        max_bin_idx = bins.index(max(bins))
        poc_price = min_p + (max_bin_idx + 0.5) * bin_size

        va_target = total_vol * 0.70
        va_vol = bins[max_bin_idx]
        up_idx, down_idx = max_bin_idx, max_bin_idx
        while va_vol < va_target and (up_idx < bins_count - 1 or down_idx > 0):
            next_up = bins[up_idx + 1] if up_idx < bins_count - 1 else 0
            next_down = bins[down_idx - 1] if down_idx > 0 else 0
            if next_up >= next_down and up_idx < bins_count - 1:
                up_idx += 1
                va_vol += bins[up_idx]
            elif down_idx > 0:
                down_idx -= 1
                va_vol += bins[down_idx]
            else:
                break

        val_price = min_p + down_idx * bin_size
        vah_price = min_p + (up_idx + 1) * bin_size

        hvns = []
        for i in range(1, bins_count - 1):
            if bins[i] > bins[i-1] and bins[i] > bins[i+1] and bins[i] >= 0.45 * bins[max_bin_idx]:
                p = min_p + (i + 0.5) * bin_size
                hvns.append(round(p, 2))

        return {
            'poc': round(poc_price, 2),
            'val': round(val_price, 2),
            'vah': round(vah_price, 2),
            'hvns': hvns,
            'min_p': round(min_p, 2),
            'max_p': round(max_p, 2)
        }
    except Exception:
        return None

def analyze_scalp_vp_plan(asset='GOLD'):
    """
    Phân tích setup Volume Profile Ngày Hôm Trước (Yesterday's VP) & Hôm Nay:
    - Cơ chế L-Shape hôm trước: yVAL & yPOC tụ đáy -> M5 phản ứng giá -> Target xoay trục về yVAH!
    - Cơ chế P-Shape hôm trước: yVAH & yPOC tụ đỉnh -> M5 phản ứng giá -> Target xoay trục về yVAL!
    - Đồng thời theo dõi Developing VP & Daily Open (DO) của hôm nay.
    """
    symbol = 'XAUUSDT' if asset == 'GOLD' else 'BTCUSDT'
    url = f'https://api.bybit.com/v5/market/kline?category=linear&symbol={symbol}&interval=5&limit=600'
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=10) as r:
        klines = json.loads(r.read().decode())['result']['list']

    curr_p = float(klines[0][4])
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    
    # 1. Xác định khung thời gian phiên Hôm Nay và Hôm Qua
    if asset == 'GOLD':
        # OANDA / Forex phiên ngày mở lúc 22:00 UTC (17:00 New York)
        if now_utc.hour >= 22:
            today_start = datetime.datetime(now_utc.year, now_utc.month, now_utc.day, 22, 0, 0, tzinfo=datetime.timezone.utc)
        else:
            prev_1 = now_utc - datetime.timedelta(days=1)
            today_start = datetime.datetime(prev_1.year, prev_1.month, prev_1.day, 22, 0, 0, tzinfo=datetime.timezone.utc)
    else:
        # Crypto phiên ngày mở lúc 00:00 UTC
        today_start = datetime.datetime(now_utc.year, now_utc.month, now_utc.day, 0, 0, 0, tzinfo=datetime.timezone.utc)

    yesterday_start = today_start - datetime.timedelta(days=1)
    today_start_ts = int(today_start.timestamp() * 1000)
    yesterday_start_ts = int(yesterday_start.timestamp() * 1000)

    yesterday_klines = [k for k in klines if yesterday_start_ts <= int(k[0]) < today_start_ts]
    session_klines = [k for k in klines if int(k[0]) >= today_start_ts]
    if len(session_klines) < 20:
        session_klines = klines[:60]

    # 2. Volume Profile Hôm Nay (Developing VP)
    daily_open = float(session_klines[-1][1])
    hod = max([float(k[2]) for k in session_klines])
    lod = min([float(k[3]) for k in session_klines])
    vp = compute_volume_profile(session_klines)
    if not vp:
        return None

    # 3. Volume Profile Ngày Hôm Trước (Yesterday's VP)
    y_vp = compute_volume_profile(yesterday_klines) if yesterday_klines else vp
    y_poc = y_vp['poc']
    y_val = y_vp['val']
    y_vah = y_vp['vah']
    y_range = y_vah - y_val

    is_l_shape = (abs(y_poc - y_val) / y_range <= 0.35) if y_range > 0 else False
    is_p_shape = (abs(y_vah - y_poc) / y_range <= 0.35) if y_range > 0 else False

    if is_l_shape:
        y_shape = "L-SHAPE (TỤ ĐÁY yVAL & yPOC)"
        y_shape_desc = f"Hôm trước tích lũy khối lượng lớn ở đáy [${y_val:,.1f} - ${y_poc:,.1f}]. Kỳ vọng nảy tìm về yVAH ${y_vah:,.1f}!"
    elif is_p_shape:
        y_shape = "P-SHAPE (TỤ ĐỈNH yVAH & yPOC)"
        y_shape_desc = f"Hôm trước phân phối khối lượng lớn ở đỉnh [${y_poc:,.1f} - ${y_vah:,.1f}]. Kỳ vọng rơi tìm về yVAL ${y_val:,.1f}!"
    else:
        y_shape = "D-SHAPE (CÂN BẰNG GIỮA)"
        y_shape_desc = f"Hôm trước tích lũy cân bằng quanh yPOC ${y_poc:,.1f}."

    # Xác định Daily Bias theo giá mở cửa ngày (Daily Open)
    if curr_p >= daily_open:
        daily_bias = f"🟢 BULLISH (Giá trên Daily Open ${daily_open:,.1f})"
    else:
        daily_bias = f"🔴 BEARISH (Giá dưới Daily Open ${daily_open:,.1f})"

    # 4. Tìm cây nến M5 có râu từ chối (Rejection Wick) gần nhất trong 5 nến gần đây
    best_rejection = None
    for i in range(min(5, len(session_klines))):
        k = session_klines[i]
        o, h, l, c = float(k[1]), float(k[2]), float(k[3]), float(k[4])
        rng = h - l
        if rng > 0:
            lw = min(o, c) - l
            uw = h - max(o, c)
            lw_pct = (lw / rng) * 100
            uw_pct = (uw / rng) * 100
            if lw_pct >= 35 and (best_rejection is None or lw_pct > best_rejection['pct']):
                best_rejection = {'type': 'BULL', 'low': l, 'high': h, 'pct': lw_pct, 'candle_idx': i}
            elif uw_pct >= 35 and (best_rejection is None or uw_pct > best_rejection['pct']):
                best_rejection = {'type': 'BEAR', 'low': l, 'high': h, 'pct': uw_pct, 'candle_idx': i}

    # 5. Xác định Hướng Giao Dịch:
    # Ưu tiên số 1: Cơ chế Xoay Trục Hôm Trước (L-Shape nảy về yVAH hoặc P-Shape dội về yVAL)
    # Ưu tiên số 2: Phản ứng nến M5 tại dPOC / dVAL / dVAH hôm nay
    if is_l_shape and curr_p <= y_vah:
        is_buy = True
        sig = 'BUY ROTATION (Tụ Đáy yVAL/yPOC Hôm Trước ➔ Tìm Về yVAH)'
    elif is_p_shape and curr_p >= y_val:
        is_buy = False
        sig = 'SELL ROTATION (Tụ Đỉnh yVAH/yPOC Hôm Trước ➔ Tìm Về yVAL)'
    elif best_rejection:
        is_buy = (best_rejection['type'] == 'BULL')
        sig = 'BUY SCALPING (Nảy Hỗ Trợ dPOC / dVAL)' if is_buy else 'SELL SCALPING (Dội Kháng Cự dPOC / dVAH)'
    else:
        is_buy = (curr_p >= daily_open)
        sig = 'BUY SCALPING (Nảy Hỗ Trợ dPOC / dVAL)' if is_buy else 'SELL SCALPING (Dội Kháng Cự dPOC / dVAH)'

    if asset == 'GOLD':
        if is_buy:
            entry = round(best_rejection['low'] + 1.2, 2) if (best_rejection and abs(curr_p - best_rejection['low']) < 6.0) else round(max(vp['poc'], vp['val']), 2)
            # SL chuyên nghiệp: Phải bảo vệ dưới toàn bộ vùng đáy tích lũy yVAL / LOD với đệm an toàn 3-4 giá
            if is_l_shape:
                base_bottom = min(y_val, lod)
                sl = round(min(base_bottom - 3.5, entry - 10.0), 2)
            elif best_rejection:
                sl = round(min(best_rejection['low'] - 3.5, entry - 9.0), 2)
            else:
                sl = round(min(vp['val'], y_val) - 3.5, 2)
            
            risk = round(abs(entry - sl), 2)
            # Khống chế SL chuẩn Volume Profile: từ 8.0 đến 16.0 giá (tránh bị bóp râu M5 cắn SL oan)
            if risk < 8.0:
                risk = 9.0
                sl = round(entry - risk, 2)
            elif risk > 18.0:
                risk = 16.0
                sl = round(entry - risk, 2)

            target_up = y_vah if is_l_shape else max(vp['vah'], hod)
            tp1 = round(entry + max(risk * 1.3, 10.0), 2)
            tp2 = round(max(target_up, entry + risk * 2.5), 2)
        else:
            entry = round(best_rejection['high'] - 1.2, 2) if (best_rejection and abs(curr_p - best_rejection['high']) < 6.0) else round(min(vp['poc'], vp['vah']), 2)
            # SL chuyên nghiệp: Phải bảo vệ trên toàn bộ vùng đỉnh phân phối yVAH / HOD với đệm an toàn 3-4 giá
            if is_p_shape:
                base_top = max(y_vah, hod)
                sl = round(max(base_top + 3.5, entry + 10.0), 2)
            elif best_rejection:
                sl = round(max(best_rejection['high'] + 3.5, entry + 9.0), 2)
            else:
                sl = round(max(vp['vah'], y_vah) + 3.5, 2)

            risk = round(abs(sl - entry), 2)
            if risk < 8.0:
                risk = 9.0
                sl = round(entry + risk, 2)
            elif risk > 18.0:
                risk = 16.0
                sl = round(entry + risk, 2)

            target_down = y_val if is_p_shape else min(vp['val'], lod)
            tp1 = round(entry - max(risk * 1.3, 10.0), 2)
            tp2 = round(min(target_down, entry - risk * 2.5), 2)
    else: # BTC
        if is_buy:
            entry = round(best_rejection['low'] + 50.0, 1) if (best_rejection and abs(curr_p - best_rejection['low']) < 300.0) else round(max(vp['poc'], vp['val']), 1)
            if is_l_shape:
                base_bottom = min(y_val, lod)
                sl = round(min(base_bottom - 150.0, entry - 450.0), 1)
            elif best_rejection:
                sl = round(min(best_rejection['low'] - 150.0, entry - 450.0), 1)
            else:
                sl = round(min(vp['val'], y_val) - 150.0, 1)

            risk = round(abs(entry - sl), 1)
            if risk < 400.0:
                risk = 450.0
                sl = round(entry - risk, 1)
            elif risk > 900.0:
                risk = 800.0
                sl = round(entry - risk, 1)

            target_up = y_vah if is_l_shape else max(vp['vah'], hod)
            tp1 = round(entry + max(risk * 1.3, 500.0), 1)
            tp2 = round(max(target_up, entry + risk * 2.5), 1)
        else:
            entry = round(best_rejection['high'] - 50.0, 1) if (best_rejection and abs(curr_p - best_rejection['high']) < 300.0) else round(min(vp['poc'], vp['vah']), 1)
            if is_p_shape:
                base_top = max(y_vah, hod)
                sl = round(max(base_top + 150.0, entry + 450.0), 1)
            elif best_rejection:
                sl = round(max(best_rejection['high'] + 150.0, entry + 450.0), 1)
            else:
                sl = round(max(vp['vah'], y_vah) + 150.0, 1)

            risk = round(abs(sl - entry), 1)
            if risk < 400.0:
                risk = 450.0
                sl = round(entry + risk, 1)
            elif risk > 900.0:
                risk = 800.0
                sl = round(entry + risk, 1)

            target_down = y_val if is_p_shape else min(vp['val'], lod)
            tp1 = round(entry - max(risk * 1.3, 500.0), 1)
            tp2 = round(min(target_down, entry - risk * 2.5), 1)

    wick_str = f"Nến M5 test râu {best_rejection['pct']:.1f}% từ chối giá" if best_rejection else "Giá dao động quanh mốc Volume Profile"

    return {
        'asset': asset,
        'symbol': symbol,
        'curr_p': curr_p,
        'daily_open': daily_open,
        'hod': hod,
        'lod': lod,
        'daily_bias': daily_bias,
        'poc': vp['poc'],
        'val': vp['val'],
        'vah': vp['vah'],
        'y_poc': y_poc,
        'y_val': y_val,
        'y_vah': y_vah,
        'y_shape': y_shape,
        'y_shape_desc': y_shape_desc,
        'is_l_shape': is_l_shape,
        'is_p_shape': is_p_shape,
        'signal': sig,
        'is_buy': is_buy,
        'entry': entry,
        'sl': sl,
        'risk': risk,
        'tp1': tp1,
        'tp2': tp2,
        'wick_info': wick_str,
        'best_rejection': best_rejection,
        'is_rejection_fresh': (best_rejection is not None and best_rejection['candle_idx'] <= 1),
        'dist_to_entry': round(abs(curr_p - entry), 2),
        'candles_count': len(session_klines)
    }

def handle_vp_scalping(chat_id=None):
    """Báo cáo phân tích Scalping nảy Volume Profile Ngày Hôm Trước & Hôm Nay (DVP - OANDA Daily Open) & Test râu M5"""
    send_telegram("⏳ <i>Đang tính toán Volume Profile Ngày Hôm Trước (Yesterday VP) & Hôm Nay (OANDA / UTC)...</i>", target_chat_id=chat_id)
    try:
        now = time.time()
        cache = PLAN_CACHE.get('VP_SCALP')
        if cache and cache.get('data') and (now - cache['time'] < 180):
            p_gold, p_btc = cache['data']['gold'], cache['data']['btc']
        else:
            p_gold = analyze_scalp_vp_plan('GOLD')
            p_btc = analyze_scalp_vp_plan('BTC')
            PLAN_CACHE['VP_SCALP'] = {'time': now, 'data': {'gold': p_gold, 'btc': p_btc}}

        g_emoji = "🟢" if p_gold['is_buy'] else "🔴"
        b_emoji = "🟢" if p_btc['is_buy'] else "🔴"

        msg = f"""🎯 <b>TUYỆT CHIÊU VOLUME PROFILE NGÀY HÔM TRƯỚC (XOAY TRỤC VAL ➔ VAH)</b>
━━━━━━━━━━━━━━━━━━
🥇 <b>1. VÀNG (XAUUSD - SÀN OANDA CHUẨN):</b>
• 💰 Giá hiện tại: <code>${p_gold['curr_p']:,.2f}</code>
• 🌅 <b>Daily Open:</b> <code>${p_gold['daily_open']:,.2f}</code> | 🧭 <b>Bias:</b> {p_gold['daily_bias']}

🏛️ <b>VOLUME PROFILE HÔM TRƯỚC: {p_gold['y_shape']}</b>
• 📍 <b>yPOC:</b> <code>${p_gold['y_poc']:,.2f}</code> | 🟢 <b>yVAL:</b> <code>${p_gold['y_val']:,.2f}</code> | 🔴 <b>yVAH:</b> <code>${p_gold['y_vah']:,.2f}</code>
• 💡 <i>{p_gold['y_shape_desc']}</i>

📊 <b>Volume Profile Hôm Nay:</b>
• dPOC: <code>${p_gold['poc']:,.2f}</code> | dVAL: <code>${p_gold['val']:,.2f}</code> | dVAH: <code>${p_gold['vah']:,.2f}</code>
• ⚡ <b>Hành động giá M5:</b> <i>{p_gold['wick_info']}</i>

🚀 <b>KẾ HOẠCH VÀO LỆNH: {g_emoji} {p_gold['signal']}</b>
👉 <b>Điểm vào (Entry):</b> <code>${p_gold['entry']:,.2f}</code>
🛡️ <b>Cắt lỗ (SL Bóp Chân Râu M5):</b> <code>${p_gold['sl']:,.2f}</code> (~{p_gold['risk']} Giá)
🎯 <b>TP1 (Chốt 50% | Giữa Đường):</b> <code>${p_gold['tp1']:,.2f}</code>
🎯 <b>TP2 (Target Mục Tiêu Chính):</b> <code>${p_gold['tp2']:,.2f}</code>

━━━━━━━━━━━━━━━━━━
👑 <b>2. BITCOIN (BTCUSDT - 00:00 UTC):</b>
• 💰 Giá hiện tại: <code>${p_btc['curr_p']:,.1f}</code>
• 🌅 <b>Daily Open:</b> <code>${p_btc['daily_open']:,.1f}</code> | 🧭 <b>Bias:</b> {p_btc['daily_bias']}

🏛️ <b>VOLUME PROFILE HÔM TRƯỚC: {p_btc['y_shape']}</b>
• 📍 <b>yPOC:</b> <code>${p_btc['y_poc']:,.1f}</code> | 🟢 <b>yVAL:</b> <code>${p_btc['y_val']:,.1f}</code> | 🔴 <b>yVAH:</b> <code>${p_btc['y_vah']:,.1f}</code>
• 💡 <i>{p_btc['y_shape_desc']}</i>

📊 <b>Volume Profile Hôm Nay:</b>
• dPOC: <code>${p_btc['poc']:,.1f}</code> | dVAL: <code>${p_btc['val']:,.1f}</code> | dVAH: <code>${p_btc['vah']:,.1f}</code>
• ⚡ <b>Hành động giá M5:</b> <i>{p_btc['wick_info']}</i>

🚀 <b>KẾ HOẠCH VÀO LỆNH: {b_emoji} {p_btc['signal']}</b>
👉 <b>Điểm vào (Entry):</b> <code>${p_btc['entry']:,.1f}</code>
🛡️ <b>Cắt lỗ (SL Bóp Chân Râu M5):</b> <code>${p_btc['sl']:,.1f}</code> (~{p_btc['risk']:,.1f} USD)
🎯 <b>TP1 (Chốt 50% | Giữa Đường):</b> <code>${p_btc['tp1']:,.1f}</code>
🎯 <b>TP2 (Target Mục Tiêu Chính):</b> <code>${p_btc['tp2']:,.1f}</code>

━━━━━━━━━━━━━━━━━━
🧠 <b>BẢN CHẤT XOAY TRỤC VAL ➔ VAH:</b>
1. <b>Khi yVAL & yPOC tụ ở đáy (L-Shape):</b> Phe mua hấp thụ cạn kiệt lực bán. Nến M5 có phản ứng giá ➔ Giá sẽ phóng như tên lửa tìm về <b>yVAH</b>!
2. <b>Khi yVAH & yPOC tụ ở đỉnh (P-Shape):</b> Phe bán phân phối chặn đầu. Nến M5 từ chối ➔ Giá sẽ rơi tìm về <b>yVAL</b>!"""
        send_telegram(msg, reply_markup=get_main_keyboard(), target_chat_id=chat_id)
    except Exception as e:
        send_telegram(f"⚠️ Lỗi tính toán Scalping Volume Profile: {e}", reply_markup=get_main_keyboard(), target_chat_id=chat_id)

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

def handle_scan(mode='long', chat_id=None):
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
🛡️ <b>Cắt lỗ (SL):</b> <code>{r['sl']}</code> (-{r['sl_pct']}%)
🎯 <b>Chốt lời 1 (TP1):</b> <code>{r['tp1']}</code> [R:R 1:2]
🎯 <b>Chốt lời 2 (TP2):</b> <code>{r['tp2']}</code> [R:R 1:3.5]"""
            
        msg += "\n━━━━━━━━━━━━━━━━━━\n<i>💡 Điểm vào lệnh được neo cố định theo cản nến trong phiên để bạn kịp đặt lệnh trên sàn!</i>"
        send_telegram(msg, reply_markup=get_main_keyboard(), target_chat_id=chat_id)
    except Exception as e:
        send_telegram(f"Lỗi scan: {e}", reply_markup=get_main_keyboard(), target_chat_id=chat_id)

# ==========================================
# 3.2 SĂN COIN RÁC / ALTCOIN BÙNG NỔ (VOLUME > 100M USD, SL 5-9%, LỰC MUA CHỦ ĐỘNG)
# ==========================================
def scan_meme_breakout_coins(limit=3):
    """
    Săn Coin Rác / Altcoin bùng nổ có Volume khủng (> 100M USD):
    - Tiêu chí thanh khoản: Volume 24h >= 100M USD (hoặc >= 70M USD nếu thị trường đi ngang).
    - Tiêu chí dòng tiền: Volume Mua Vào Chủ Động (Momentum Breakout), tuyệt đối KHÔNG PHẢI BẮT ĐÁY (Buy the dip).
    - Nến H1: Nến xanh đẩy hoặc nằm trên SMA6, biến động 24h dương (> 0.5%).
    - Stop Loss: Khống chế trong biên độ 5.0% - 9.0% (bảo vệ dưới đáy nến H1).
    - Take Profit: TP1 +8% đến +12% (R:R 1:1.5, chốt 50% & dời hoà), TP2 +18% đến +27% (R:R 1:3).
    """
    now = time.time()
    if PLAN_CACHE.get('MEME_COINS', {}).get('data') and (now - PLAN_CACHE['MEME_COINS']['time'] < 900):
        return PLAN_CACHE['MEME_COINS']['data']

    TRADFI_EXCLUDE = {
        'SOXLUSDT', 'NVDAUSDT', 'SOXSUSDT', 'SNDKUSDT', 'XAUUSDT', 'XAGUSDT', 
        'SKHYNIXUSDT', 'MUUSDT', 'QQQUSDT', 'KORUUSDT', 'TSLAUSDT', 'AAPLUSDT', 
        'MSFTUSDT', 'AMZNUSDT', 'GOOGLUSDT', 'METAUSDT', 'COINUSDT', 'SPCXUSDT'
    }
    MAJORS_EXCLUDE = {'BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'USDCUSDT'}

    url = 'https://api.bybit.com/v5/market/tickers?category=linear'
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode())
        tickers = data['result']['list']

    candidates = []
    for d in tickers:
        sym = d['symbol']
        if not sym.endswith('USDT'): continue
        if sym in TRADFI_EXCLUDE or sym in MAJORS_EXCLUDE: continue
        
        vol_usd = float(d.get('turnover24h', 0))
        change_pct = float(d.get('price24hPcnt', 0)) * 100.0
        
        # Tiêu chuẩn: Vol >= 70M USD (ưu tiên >= 100M) và đang có đà bơm (change > 0.5%)
        if vol_usd >= 70_000_000 and change_pct >= 0.5:
            candidates.append({
                'symbol': sym,
                'sym_clean': sym.replace('USDT', '/USDT'),
                'price': float(d['lastPrice']),
                'change_pct': round(change_pct, 2),
                'vol_m': round(vol_usd / 1_000_000, 1),
                'high_24h': float(d['highPrice24h']),
                'low_24h': float(d['lowPrice24h'])
            })

    # Ưu tiên các coin đạt mốc 100M+ và có đà tăng mạnh nhất
    candidates.sort(key=lambda x: (x['vol_m'] >= 100.0, x['change_pct']), reverse=True)
    selected = candidates[:8]
    
    results = []
    for c in selected:
        sym = c['symbol']
        try:
            k_url = f'https://api.bybit.com/v5/market/kline?category=linear&symbol={sym}&interval=60&limit=12'
            k_req = urllib.request.Request(k_url, headers=HEADERS)
            with urllib.request.urlopen(k_req, timeout=5) as r:
                klines = json.loads(r.read().decode())['result']['list']
            
            curr_k = klines[0]
            prev_k = klines[1]
            close_p = float(curr_k[4])
            open_p = float(curr_k[1])
            
            # Kiểm tra Volume Mua Vào Chủ Động (Không phải bắt đáy dao rơi / buy the dip)
            is_bull_candle = (close_p >= open_p) or (float(prev_k[4]) >= float(prev_k[1]))
            closes = [float(k[4]) for k in klines]
            sma6 = sum(closes[:6]) / 6
            if not (is_bull_candle and close_p >= sma6):
                continue
                
            # Tính SL chuẩn 5% - 10% (theo yêu cầu)
            recent_low = min([float(k[3]) for k in klines[:4]])
            raw_sl_pct = ((close_p - recent_low) / close_p) * 100.0
            
            if raw_sl_pct < 5.0:
                sl_pct = 5.8
            elif raw_sl_pct > 9.5:
                sl_pct = 8.5
            else:
                sl_pct = round(raw_sl_pct + 0.8, 1)
                
            sl_price = round(close_p * (1.0 - sl_pct / 100.0), 6 if close_p < 1 else 4)
            tp1_pct = round(sl_pct * 1.5, 1)
            tp1_price = round(close_p * (1.0 + tp1_pct / 100.0), 6 if close_p < 1 else 4)
            tp2_pct = round(sl_pct * 3.0, 1)
            tp2_price = round(close_p * (1.0 + tp2_pct / 100.0), 6 if close_p < 1 else 4)

            vol_label = f"🔥 ${c['vol_m']:.1f}M USD" if c['vol_m'] >= 100.0 else f"⚡ ${c['vol_m']:.1f}M USD"
            
            results.append({
                'symbol': c['sym_clean'],
                'price': close_p,
                'change': c['change_pct'],
                'vol_m': c['vol_m'],
                'vol_label': vol_label,
                'sl_pct': sl_pct,
                'sl_price': sl_price,
                'tp1_pct': tp1_pct,
                'tp1_price': tp1_price,
                'tp2_pct': tp2_pct,
                'tp2_price': tp2_price
            })
            if len(results) >= limit:
                break
        except Exception as e:
            continue

    PLAN_CACHE['MEME_COINS'] = {'time': now, 'data': results}
    return results

def handle_meme_coins(chat_id=None):
    """Báo cáo danh sách Coin Rác / Altcoin bùng nổ có Volume khủng (> 100M USD) & Momentum mua vào"""
    send_telegram("⏳ <i>Đang quét toàn sàn Bybit lọc Coin Rác có Volume > $100M & Lực mua chủ động...</i>", target_chat_id=chat_id)
    try:
        coins = scan_meme_breakout_coins(limit=4)
        if not coins:
            send_telegram("⚠️ Hiện tại chưa có Coin Rác nào đạt đồng thời tiêu chí Volume > $70M-$100M và nến H1 đang có lực mua đẩy. Hãy thử lại sau ít phút!", reply_markup=get_main_keyboard(), target_chat_id=chat_id)
            return

        msg = f"""💣 <b>[RADAR SĂN COIN RÁC: VOLUME > $100M & LỰC MUA CHỦ ĐỘNG]</b> 💣
━━━━━━━━━━━━━━━━━━
🎯 <b>Tiêu Chí Sàng Lọc Nghiêm Ngặt:</b>
• <b>Thanh khoản:</b> Khối lượng 24h <b>> 100 Triệu USD</b> (Cá mập gom hàng, không sợ trượt giá).
• <b>Hành động giá:</b> <b>Volume Mua Vào Chủ Động (Momentum Breakout)</b> — Tuyệt đối KHÔNG bắt đáy dao rơi (Buy the dip)!
• <b>Cắt lỗ an toàn:</b> <b>SL 5% - 9%</b> (Bảo vệ dưới chân nến H1).
━━━━━━━━━━━━━━━━━━"""

        for i, c in enumerate(coins, 1):
            p = c['price']
            p_str = f"${p:,.6f}" if p < 1 else f"${p:,.4f}"
            sl_str = f"${c['sl_price']:,.6f}" if p < 1 else f"${c['sl_price']:,.4f}"
            tp1_str = f"${c['tp1_price']:,.6f}" if p < 1 else f"${c['tp1_price']:,.4f}"
            tp2_str = f"${c['tp2_price']:,.6f}" if p < 1 else f"${c['tp2_price']:,.4f}"
            
            msg += f"""
{i}. 🚀 <b>{c['symbol']}</b> (Biến động 24h: <b>+{c['change']:.2f}%</b>)
• 💰 <b>Thị giá:</b> <b>{p_str}</b> | 🌊 <b>Vol 24h:</b> <b>${c['vol_m']:.1f}M USD</b>
👉 <b>Entry Vào Ngay:</b> <code>{p_str}</code> (Market / Đón râu M15)
🛡️ <b>Cắt lỗ (SL):</b> <code>{sl_str}</code> (<b>-{c['sl_pct']}%</b>)
🎯 <b>Chốt lời 1 (TP1 - Chốt 50% & Dời Hoà):</b> <code>{tp1_str}</code> (<b>+{c['tp1_pct']}%</b> | R:R 1:1.5)
🎯 <b>Chốt lời 2 (TP2 - Gồng Ăn Sóng Pump):</b> <code>{tp2_str}</code> (<b>+{c['tp2_pct']}%</b> | R:R 1:3.0)
"""

        msg += f"""━━━━━━━━━━━━━━━━━━
🛡️ <b>QUẢN LÝ VỐN COIN RÁC (Vốn mẫu: ${CONFIG['ACCOUNT_BALANCE']:,.0f}):</b>
• Rủi ro tối đa 2%: <b>$40.0</b> (Quy mô vị thế: ~<b>$450 - $700</b> | Đòn bẩy an toàn: <b>2x - 3x</b> hoặc Spot)
💡 <i>Chiến thuật: Khi chạm TP1 (+{coins[0]['tp1_pct']}%), lập tức chốt 50% và dời SL về hoà vốn để free-risk!</i>"""

        send_telegram(msg, reply_markup=get_main_keyboard(), target_chat_id=chat_id)
    except Exception as e:
        send_telegram(f"⚠️ Lỗi quét Coin Rác: {e}", reply_markup=get_main_keyboard(), target_chat_id=chat_id)

# ==========================================
# 4. ĐÁNH GIÁ & LỌC CỔ PHIẾU VIỆT NAM (VN-INDEX, P/E < 10, G > 10%)
# ==========================================
VN_WATCHLIST = [
    'HPG', 'MBB', 'TCB', 'ACB', 'CTG', 'VPB', 'VHM', 'MWG', 'MSN', 'VNM',
    'FPT', 'DCM', 'DPM', 'PVS', 'PC1', 'HAH', 'SSI', 'GMD', 'HDB', 'VRE',
    'STB', 'BID', 'VCB', 'KBC', 'NLG', 'IDC', 'VIX', 'PVD', 'DGC', 'HCM', 'SHS'
]

def get_vnindex_summary():
    """Lấy dữ liệu chỉ số VN-Index từ DNSE API"""
    try:
        now = int(time.time())
        month_ago = now - 30 * 86400
        url = f"https://services.entrade.com.vn/chart-api/v2/ohlcs/index?from={month_ago}&to={now}&symbol=VNINDEX&resolution=1D"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as resp:
            d = json.loads(resp.read().decode('utf-8'))
            closes = d.get('c', [])
            vols = d.get('v', [])
            times = d.get('t', [])
            if len(closes) >= 2:
                last_c = closes[-1]
                prev_c = closes[-2]
                chg = last_c - prev_c
                chg_pct = (chg / prev_c) * 100
                last_date = datetime.datetime.fromtimestamp(times[-1]).strftime('%d/%m/%Y')
                last_vol = vols[-1] if vols else 0
                return {
                    'price': last_c,
                    'change': chg,
                    'change_pct': chg_pct,
                    'volume': last_vol,
                    'date': last_date
                }
    except Exception as e:
        pass
    return None

def analyze_vn_stock(ticker):
    """Phân tích 1 cổ phiếu theo P/E, G, PEG, ROE, Inflow/Outflow qua Simplize API"""
    ticker = ticker.upper().strip()
    url = f"https://api.simplize.vn/api/company/summary/{ticker}"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode('utf-8')).get('data', {})
            price = data.get('priceClose', 0)
            pe = data.get('peRatio', 0)
            pb = data.get('pbRatio', 0)
            eps = data.get('epsRatio', 0)
            g = data.get('netIncomeLtmGrowth', 0)
            rev_g = data.get('revenueLtmGrowth', 0)
            roe = data.get('roe', 0)
            roa = data.get('roa', 0)
            vol = data.get('volume', 0)
            avg_vol = data.get('volume10dAvg', 0)
            sector = data.get('bcEconomicSectorName', 'N/A')
            name = data.get('nameVi', ticker)
            
            peg = round(pe / g, 2) if (g and g > 0 and pe and pe > 0) else None
            
            # Đánh giá dòng tiền (Inflow / Outflow)
            vol_ratio = round(vol / avg_vol, 2) if (avg_vol and avg_vol > 0) else 1.0
            if vol_ratio >= 1.2:
                flow = f"🟢 INFLOW MẠNH (Vol {vol_ratio}x TB 10 phiên - Dòng tiền lớn gom hàng)"
            elif vol_ratio <= 0.8:
                flow = f"🟡 TÍCH LŨY CẠN CUNG (Vol {vol_ratio}x TB 10 phiên - Lực bán cạn)"
            else:
                flow = f"⚖️ TRUNG TÍNH (Vol xấp xỉ TB 10 phiên)"
                
            # Đánh giá tiêu chí Peter Lynch & Tiềm năng
            if pe and pe < 10 and g and g > 10:
                rating = "💎 SIÊU TIỀM NĂNG (P/E < 10, Tăng trưởng G > 10% - Rất rẻ theo Benjamin Graham & Peter Lynch)"
                action = "🟢 KHUYẾN NGHỊ MUA GOM TÍCH SẢN (Vùng giá hấp dẫn để giữ trung - dài hạn)"
            elif pe and pe < 12 and g and g > 0:
                rating = "⭐ ĐỊNH GIÁ HỢP LÝ (P/E thấp, Doanh nghiệp tiếp tục tăng trưởng)"
                action = "🟢 CANH MUA KHI CÓ NHỊP CHỈNH THEO VN-INDEX"
            elif pe and pe >= 20:
                rating = "⚠️ ĐỊNH GIÁ CAO (P/E >= 20, Kỳ vọng đã phản ánh nhiều vào giá)"
                action = "⛔ KHÔNG MUA ĐUỔI - CẦN CHIẾT KHẤU THÊM"
            else:
                rating = "⚡ THEO DÕI THÊM TĂNG TRƯỞNG LỢI NHUẬN CÁC QUÝ TỚI"
                action = "⏳ QUAN SÁT THÊM TÍN HIỆU DÒNG TIỀN"

            return {
                'ticker': ticker,
                'name': name,
                'sector': sector,
                'price': price,
                'pe': pe,
                'pb': pb,
                'eps': eps,
                'g': g,
                'rev_g': rev_g,
                'peg': peg,
                'roe': roe,
                'roa': roa,
                'vol': vol,
                'avg_vol': avg_vol,
                'vol_ratio': vol_ratio,
                'flow': flow,
                'rating': rating,
                'action': action
            }
    except Exception as e:
        return {'error': str(e), 'ticker': ticker}

def scan_top_vn_stocks():
    """Lọc danh sách các mã cổ phiếu đạt tiêu chí P/E < 12 và G > 10%"""
    now = time.time()
    cache = PLAN_CACHE.get('VN_STOCKS')
    if cache and cache['data'] and (now - cache['time'] < 1800):
        return cache['data']
        
    results = []
    for sym in VN_WATCHLIST:
        res = analyze_vn_stock(sym)
        if 'error' not in res and res.get('price', 0) > 0:
            results.append(res)
        time.sleep(0.04)
        
    # Lọc các cổ phiếu có P/E <= 12 và G >= 10%
    qualified = [r for r in results if r.get('pe') and 0 < r['pe'] <= 12.0 and r.get('g') and r['g'] >= 10.0]
    qualified.sort(key=lambda x: (x.get('peg') or 999.0))
    
    data = {
        'all': results,
        'qualified': qualified,
        'scan_time': datetime.datetime.now(TZ_VN).strftime('%H:%M %d/%m/%Y')
    }
    PLAN_CACHE['VN_STOCKS'] = {'time': now, 'data': data}
    return data

def handle_vn_stocks_overview(chat_id=None):
    """Gửi tổng quan vĩ mô lãi suất, dòng vốn ngoại và top cổ phiếu tiềm năng P/E < 10, G > 10%"""
    send_telegram("⏳ <i>Đang quét và phân tích dữ liệu BCTC & Dòng tiền cổ phiếu Việt Nam (P/E < 10, G > 10%)...</i>", target_chat_id=chat_id)
    try:
        data = scan_top_vn_stocks()
        vnindex = get_vnindex_summary()
        qualified = data['qualified']
        
        vn_str = ""
        if vnindex:
            vn_str = f"📊 <b>VN-Index ({vnindex['date']}):</b> <code>{vnindex['price']:.2f}</code> ({vnindex['change']:+.2f} | <b>{vnindex['change_pct']:+.2f}%</b>) - Khối lượng: {vnindex['volume']:,}\n"
        
        msg = f"""🇻🇳 <b>PHÂN TÍCH THỊ TRƯỜNG & LỌC CỔ PHIẾU TIỀM NĂNG VIỆT NAM</b>
━━━━━━━━━━━━━━━━━━
{vn_str}
🌐 <b>BỐI CẢNH VĨ MÔ & LÃI SUẤT (MACRO CONTEXT):</b>
• <b>Lãi suất Việt Nam (NHNN - SBV):</b> Duy trì mặt bằng thấp (Lãi suất tái cấp vốn <b>4.5%</b>, Lãi suất tiền gửi 12T quanh <b>4.8% - 5.3%</b>). Môi trường tiền rẻ thúc đẩy tín dụng và định giá P/E thị trường mở rộng.
• <b>Lãi suất Mỹ (Fed Funds Rate):</b> Dao động <b>4.50% - 4.75%</b> trong chu kỳ nới lỏng tiền tệ, hạ nhiệt sức mạnh DXY và giảm áp lực tỷ giá USD/VND.
• <b>Dòng vốn ngoại (Foreign Capital):</b> Khối ngoại có xu hướng sàng lọc kỹ, bán ròng mã đầu cơ P/E cao và gom tích lũy các cổ phiếu đầu ngành có <b>P/E &lt; 10, ROE &gt; 15%</b> và dòng tiền kinh doanh lành mạnh.

🎯 <b>TIÊU CHÍ SÀNG LỌC ĐẦU TƯ GIÁ TRỊ TĂNG TRƯỞNG:</b>
1. <b>P/E &lt; 10:</b> Định giá rẻ, hoàn vốn dưới 10 năm.
2. <b>G &gt; 10%:</b> Tăng trưởng lợi nhuận ròng LTM trên 10% và duy trì ổn định.
3. <b>PEG &lt; 1.0:</b> Tỷ số PEG siêu rẻ theo phương pháp Peter Lynch.
4. <b>Dòng tiền (Inflow):</b> Đang có dòng tiền tổ chức gom hàng hoặc tích lũy cạn cung.
━━━━━━━━━━━━━━━━━━
🏆 <b>TOP CỔ PHIẾU ĐẠT TIÊU CHÍ VÀNG:</b>
"""
        if not qualified:
            msg += "\n<i>Hiện tại chưa có mã nào thỏa mãn đồng thời P/E &lt; 10 và G &gt; 10%.</i>"
        else:
            for idx, r in enumerate(qualified[:8], 1):
                star = "💎" if r['pe'] < 10 else "⭐"
                peg_str = f"{r['peg']:.2f}" if r['peg'] is not None else "N/A"
                msg += f"""
{idx}. {star} <b>{r['ticker']}</b> - {r['name']} ({r['sector']})
• Thị giá: <b>{r['price']:,.0f} đ</b>
• <b>P/E:</b> <code>{r['pe']:.2f}</code> | <b>Tăng trưởng G:</b> <code>{r['g']:+.1f}%</code>
• <b>PEG:</b> <code>{peg_str}</code> (Cực rẻ) | <b>ROE:</b> <code>{r['roe']:.1f}%</code>
• <b>Dòng tiền:</b> <i>{r['flow']}</i>
• <b>Khuyến nghị:</b> {r['action']}
"""
        msg += f"""━━━━━━━━━━━━━━━━━━
💡 <i>Để xem chi tiết tài chính & định giá từng mã, gõ:</i>
<code>/vnstock &lt;MÃ&gt;</code> <i>(Ví dụ: <code>/vnstock HPG</code>, <code>/vnstock MBB</code>, <code>/vnstock FPT</code> hoặc gõ thẳng tên mã)</i>
⏱️ <i>Cập nhật: {data['scan_time']}</i>"""
        send_telegram(msg, reply_markup=get_main_keyboard(), target_chat_id=chat_id)
    except Exception as e:
        send_telegram(f"⚠️ Lỗi phân tích cổ phiếu: {e}", reply_markup=get_main_keyboard(), target_chat_id=chat_id)

def handle_vn_stock_detail(ticker, chat_id=None):
    """Phân tích chi tiết 1 mã cổ phiếu theo yêu cầu của người dùng"""
    ticker = ticker.upper().strip()
    send_telegram(f"⏳ <i>Đang phân tích chi tiết mã cổ phiếu <b>{ticker}</b>...</i>", target_chat_id=chat_id)
    try:
        r = analyze_vn_stock(ticker)
        if 'error' in r or r.get('price', 0) == 0:
            send_telegram(f"⚠️ Không tìm thấy dữ liệu cho mã <b>{ticker}</b> hoặc mã không tồn tại trên sàn HSX/HNX/UPCOM.", reply_markup=get_main_keyboard(), target_chat_id=chat_id)
            return

        peg_str = f"{r['peg']:.2f}" if r['peg'] is not None else "N/A"
        pe_str = f"{r['pe']:.2f}" if r['pe'] else "N/A"
        pb_str = f"{r['pb']:.2f}" if r['pb'] else "N/A"
        eps_str = f"{r['eps']:,.0f}" if r['eps'] else "N/A"
        g_str = f"{r['g']:+.1f}%" if r['g'] is not None else "N/A"
        rev_g_str = f"{r['rev_g']:+.1f}%" if r['rev_g'] is not None else "N/A"
        roe_str = f"{r['roe']:.1f}%" if r['roe'] is not None else "N/A"
        roa_str = f"{r['roa']:.1f}%" if r['roa'] is not None else "N/A"
        
        msg = f"""🇻🇳 <b>BÁO CÁO PHÂN TÍCH CHI TIẾT CỔ PHIẾU: {r['ticker']}</b>
━━━━━━━━━━━━━━━━━━
🏢 <b>Doanh nghiệp:</b> {r['name']}
🏭 <b>Ngành nghề:</b> {r['sector']}
💰 <b>Thị giá:</b> <b>{r['price']:,.0f} VNĐ</b>

📊 <b>CHỈ SỐ TÀI CHÍNH CƠ BẢN:</b>
• <b>P/E Hiện tại:</b> <code>{pe_str}</code> (Tiêu chí chuẩn &lt; 10)
• <b>P/B:</b> <code>{pb_str}</code> | <b>EPS:</b> <code>{eps_str} đ</code>
• <b>ROE (Hiệu quả sử dụng vốn):</b> <code>{roe_str}</code>
• <b>ROA:</b> <code>{roa_str}</code>

📈 <b>TĂNG TRƯỞNG & ĐỊNH GIÁ PETER LYNCH:</b>
• <b>Tăng trưởng Lợi nhuận (G - LTM):</b> <code>{g_str}</code>
• <b>Tăng trưởng Doanh thu:</b> <code>{rev_g_str}</code>
• <b>Định giá PEG (P/E / G):</b> <code>{peg_str}</code> <i>(PEG &lt; 1.0 là cổ phiếu tăng trưởng bị định giá rẻ)</i>

🌊 <b>DÒNG TIỀN & THANH KHOẢN:</b>
• Khối lượng giao dịch: <b>{r['vol']:,}</b> cp
• Trung bình 10 phiên: <b>{r['avg_vol']:,}</b> cp
• Đánh giá dòng tiền: <i>{r['flow']}</i>

🎯 <b>KẾT LUẬN & ĐÁNH GIÁ ĐẦU TƯ:</b>
• <b>Xếp hạng:</b> {r['rating']}
• <b>Hành động:</b> <b>{r['action']}</b>
━━━━━━━━━━━━━━━━━━
<i>💡 Gõ <code>/vnstock</code> để quay lại danh sách top cổ phiếu tiềm năng toàn thị trường!</i>"""
        send_telegram(msg, reply_markup=get_main_keyboard(), target_chat_id=chat_id)
    except Exception as e:
        send_telegram(f"⚠️ Lỗi phân tích mã {ticker}: {e}", reply_markup=get_main_keyboard(), target_chat_id=chat_id)

# ==========================================
# 5. SERVER HEALTH CHECK & AUTO-PING
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
                    chat_obj = msg.get("chat", {})
                    chat_id = str(chat_obj.get("id"))
                    from_user = msg.get("from", {})
                    first_name = from_user.get("first_name", "User")
                    username = from_user.get("username", "")
                    user_tag = f"@{username}" if username else first_name
                    
                    if not chat_id or chat_id == "None":
                        continue

                    # 1. Quản lý phê duyệt dành riêng cho ADMIN
                    if chat_id == ADMIN_ID:
                        if text.startswith("/approve"):
                            parts = text.split()
                            if len(parts) >= 2:
                                target_id = parts[1].strip()
                                add_approved_user(target_id, name=f"User {target_id}")
                                send_telegram(f"✅ Đã <b>DUYỆT</b> thành công quyền sử dụng bot cho ID: <code>{target_id}</code>!", target_chat_id=ADMIN_ID)
                                send_telegram("🎉 <b>CHÚC MỪNG!</b>\nTài khoản của bạn đã được Admin phê duyệt quyền sử dụng <b>FX DREAM TRADING BOT</b>!\nBấm các nút bên dưới để bắt đầu nhận phân tích:", reply_markup=get_main_keyboard(), target_chat_id=target_id)
                            else:
                                send_telegram("⚠️ Cú pháp duyệt thành viên: <code>/approve &lt;ID_Telegram&gt;</code>", target_chat_id=ADMIN_ID)
                            continue
                        elif text.startswith("/revoke"):
                            parts = text.split()
                            if len(parts) >= 2:
                                target_id = parts[1].strip()
                                ok = remove_approved_user(target_id)
                                if ok:
                                    send_telegram(f"🚫 Đã <b>HUỶ QUYỀN</b> sử dụng bot của ID: <code>{target_id}</code>!", target_chat_id=ADMIN_ID)
                                    send_telegram("⚠️ Quyền sử dụng bot của bạn đã bị thu hồi bởi Admin.", target_chat_id=target_id)
                                else:
                                    send_telegram(f"⚠️ Không tìm thấy hoặc không thể huỷ ID: <code>{target_id}</code>", target_chat_id=ADMIN_ID)
                            else:
                                send_telegram("⚠️ Cú pháp huỷ quyền: <code>/revoke &lt;ID_Telegram&gt;</code>", target_chat_id=ADMIN_ID)
                            continue
                        elif text in ["/users", "/members", "users", "Danh Sách Thành Viên"]:
                            users = load_authorized_users()
                            u_list = "👥 <b>DANH SÁCH THÀNH VIÊN ĐƯỢC DUYỆT:</b>\n━━━━━━━━━━━━━━━━━━\n"
                            for uid, info in users.items():
                                u_role = "👑 ADMIN" if info.get('role') == 'admin' else "👤 Member"
                                u_list += f"• <b>{info.get('name', 'User')}</b> ({u_role})\n  ID: <code>{uid}</code> | Kích hoạt: {info.get('date', '')}\n"
                            u_list += f"\n<i>👉 Để huỷ quyền, gõ: /revoke &lt;ID&gt;</i>"
                            send_telegram(u_list, target_chat_id=ADMIN_ID)
                            continue

                    # 2. Kiểm duyệt người dùng lạ: Nếu chưa được duyệt thì chặn và báo Admin
                    if not is_user_approved(chat_id):
                        guest_msg = f"""👋 <b>Xin chào {first_name}!</b>
━━━━━━━━━━━━━━━━━━
🔒 <b>HỆ THỐNG TRUY CẬP CÓ KIỂM SOÁT</b>
Tài khoản của bạn hiện tại chưa được cấp quyền sử dụng hệ thống tín hiệu và phân tích VIP.

🆔 <b>Telegram ID của bạn:</b> <code>{chat_id}</code>
⏱️ Yêu cầu của bạn đã được tự động gửi tới Admin phê duyệt.

<i>👉 Vui lòng liên hệ Admin để được cấp quyền kích hoạt!</i>"""
                        send_telegram(guest_msg, target_chat_id=chat_id)

                        admin_alert = f"""🔔 <b>[YÊU CẦU TRUY CẬP BOT MỚI]</b> 🔔
━━━━━━━━━━━━━━━━━━
👤 <b>Người dùng:</b> {first_name} ({user_tag})
🆔 <b>Telegram ID:</b> <code>{chat_id}</code>
⏱️ <b>Thời gian:</b> {datetime.datetime.now(TZ_VN).strftime('%H:%M:%S %d/%m/%Y')}

👉 <b>ĐỂ PHÊ DUYỆT NGAY, BẤM VÀO LỆNH SAU:</b>
<code>/approve {chat_id}</code>"""
                        send_telegram(admin_alert, target_chat_id=ADMIN_ID)
                        continue

                    # 3. Phân luồng tính năng cho thành viên ĐÃ ĐƯỢC DUYỆT
                    if text in ["/start", "menu", "Menu", "⚙️ Menu Hỗ Trợ"]:
                        menu_help = """🤖 <b>BẢNG ĐIỀU KHIỂN & MENU TÍNH NĂNG BOT:</b>
━━━━━━━━━━━━━━━━━━
👑 <b>Phân Tích BTC:</b> Bias W1/D1 + SMC KeyVolume H1 & M5
🥇 <b>Phân Tích VÀNG (XAU):</b> Chuẩn OANDA MT5 + SMC H1 OB
🎯 <b>Scalping Volume Profile M5:</b> Đánh xoay trục L-Shape/P-Shape hôm trước (yVAL/yVAH) & dPOC
⚡ <b>Tuyệt Chiêu H4 Lưỡng Lự:</b> Bắt bứt phá Breakout nến H4
💣 <b>Săn Coin Rác (Vol > $100M):</b> Bắt momentum mua vào, SL 5% - 9% (Nói KHÔNG với bắt dao rơi / Buy the dip)
📈 <b>Tìm Coin TĂNG (LONG):</b> Lọc coin tích lũy gom hàng Bybit
📉 <b>Tìm Coin GIẢM (SHORT):</b> Lọc coin phân phối xả hàng Bybit
🇻🇳 <b>Đánh Giá Cổ Phiếu VN:</b> Định giá PE < 10, G > 10%, dòng tiền & lãi suất
🔍 <b>Kiểm Tra Lệnh & Báo Cáo Ngày:</b> Live Radar trực tiếp + Quản lý lệnh đang chạy

💡 <i>Bấm các nút bên dưới hoặc gõ trực tiếp lệnh (/gold, /btc, /scalp, /meme, /h4, /check, /vnstock)!</i>"""
                        send_telegram(menu_help, reply_markup=get_main_keyboard(), target_chat_id=chat_id)
                    elif text in ["/check", "check", "🔍 Kiểm Tra Lệnh & Báo Cáo Ngày"]:
                        handle_check_vip_trades(chat_id=chat_id)
                    elif text in ["/meme", "/coinrac", "/junk", "/gem", "/alt", "💣 Săn Coin Rác (Vol > $100M)", "coinrac", "coin rác", "Coin rác", "săn coin rác", "san coin rac"]:
                        handle_meme_coins(chat_id=chat_id)
                    elif text in ["/h4", "⚡ Tuyệt Chiêu H4 Lưỡng Lự", "h4", "H4", "breakout", "Breakout"]:
                        handle_h4_breakout(chat_id=chat_id)
                    elif text in ["/scalp", "/vp", "/volumeprofile", "🎯 Scalping Volume Profile M5", "⚡ Scalping Vàng/BTC (Volume Profile M5)", "scalp", "Scalp", "SCALP", "vp", "VP"]:
                        handle_vp_scalping(chat_id=chat_id)
                    elif text in ["/btc", "👑 Phân Tích BTC", "btc", "BTC"]:
                        handle_btc(chat_id=chat_id)
                    elif text in ["/gold", "🥇 Phân Tích VÀNG (XAU)", "gold", "vang", "Vàng"]:
                        handle_gold(chat_id=chat_id)
                    elif text in ["/long", "📈 Tìm Coin TĂNG (LONG)", "long"]:
                        handle_scan(mode='long', chat_id=chat_id)
                    elif text in ["/short", "📉 Tìm Coin GIẢM (SHORT)", "short"]:
                        handle_scan(mode='short', chat_id=chat_id)
                    elif text in ["/vnstock", "/cophieu", "/stock", "🇻🇳 Đánh Giá Cổ Phiếu VN", "cophieu", "Cổ phiếu", "chungkhoan", "Chứng khoán"]:
                        handle_vn_stocks_overview(chat_id=chat_id)
                    elif text.startswith("/vnstock ") or text.startswith("/cp "):
                        parts = text.split()
                        if len(parts) >= 2:
                            handle_vn_stock_detail(parts[1].strip(), chat_id=chat_id)
                        else:
                            handle_vn_stocks_overview(chat_id=chat_id)
                    elif len(text) == 3 and text.upper() in VN_WATCHLIST:
                        handle_vn_stock_detail(text.upper(), chat_id=chat_id)
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

            # 4. RADAR CẢNH BÁO CHẠM CẢN KHỐI OB H1 (VÀNG & BITCOIN)
            # 4.1. Radar Vàng
            p_g = plan_gold['current_price']
            if (p_g >= plan_gold['b_ob_bot'] - 1.0 and p_g <= plan_gold['b_ob_top'] + 3.0):
                if now - LAST_RADAR_ALERT['GOLD_BEAR'] > 1800:
                    send_telegram(f"""🔔 <b>[RADAR: VÀNG ĐÃ CHẠM KHỐI BEARISH OB H1]</b> 🔔
━━━━━━━━━━━━━━━━━━
💰 Giá Vàng hiện tại: <code>${p_g:,.2f}</code>
🧱 Khối Kháng Cự H1: <code>[${plan_gold['b_ob_bot']:,.2f} - ${plan_gold['b_ob_top']:,.2f}]</code>
⚖️ Điểm Cân Bằng 50%: <code>${plan_gold['b_ob_mid']:,.2f}</code>
━━━━━━━━━━━━━━━━━━
⚠️ <b>HÀNH ĐỘNG CẦN LÀM:</b>
• Giá Vàng đã chính thức đi vào VÙNG CANH SELL!
• Hãy mở chart M5 quan sát: Nếu nến M5 rút râu từ chối + nổ Volume thì chuẩn bị đón tín hiệu vào lệnh!""")
                    LAST_RADAR_ALERT['GOLD_BEAR'] = now
            elif (p_g <= plan_gold['bull_ob_top'] + 1.0 and p_g >= plan_gold['bull_ob_bot'] - 3.0):
                if now - LAST_RADAR_ALERT['GOLD_BULL'] > 1800:
                    send_telegram(f"""🔔 <b>[RADAR: VÀNG ĐÃ CHẠM KHỐI BULLISH OB H1]</b> 🔔
━━━━━━━━━━━━━━━━━━
💰 Giá Vàng hiện tại: <code>${p_g:,.2f}</code>
🧱 Khối Hỗ Trợ H1: <code>[${plan_gold['bull_ob_bot']:,.2f} - ${plan_gold['bull_ob_top']:,.2f}]</code>
⚖️ Điểm Cân Bằng 50%: <code>${plan_gold['bull_ob_mid']:,.2f}</code>
━━━━━━━━━━━━━━━━━━
⚠️ <b>HÀNH ĐỘNG CẦN LÀM:</b>
• Giá Vàng đã chính thức đi vào VÙNG CANH BUY!
• Hãy mở chart M5 quan sát: Nếu nến M5 rút chân đẩy lên + nổ Volume thì chuẩn bị đón tín hiệu vào lệnh!""")
                    LAST_RADAR_ALERT['GOLD_BULL'] = now

            # 4.2. Radar Bitcoin
            p_b = plan_btc['current_price']
            if (p_b >= plan_btc['b_ob_bot'] - 50.0 and p_b <= plan_btc['b_ob_top'] + 150.0):
                if now - LAST_RADAR_ALERT['BTC_BEAR'] > 1800:
                    send_telegram(f"""🔔 <b>[RADAR: BTC ĐÃ CHẠM KHỐI BEARISH OB H1]</b> 🔔
━━━━━━━━━━━━━━━━━━
💰 Giá BTC hiện tại: <code>${p_b:,.1f}</code>
🧱 Khối Kháng Cự H1: <code>[${plan_btc['b_ob_bot']:,.1f} - ${plan_btc['b_ob_top']:,.1f}]</code>
⚖️ Điểm Cân Bằng 50%: <code>${plan_btc['b_ob_mid']:,.1f}</code>
━━━━━━━━━━━━━━━━━━
⚠️ <b>HÀNH ĐỘNG CẦN LÀM:</b>
• Giá BTC đã chính thức đi vào VÙNG CANH SELL!
• Hãy mở chart M5 quan sát: Nếu nến M5 rút râu từ chối + nổ Volume thì chuẩn bị đón tín hiệu vào lệnh!""")
                    LAST_RADAR_ALERT['BTC_BEAR'] = now
            elif (p_b <= plan_btc['bull_ob_top'] + 50.0 and p_b >= plan_btc['bull_ob_bot'] - 150.0):
                if now - LAST_RADAR_ALERT['BTC_BULL'] > 1800:
                    send_telegram(f"""🔔 <b>[RADAR: BTC ĐÃ CHẠM KHỐI BULLISH OB H1]</b> 🔔
━━━━━━━━━━━━━━━━━━
💰 Giá BTC hiện tại: <code>${p_b:,.1f}</code>
🧱 Khối Hỗ Trợ H1: <code>[${plan_btc['bull_ob_bot']:,.1f} - ${plan_btc['bull_ob_top']:,.1f}]</code>
⚖️ Điểm Cân Bằng 50%: <code>${plan_btc['bull_ob_mid']:,.1f}</code>
━━━━━━━━━━━━━━━━━━
⚠️ <b>HÀNH ĐỘNG CẦN LÀM:</b>
• Giá BTC đã chính thức đi vào VÙNG CANH BUY!
• Hãy mở chart M5 quan sát: Nếu nến M5 rút chân đẩy lên + nổ Volume thì chuẩn bị đón tín hiệu vào lệnh!""")
                    LAST_RADAR_ALERT['BTC_BULL'] = now

            # 5. QUÉT TỰ ĐỘNG BẮN KÈO VÀNG (OANDA:XAUUSD - Chuẩn MT5)
            has_active_gold = any(t.get('symbol') == 'XAUUSD' for t in active_trades)
            dist_to_cản_gold = abs(plan_gold['current_price'] - plan_gold['entry_limit'])
            is_gold_ready = plan_gold.get('is_confirmed') and (
                ('ĐÃ PHÁ VỠ CẤU TRÚC M15' in plan_gold.get('confirm_badge', '')) or
                ('REJECTION KEYVOLUME M5' in plan_gold.get('confirm_badge', ''))
            ) and (dist_to_cản_gold <= 10.0)

            if not has_active_gold and is_gold_ready:
                if now - LAST_ALERT_TIME['GOLD'] > 1200: # Cooldown giữa các kèo
                    price_gold = plan_gold['current_price']
                    entry_gold = plan_gold['entry_limit']
                    s_emoji = "🔴 SHORT (BÁN)" if plan_gold['signal'] == 'SHORT' else "🟢 LONG (MUA)"
                    is_rej = 'REJECTION KEYVOLUME M5' in plan_gold.get('confirm_badge', '')
                    title_g = "🚨 <b>[TỰ ĐỘNG BÁO KÈO VIP: REJECTION KEYVOLUME M5 TẠI OB H1]</b> 🚨" if is_rej else "🚨 <b>[TỰ ĐỘNG BÁO KÈO VIP: ĐÃ PHÁ VỠ CẤU TRÚC M15 & KÍCH VOL M5]</b> 🚨"
                    action_l = "LỆNH VÀO NGAY (Rejection Rút Râu + Nổ Vol M5 tại OB):" if is_rej else "LỆNH VÀO NGAY (M15 Đã Gãy Cấu Trúc + M5 Retest Kích Vol):"
                    msg = f"""{title_g}
━━━━━━━━━━━━━━━━━━
📊 Nguồn biểu đồ: <b>TradingView (OANDA:XAUUSD - Chuẩn MT5)</b>
💰 Giá Vàng hiện tại: <b>${price_gold:,.2f}</b>
🎯 <b>Trạng thái:</b> <b>{plan_gold.get('confirm_badge', 'ĐÃ XÁC NHẬN')}</b>
📊 <b>Khối Bearish OB H1:</b> <code>[${plan_gold['b_ob_bot']:,.2f} - ${plan_gold['b_ob_top']:,.2f}]</code>
📉 <b>Khối Bullish OB H1:</b> <code>[${plan_gold['bull_ob_bot']:,.2f} - ${plan_gold['bull_ob_top']:,.2f}]</code>
⚡ <b>Cấu Trúc Khung M15:</b> <b>{plan_gold.get('m15_status')}</b> (Mốc BOS: <code>${plan_gold.get('m15_choch_level', 0):,.2f}</code>)
━━━━━━━━━━━━━━━━━━
💎 <b>ĐỒNG PHA BIAS ĐA KHUNG (WINRATE CAO):</b>
• <b>Bias Tuần (W1):</b> {plan_gold['w1_bias']}
• <b>Bias Ngày (D1):</b> {plan_gold['d1_bias']}
<i>🔥 Tín hiệu chuẩn SMC & KeyVolume FX DREAM, kích hoạt vào lệnh tại cản!</i>
━━━━━━━━━━━━━━━━━━
🚀 <b>KHUYẾN NGHỊ VÀO LỆNH: {s_emoji}</b>
👉 <b>{action_l}</b>
   <code>${entry_gold:,.2f}</code>

🛡️ <b>Cắt lỗ (SL Ngoài Râu M5):</b>
   <code>${plan_gold['sl']:,.2f}</code> (~{plan_gold['sl_dist']:.1f} Giá)
🎯 <b>Chốt lời 1 (TP1 - R:R 1:1.2 | Chốt 50% & Dời Hoà):</b> <code>${plan_gold['tp1']:,.2f}</code>
🎯 <b>Chốt lời 2 (TP2 - R:R 1:2.5 | Gồng Về Cản):</b> <code>${plan_gold['tp2']:,.2f}</code>

🧠 <b>Kế hoạch xử lý:</b>
{plan_gold['advice']}

🛡️ <b>QUẢN LÝ VỐN VÀNG MT5 (${CONFIG['ACCOUNT_BALANCE']:,.0f}):</b>
• Rủi ro tối đa 2%: <b>$40.0</b> (tương đương 0.02 - 0.04 lot trên MT5)"""
                    send_telegram(msg)
                    LAST_ALERT_TIME['GOLD'] = now
                    # Ghi nhận lệnh vào hệ thống theo dõi duy nhất 1 lệnh
                    record_new_vip_trade(
                        asset='GOLD',
                        symbol='XAUUSD',
                        signal=plan_gold['signal'],
                        entry_price=entry_gold,
                        entry_stop=plan_gold.get('entry_stop', 0),
                        sl=plan_gold['sl'],
                        tp1=plan_gold['tp1'],
                        tp2=plan_gold['tp2'],
                        sl_dist=plan_gold['sl_dist']
                    )

            # 6. QUÉT TỰ ĐỘNG BẮN KÈO BITCOIN (BTCUSDT)
            has_active_btc = any(t.get('symbol') == 'BTCUSDT' for t in active_trades)
            dist_to_cản_btc = abs(plan_btc['current_price'] - plan_btc['entry_limit'])
            is_btc_ready = plan_btc.get('is_confirmed') and (
                ('ĐÃ PHÁ VỠ CẤU TRÚC M15' in plan_btc.get('confirm_badge', '')) or
                ('REJECTION KEYVOLUME M5' in plan_btc.get('confirm_badge', ''))
            ) and (dist_to_cản_btc <= 450.0)

            if not has_active_btc and is_btc_ready:
                if now - LAST_ALERT_TIME['BTC'] > 1200:
                    price_btc = plan_btc['current_price']
                    entry_l = plan_btc['entry_limit']
                    s_emoji = "🔴 SHORT (BÁN)" if plan_btc['signal'] == 'SHORT' else "🟢 LONG (MUA)"
                    is_rej_b = 'REJECTION KEYVOLUME M5' in plan_btc.get('confirm_badge', '')
                    title_b = "🚨 <b>[TỰ ĐỘNG BÁO KÈO VIP: REJECTION KEYVOLUME M5 TẠI OB H1]</b> 🚨" if is_rej_b else "🚨 <b>[TỰ ĐỘNG BÁO KÈO VIP: ĐÃ PHÁ VỠ CẤU TRÚC M15 & KÍCH VOL M5]</b> 🚨"
                    action_l_b = "LỆNH VÀO NGAY (Rejection Rút Râu + Nổ Vol M5 tại OB):" if is_rej_b else "LỆNH VÀO NGAY (M15 Đã Gãy Cấu Trúc + M5 Retest Kích Vol):"
                    msg = f"""{title_b}
━━━━━━━━━━━━━━━━━━
💰 Giá BTC hiện tại: <b>${price_btc:,.1f}</b>
🎯 <b>Trạng thái:</b> <b>{plan_btc.get('confirm_badge', 'ĐÃ XÁC NHẬN')}</b>
📊 <b>Khối Bearish OB H1:</b> <code>[${plan_btc['b_ob_bot']:,.1f} - ${plan_btc['b_ob_top']:,.1f}]</code>
📉 <b>Khối Bullish OB H1:</b> <code>[${plan_btc['bull_ob_bot']:,.1f} - ${plan_btc['bull_ob_top']:,.1f}]</code>
⚡ <b>Cấu Trúc Khung M15:</b> <b>{plan_btc.get('m15_status')}</b> (Mốc BOS: <code>${plan_btc.get('m15_choch_level', 0):,.1f}</code>)
━━━━━━━━━━━━━━━━━━
💎 <b>ĐỒNG PHA BIAS ĐA KHUNG (WINRATE CAO):</b>
• <b>Bias Tuần (W1):</b> {plan_btc['w1_bias']}
• <b>Bias Ngày (D1):</b> {plan_btc['d1_bias']}
<i>🔥 Tín hiệu chuẩn SMC & KeyVolume FX DREAM, kích hoạt vào lệnh tại cản!</i>
━━━━━━━━━━━━━━━━━━
🚀 <b>KHUYẾN NGHỊ VÀO LỆNH: {s_emoji}</b>
👉 <b>{action_l_b}:</b>
   <code>${entry_l:,.1f}</code>

🛡️ <b>Cắt lỗ (SL Ngoài Râu M5):</b> <code>${plan_btc['sl']:,.1f}</code> (-{plan_btc['sl_pct']}%)
🎯 <b>Chốt lời 1 (TP1 - R:R 1:1.2 | Chốt 50% & Dời Hoà):</b> <code>${plan_btc['tp1']:,.1f}</code>
🎯 <b>Chốt lời 2 (TP2 - R:R 1:2.5 | Gồng Theo Sóng):</b> <code>${plan_btc['tp2']:,.1f}</code>

🧠 <b>Kế hoạch xử lý:</b>
{plan_btc['advice']}

🛡️ <b>QUẢN LÝ VỐN (${CONFIG['ACCOUNT_BALANCE']:,.0f}):</b>
• Rủi ro tối đa 2%: <b>$40.0</b> | Khối lượng: <b>$2,000.0</b> | Đòn bẩy: <b>5x</b>"""
                    send_telegram(msg)
                    LAST_ALERT_TIME['BTC'] = now
                    record_new_vip_trade(
                        asset='BTC',
                        symbol='BTCUSDT',
                        signal=plan_btc['signal'],
                        entry_price=entry_l,
                        entry_stop=plan_btc.get('entry_stop', 0),
                        sl=plan_btc['sl'],
                        tp1=plan_btc['tp1'],
                        tp2=plan_btc['tp2'],
                        sl_dist=abs(entry_l - plan_btc['sl'])
                    )

            # 7. QUÉT TỰ ĐỘNG BẮN KÈO SCALPING DAILY VOLUME PROFILE M5 (VÀNG OANDA)
            if not has_active_gold and (now - LAST_ALERT_TIME.get('GOLD_SCALP', 0) > 900):
                p_gold_vp = analyze_scalp_vp_plan('GOLD')
                if p_gold_vp and p_gold_vp.get('is_rejection_fresh') and p_gold_vp.get('dist_to_entry', 999) <= 4.5:
                    price_gold = p_gold_vp['curr_p']
                    entry_g = p_gold_vp['entry']
                    sl_g = p_gold_vp['sl']
                    tp1_g = p_gold_vp['tp1']
                    tp2_g = p_gold_vp['tp2']
                    s_emoji = "🟢 LONG (MUA)" if p_gold_vp['is_buy'] else "🔴 SHORT (BÁN)"
                    action_s = "BUY" if p_gold_vp['is_buy'] else "SELL"
                    
                    msg_scalp_g = f"""🚨 <b>[TỰ ĐỘNG BÁO KÈO VIP: SCALPING VOLUME PROFILE NGÀY]</b> 🚨
━━━━━━━━━━━━━━━━━━
🥇 Tài sản: <b>VÀNG (OANDA:XAUUSD MT5)</b>
💰 Giá hiện tại: <b>${price_gold:,.2f}</b>
🏛️ <b>VP Hôm Trước ({p_gold_vp['y_shape']}):</b>
• yVAL: <code>${p_gold_vp['y_val']:,.2f}</code> | yPOC: <code>${p_gold_vp['y_poc']:,.2f}</code> | yVAH: <code>${p_gold_vp['y_vah']:,.2f}</code>
🌅 <b>Hôm Nay:</b> Open: <code>${p_gold_vp['daily_open']:,.2f}</code> | dPOC: <code>${p_gold_vp['poc']:,.2f}</code>
🧭 <b>Bias:</b> {p_gold_vp['daily_bias']}
⚡ <b>Tín Hiệu M5:</b> <b>{p_gold_vp['wick_info']}</b>
━━━━━━━━━━━━━━━━━━
🚀 <b>LỆNH VÀO NGAY: {s_emoji}</b>
👉 <b>Entry ({action_s} Limit / Now):</b> <code>${entry_g:,.2f}</code>
🛡️ <b>Cắt lỗ (SL Bóp Chân Râu M5):</b> <code>${sl_g:,.2f}</code> (~{p_gold_vp['risk']} Giá)
🎯 <b>Chốt lời 1 (TP1 - Chốt 75%):</b> <code>${tp1_g:,.2f}</code>
🎯 <b>Chốt lời 2 (TP2 - Mục Tiêu Xoay Trục {p_gold_vp['y_shape']}):</b> <code>${tp2_g:,.2f}</code>

🧠 <b>Chiến Thuật:</b> {p_gold_vp['y_shape_desc']} Chốt 75% tại TP1, dời BE gồng 25% về TP2!"""
                    send_telegram(msg_scalp_g)
                    LAST_ALERT_TIME['GOLD_SCALP'] = now
                    record_new_vip_trade(
                        asset='GOLD',
                        symbol='XAUUSD',
                        signal='LONG' if p_gold_vp['is_buy'] else 'SHORT',
                        entry_price=entry_g,
                        entry_stop=0,
                        sl=sl_g,
                        tp1=tp1_g,
                        tp2=tp2_g,
                        sl_dist=p_gold_vp['risk']
                    )

            # 8. QUÉT TỰ ĐỘNG BẮN KÈO SCALPING DAILY VOLUME PROFILE M5 (BITCOIN)
            if not has_active_btc and (now - LAST_ALERT_TIME.get('BTC_SCALP', 0) > 900):
                p_btc_vp = analyze_scalp_vp_plan('BTC')
                if p_btc_vp and p_btc_vp.get('is_rejection_fresh') and p_btc_vp.get('dist_to_entry', 999) <= 150.0:
                    price_btc = p_btc_vp['curr_p']
                    entry_b = p_btc_vp['entry']
                    sl_b = p_btc_vp['sl']
                    tp1_b = p_btc_vp['tp1']
                    tp2_b = p_btc_vp['tp2']
                    s_emoji = "🟢 LONG (MUA)" if p_btc_vp['is_buy'] else "🔴 SHORT (BÁN)"
                    action_s = "BUY" if p_btc_vp['is_buy'] else "SELL"
                    
                    msg_scalp_b = f"""🚨 <b>[TỰ ĐỘNG BÁO KÈO VIP: SCALPING VOLUME PROFILE NGÀY]</b> 🚨
━━━━━━━━━━━━━━━━━━
👑 Tài sản: <b>BITCOIN (BTCUSDT)</b>
💰 Giá hiện tại: <b>${price_btc:,.1f}</b>
🏛️ <b>VP Hôm Trước ({p_btc_vp['y_shape']}):</b>
• yVAL: <code>${p_btc_vp['y_val']:,.1f}</code> | yPOC: <code>${p_btc_vp['y_poc']:,.1f}</code> | yVAH: <code>${p_btc_vp['y_vah']:,.1f}</code>
🌅 <b>Hôm Nay:</b> Open: <code>${p_btc_vp['daily_open']:,.1f}</code> | dPOC: <code>${p_btc_vp['poc']:,.1f}</code>
🧭 <b>Bias:</b> {p_btc_vp['daily_bias']}
⚡ <b>Tín Hiệu M5:</b> <b>{p_btc_vp['wick_info']}</b>
━━━━━━━━━━━━━━━━━━
🚀 <b>LỆNH VÀO NGAY: {s_emoji}</b>
👉 <b>Entry ({action_s} Limit / Now):</b> <code>${entry_b:,.1f}</code>
🛡️ <b>Cắt lỗ (SL Bóp Chân Râu M5):</b> <code>${sl_b:,.1f}</code> (~{p_btc_vp['risk']:,.1f} USD)
🎯 <b>Chốt lời 1 (TP1 - Chốt 75%):</b> <code>${tp1_b:,.1f}</code>
🎯 <b>Chốt lời 2 (TP2 - Mục Tiêu Xoay Trục {p_btc_vp['y_shape']}):</b> <code>${tp2_b:,.1f}</code>

🧠 <b>Chiến Thuật:</b> {p_btc_vp['y_shape_desc']} Chốt 75% tại TP1, dời BE gồng 25% về TP2!"""
                    send_telegram(msg_scalp_b)
                    LAST_ALERT_TIME['BTC_SCALP'] = now
                    record_new_vip_trade(
                        asset='BTC',
                        symbol='BTCUSDT',
                        signal='LONG' if p_btc_vp['is_buy'] else 'SHORT',
                        entry_price=entry_b,
                        entry_stop=0,
                        sl=sl_b,
                        tp1=tp1_b,
                        tp2=tp2_b,
                        sl_dist=p_btc_vp['risk']
                    )

        except Exception as e:
            print(f"Lỗi worker quét tự động: {e}")
            time.sleep(10)

if __name__ == '__main__':
    threading.Thread(target=start_health_server, daemon=True).start()
    threading.Thread(target=self_ping_worker, daemon=True).start()
    threading.Thread(target=auto_diamond_alert_worker, daemon=True).start()
    run_bot()
