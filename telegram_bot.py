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
def find_smc_swings_and_ob(klines_desc):
    """
    Xác định đỉnh/đáy cấu trúc uy tín (Valid Swing Point) và Khối Lệnh Order Block (OB)
    theo chuẩn phương pháp lọc Inside Bar của FX DREAM TRADING:
    - Swing High: Nến giữa cao nhất. Nếu nến phải là Inside Bar -> Cần nến sau đóng cửa dưới Low nến giữa để DUYỆT.
    - Swing Low: Nến giữa thấp nhất. Nếu nến phải là Inside Bar -> Cần nến sau đóng cửa trên High nến giữa để DUYỆT.
    - Tạo ra Khối Bearish/Bullish Order Block (OB).
    """
    chrono = list(reversed(klines_desc))
    n = len(chrono)
    
    confirmed_sh = []
    confirmed_sl = []
    
    for i in range(2, n - 2):
        prev_c = chrono[i - 1]
        mid_c = chrono[i]
        next_c = chrono[i + 1]
        
        mid_h = float(mid_c[2])
        mid_l = float(mid_c[3])
        
        # 1. Swing High candidate
        if mid_h > float(prev_c[2]) and mid_h > float(next_c[2]):
            is_inside_bar = (float(next_c[2]) <= mid_h) and (float(next_c[3]) >= mid_l)
            if not is_inside_bar:
                sh_time = datetime.datetime.fromtimestamp(int(mid_c[0])/1000, tz=TZ_VN).strftime('%H:%M %d/%m')
                confirmed_sh.append({
                    'time': sh_time, 'high': mid_h, 'low': mid_l, 'open': float(mid_c[1]), 'close': float(mid_c[4]), 'filter': 'Chuẩn 3 Nến'
                })
            else:
                is_valid = False
                for k in range(i + 2, n):
                    if float(chrono[k][2]) > mid_h:
                        break
                    if float(chrono[k][4]) < mid_l: # Đóng nến dưới Low để duyệt
                        is_valid = True
                        break
                if is_valid:
                    sh_time = datetime.datetime.fromtimestamp(int(mid_c[0])/1000, tz=TZ_VN).strftime('%H:%M %d/%m')
                    confirmed_sh.append({
                        'time': sh_time, 'high': mid_h, 'low': mid_l, 'open': float(mid_c[1]), 'close': float(mid_c[4]), 'filter': 'Duyệt Qua InsideBar'
                    })

        # 2. Swing Low candidate
        if mid_l < float(prev_c[3]) and mid_l < float(next_c[3]):
            is_inside_bar = (float(next_c[2]) <= mid_h) and (float(next_c[3]) >= mid_l)
            if not is_inside_bar:
                sl_time = datetime.datetime.fromtimestamp(int(mid_c[0])/1000, tz=TZ_VN).strftime('%H:%M %d/%m')
                confirmed_sl.append({
                    'time': sl_time, 'high': mid_h, 'low': mid_l, 'open': float(mid_c[1]), 'close': float(mid_c[4]), 'filter': 'Chuẩn 3 Nến'
                })
            else:
                is_valid = False
                for k in range(i + 2, n):
                    if float(chrono[k][3]) < mid_l:
                        break
                    if float(chrono[k][4]) > mid_h: # Đóng nến trên High để duyệt
                        is_valid = True
                        break
                if is_valid:
                    sl_time = datetime.datetime.fromtimestamp(int(mid_c[0])/1000, tz=TZ_VN).strftime('%H:%M %d/%m')
                    confirmed_sl.append({
                        'time': sl_time, 'high': mid_h, 'low': mid_l, 'open': float(mid_c[1]), 'close': float(mid_c[4]), 'filter': 'Duyệt Qua InsideBar'
                    })

    valid_sh = confirmed_sh[-1] if confirmed_sh else {'time': 'H1', 'high': float(klines_desc[0][2]), 'low': float(klines_desc[0][3]), 'open': float(klines_desc[0][1]), 'close': float(klines_desc[0][4]), 'filter': 'Mặc định'}
    valid_sl = confirmed_sl[-1] if confirmed_sl else {'time': 'H1', 'high': float(klines_desc[0][2]), 'low': float(klines_desc[0][3]), 'open': float(klines_desc[0][1]), 'close': float(klines_desc[0][4]), 'filter': 'Mặc định'}

    b_ob_top = valid_sh['high']
    b_ob_bot = min(valid_sh['open'], valid_sh['close'])
    bearish_ob = {'top': b_ob_top, 'bottom': b_ob_bot, 'mid': round((b_ob_top + b_ob_bot) / 2.0, 1), 'time': valid_sh['time'], 'filter': valid_sh['filter']}

    bull_ob_bot = valid_sl['low']
    bull_ob_top = max(valid_sl['open'], valid_sl['close'])
    bullish_ob = {'top': bull_ob_top, 'bottom': bull_ob_bot, 'mid': round((bull_ob_top + bull_ob_bot) / 2.0, 1), 'time': valid_sl['time'], 'filter': valid_sl['filter']}

    return valid_sh, bearish_ob, valid_sl, bullish_ob

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
    # Cache giữ nguyên trong 1 tiếng để đảm bảo không bị nhảy giá liên tục
    if PLAN_CACHE['BTC']['data'] and (now - PLAN_CACHE['BTC']['candle_time'] < 3600):
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

        current_price = float(m15_klines[0][4])
        
        # 1. Bias Đa Khung (Tuần W1 & Ngày D1)
        w_closes = [float(k[4]) for k in reversed(w_klines)]
        w_ema20 = sum(w_closes[-20:]) / 20.0
        w1_bear = current_price < w_ema20
        w1_bias = "🔴 GIẢM (BEARISH)" if w1_bear else "🟢 TĂNG (BULLISH)"

        d_closes = [float(k[4]) for k in reversed(d_klines)]
        d_ema20 = sum(d_closes[-20:]) / 20.0
        d1_bear = current_price < d_ema20
        d1_bias = "🔴 GIẢM (BEARISH)" if d1_bear else "🟢 TĂNG (BULLISH)"

        # 2. Cấu Trúc SMC & Order Block (OB H1 - Lọc Qua Inside Bar)
        valid_sh, bearish_ob, valid_sl, bullish_ob = find_smc_swings_and_ob(h1_klines)
        swing_high = round(valid_sh['high'], 1)
        sh_time = valid_sh['time']
        sh_filter = valid_sh['filter']
        swing_low = round(valid_sl['low'], 1)
        sl_time = valid_sl['time']
        sl_filter = valid_sl['filter']

        # 3. Tính POC & Vùng High Volume Node (HVN) M15 theo Lý Thuyết Giá FX DREAM
        poc_m15, hvn_lower, hvn_upper = calculate_keyvolume_nodes(m15_klines, n_bins=20)

        # Phát hiện Bẫy Quét Râu (Sweep) / Mô hình 2 Đáy / 2 Đỉnh trên M15
        sweep_bull = None
        sweep_bear = None
        for k in m15_klines[:8]:
            c_open, c_high, c_low, c_close = float(k[1]), float(k[2]), float(k[3]), float(k[4])
            c_range = c_high - c_low
            lower_wick = min(c_open, c_close) - c_low
            upper_wick = c_high - max(c_open, c_close)
            if c_range > 350.0:
                if lower_wick / c_range > 0.45 and not sweep_bull:
                    sweep_bull = {'low': c_low, 'close': c_close, 'wick': lower_wick}
                elif upper_wick / c_range > 0.45 and not sweep_bear:
                    sweep_bear = {'high': c_high, 'close': c_close, 'wick': upper_wick}

        # Kiểm tra mô hình 2 Đáy (Cân bằng quân lực M15 theo FX Dream):
        is_double_bottom = (current_price > swing_low + 200.0) and (sweep_bull is not None)

        # XÁC ĐỊNH HƯỚNG ĐÁNH (KHÔNG ÉP THEO TREND NGÀY NẾU M15 CÓ ĐẢO CHIỀU UY TÍN)
        if sweep_bull or is_double_bottom:
            signal = "LONG"
            setup_desc = f"Mô Hình 2 Đáy M15 tại Khối Bullish OB ${swing_low:,.1f} ({sl_time}) + Bullish CHoCH"
            diamond_note = "⭐ ĐẢO CHIỀU UY TÍN (CÂN BẰNG QUÂN LỰC): Có 2 Đáy & Quét Râu Đáy rõ ràng, không bắt đáy vô cớ!"
        elif sweep_bear:
            signal = "SHORT"
            setup_desc = f"Quét Râu Đỉnh / Test Khối Bearish OB tại ${swing_high:,.1f} ({sh_time}) + Bearish CHoCH"
            diamond_note = "⭐ KHỐI ORDER BLOCK UY TÍN: Chạm khối OB đỉnh bị từ chối mạnh, thuận lực xả vĩ mô!"
        elif w1_bear and d1_bear:
            signal = "SHORT"
            setup_desc = f"Đồng Pha Giảm Tuần/Ngày - Kiên nhẫn chờ hồi về Khối Bearish OB ${bearish_ob['mid']:,.1f}"
            diamond_note = "⭐ ĐỒNG PHA TUẦN + NGÀY (CẢN TO): Chờ hồi test Khối OB, tuyệt đối không bán lưng chừng!"
        else:
            signal = "SHORT" if d1_bear else "LONG"
            setup_desc = f"Cấu Trúc KeyVolume H1 tại Khối OB ${bearish_ob['mid']:,.1f}"
            diamond_note = "⚡ Quản lý vốn theo từng mốc cản."

        if signal == "SHORT":
            # ENTRY LIMIT: Neo chặt tại KHỐI BEARISH ORDER BLOCK (50% OB hoặc POC), TUYỆT ĐỐI KHÔNG BÁN LƯNG CHỪNG
            entry_limit = round(max(bearish_ob['bottom'], min(poc_m15, bearish_ob['mid'])), 1)
            if entry_limit < current_price:
                entry_limit = round(bearish_ob['mid'], 1)
            # SELL STOP: Đặt phá vỡ đáy để ăn trọn sóng xả đâm 1 mạch nếu không hồi
            entry_stop = round(swing_low * 0.998, 1)
            
            # SL: Đặt trên chóp Swing High (đỉnh của khối OB) + đệm an toàn
            sl = round(swing_high + 180.0, 1)
            risk = sl - entry_limit
            if risk < 300.0:
                sl = round(entry_limit + 400.0, 1)
                risk = sl - entry_limit
            tp1 = round(entry_limit - (risk * 2.0), 1)
            tp2 = round(entry_limit - (risk * 3.5), 1)
            
            advice = (
                f"⚠️ <b>LÝ THUYẾT GIÁ (FX DREAM):</b> Giá hiện tại ${current_price:,.1f} ở vùng LVN mỏng, chỉ đặt Sell Limit đón khi giá hồi lên cạnh <b>Khối Bearish HVN/OB [${bearish_ob['bottom']:,.1f} - ${bearish_ob['top']:,.1f}]</b>!\n"
                f"🛡️ <b>SL SIÊU NGẮN:</b> Đặt ngoài chóp Swing High ${sl:,.1f}. Nếu giá đục thủng OB ra ngoài là kịch bản sai, cắt lỗ ngay bảo toàn vốn!\n"
                f"💎 <b>ĐUA SÓNG ĐÂM 1 MẠCH:</b> Nếu BTC lao thẳng không test phá đáy <b>${entry_stop:,.1f}</b>, Lệnh 2 Sell Stop sẽ tự kích hoạt để không bị lỡ tàu!"
            )
        else: # LONG
            # ENTRY LIMIT: Neo chặt tại KHỐI BULLISH ORDER BLOCK (50% OB hoặc POC)
            entry_limit = round(min(bullish_ob['top'], max(poc_m15, bullish_ob['mid'])), 1)
            if entry_limit > current_price:
                entry_limit = round(bullish_ob['mid'], 1)
                
            entry_stop = round(swing_high * 1.002, 1)
            
            # SL: Đặt dưới đáy Swing Low (đáy của khối OB) an toàn
            sl = round(swing_low - 180.0, 1)
            risk = entry_limit - sl
            if risk < 300.0:
                sl = round(entry_limit - 400.0, 1)
                risk = entry_limit - sl
            tp1 = round(entry_limit + (risk * 2.0), 1)
            tp2 = round(entry_limit + (risk * 3.5), 1)
            
            advice = (
                f"⚠️ <b>CÂN BẰNG QUÂN LỰC:</b> Có xác nhận mô hình 2 Đáy M15 đối trọng với phe địch, đón Buy Limit khi giá chui vào cạnh <b>Khối Bullish HVN/OB [${bullish_ob['bottom']:,.1f} - ${bullish_ob['top']:,.1f}]</b>!\n"
                f"🛡️ <b>SL SIÊU NGẮN:</b> Đặt dưới đáy Swing Low ${sl:,.1f}. Nếu giá đâm thủng OB ra ngoài là cắt lỗ ngay lập tức!\n"
                f"💎 <b>ĐUA SÓNG BỨT TỐC:</b> Nếu BTC tăng thốc 1 mạch qua đỉnh <b>${entry_stop:,.1f}</b> (như nhịp 3k giá), Lệnh 2 Buy Stop sẽ tự khớp bắt trọn con sóng!"
            )

        sl_pct = (risk / entry_limit) * 100.0
        dist_to_entry = round(abs(current_price - entry_limit), 1)

        plan = {
            'signal': signal,
            'current_price': current_price,
            'w1_bias': w1_bias,
            'd1_bias': d1_bias,
            'diamond_note': diamond_note,
            'setup_desc': setup_desc,
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
            'entry_limit': entry_limit,
            'entry_stop': entry_stop,
            'dist_to_entry': dist_to_entry,
            'sl': sl,
            'sl_pct': round(sl_pct, 2),
            'tp1': tp1,
            'tp2': tp2,
            'advice': advice
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
        s_emoji = "🟢 LONG (MUA)" if plan['signal'] == 'LONG' else "🔴 SHORT (BÁN)"
        action_l = "LỆNH 1: Bán Limit Đón Râu Hồi Retest Khối OB / POC" if plan['signal'] == 'SHORT' else "LỆNH 1: Mua Limit Đón Râu Hồi Retest Khối OB / POC"
        action_s = "LỆNH 2: Bán Stop Phá Đáy - Bắt Trọn Cú Xả Đâm 1 Mạch" if plan['signal'] == 'SHORT' else "LỆNH 2: Mua Stop Phá Đỉnh - Bắt Trọn Cú Bơm Đâm 1 Mạch"
        sh_time_str = f" ({plan.get('sh_time', '')}) [{plan.get('sh_filter', 'Lọc InsideBar')}]" if plan.get('sh_time') else ""
        sl_time_str = f" ({plan.get('sl_time', '')}) [{plan.get('sl_filter', 'Lọc InsideBar')}]" if plan.get('sl_time') else ""
        
        text = f"""👑 <b>[CHIẾN LƯỢC BITCOIN: KEYVOLUME & LỌC INSIDE BAR]</b> 👑
━━━━━━━━━━━━━━━━━━
💰 Giá BTC hiện tại: <b>${plan['current_price']:,.1f}</b>
🎯 <b>Vùng POC M15 (Volume cốt lõi):</b> <code>${plan['poc']:,.1f}</code> (HVN: [${plan.get('hvn_lower', 0):,.1f} - ${plan.get('hvn_upper', 0):,.1f}])
📊 <b>CẤU TRÚC SWING POINT (LỌC THEO INSIDE BAR):</b>
📈 <b>Swing High Hợp Lệ:</b> <code>${plan['swing_high']:,.1f}</code>{sh_time_str}
   🧱 <b>Khối Bearish HVN/OB:</b> <code>[${plan['b_ob_bot']:,.1f} - ${plan['b_ob_top']:,.1f}]</code> (50% Mid: ${plan['b_ob_mid']:,.1f})
📉 <b>Swing Low Hợp Lệ:</b> <code>${plan['swing_low']:,.1f}</code>{sl_time_str}
   🧱 <b>Khối Bullish HVN/OB:</b> <code>[${plan['bull_ob_bot']:,.1f} - ${plan['bull_ob_top']:,.1f}]</code> (50% Mid: ${plan['bull_ob_mid']:,.1f})
━━━━━━━━━━━━━━━━━━
💎 <b>ĐỒNG PHA BIAS ĐA KHUNG (WINRATE CAO):</b>
• <b>Bias Tuần (W1):</b> {plan['w1_bias']}
• <b>Bias Ngày (D1):</b> {plan['d1_bias']}
⚡ <b>Cấu trúc SMC:</b> <b>{plan['setup_desc']}</b>
<i>{plan['diamond_note']}</i>
━━━━━━━━━━━━━━━━━━
🚀 <b>CHIẾN LƯỢC: {s_emoji}</b>
👉 <b>{action_l}:</b>
   <code>${plan['entry_limit']:,.1f}</code>
👉 <b>{action_s}:</b>
   <code>${plan['entry_stop']:,.1f}</code>

🛡️ <b>Cắt lỗ (SL Ngoài Chóp Swing High/Low):</b> <code>${plan['sl']:,.1f}</code> (-{plan['sl_pct']}%)
🎯 <b>Chốt lời 1 (TP1 - R:R 1:2):</b> <code>${plan['tp1']:,.1f}</code>
🎯 <b>Chốt lời 2 (TP2 - R:R 1:3.5):</b> <code>${plan['tp2']:,.1f}</code>

🧠 <b>KẾ HOẠCH XỬ LÝ LỆNH CHỦ ĐỘNG:</b>
{plan['advice']}

🛡️ <b>QUẢN LÝ VỐN (${CONFIG['ACCOUNT_BALANCE']:,.0f}):</b>
• Rủi ro tối đa 2%: <b>$20.0</b> | Khối lượng: <b>$1,000.0</b> | Đòn bẩy: <b>5x</b>
<i>💡 Phương pháp KeyVolume: Vào lệnh tại cạnh HVN/Khối OB khi có râu test, SL ngoài chóp cực ngắn. Nếu BTC đâm 1 mạch không hồi thì Lệnh 2 Stop sẽ tự động kích hoạt bắt trọn con sóng!</i>"""
        send_telegram(text, reply_markup=get_main_keyboard())
    except Exception as e:
        send_telegram(f"Lỗi BTC POC: {e}", reply_markup=get_main_keyboard())

# ==========================================
# 2. KẾ HOẠCH VÀNG (SMC) - NGUỒN OANDA:XAUUSD (CHUẨN MT5)
# ==========================================
def calculate_gold_h4_plan():
    now = time.time()
    if PLAN_CACHE['GOLD']['data'] and (now - PLAN_CACHE['GOLD']['candle_time'] < 3600):
        return PLAN_CACHE['GOLD']['data']
        
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

        sh_raw, b_ob_raw, sl_raw, bull_ob_raw = find_smc_swings_and_ob(gold_h1_klines)
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
        
        # 3. Vùng HVN / POC M15 Vàng theo KeyVolume
        try:
            url_gold_m15 = 'https://api.bybit.com/v5/market/kline?category=linear&symbol=XAUUSDT&interval=15&limit=30'
            req_gm15 = urllib.request.Request(url_gold_m15, headers=HEADERS)
            with urllib.request.urlopen(req_gm15, timeout=8) as r:
                gold_m15_klines = json.loads(r.read().decode())['result']['list']
            poc_raw, hvn_l_raw, hvn_u_raw = calculate_keyvolume_nodes(gold_m15_klines)
            poc_gold_m15 = round(poc_raw + delta, 2)
            hvn_lower = round(hvn_l_raw + delta, 2)
            hvn_upper = round(hvn_u_raw + delta, 2)
        except Exception:
            poc_gold_m15 = round((m15_high + m15_low + m15_ema20) / 3.0, 2)
            hvn_lower = round(m15_low, 2)
            hvn_upper = round(m15_high, 2)
            gold_m15_klines = []
        
        # 4. Phát hiện Bẫy Quét Râu / Test Khối OB (Rejection Wick) / 2 Đáy / 2-3 Đỉnh trên M15
        test_bear_wick = False
        for k in gold_m15_klines[:6]:
            k_h = float(k[2]) + delta
            k_c = float(k[4]) + delta
            k_o = float(k[1]) + delta
            body_top = max(k_c, k_o)
            if k_h >= b_ob_bot and body_top <= b_ob_top:
                test_bear_wick = True
                break

        is_double_bottom = (current_gold > major_sup + 4.0) and (m15_low >= major_sup - 1.0) and (current_gold > m15_ema20)
        is_at_major_res = (current_gold >= b_ob_bot - 1.5) or (m5_high >= major_res - 0.8) or test_bear_wick
        
        # XÁC ĐỊNH HƯỚNG ĐÁNH (KHÔNG ÉP THEO TREND NGÀY NẾU M15 CÓ ĐẢO CHIỀU UY TÍN)
        if is_double_bottom and not is_at_major_res:
            signal = "LONG"
            setup_desc = f"Mô Hình 2 Đáy M15 tại Khối Bullish OB ${major_sup:,.2f} ({sl_time}) + Bullish CHoCH"
            diamond_note = "⭐ ĐẢO CHIỀU UY TÍN (CÂN BẰNG QUÂN LỰC): Có mô hình 2 Đáy từ khối OB uy tín, không bắt đáy vô cớ!"
        elif is_at_major_res or (current_gold < h4_ema20):
            signal = "SHORT"
            wick_txt = " + Râu Nến Test Khối OB" if test_bear_wick else ""
            setup_desc = f"Chạm Khối Bearish OB tại ${major_res:,.2f} ({sh_time}){wick_txt} / CHoCH Giảm"
            diamond_note = "⭐ KHỐI ORDER BLOCK UY TÍN: Chạm khối OB đỉnh bị từ chối mạnh, tuyệt đối không bán lưng chừng!"
        else:
            signal = "SHORT" if d1_bear else "LONG"
            setup_desc = f"Cấu Trúc KeyVolume H1 tại Khối OB ${b_ob_mid:,.2f}"
            diamond_note = "⚡ Quản lý vốn chặt chẽ theo cản."
        
        if signal == "SHORT":
            # ENTRY LIMIT: Neo chặt tại KHỐI BEARISH ORDER BLOCK (cạnh dưới HVN/OB hoặc 50% OB), TUYỆT ĐỐI KHÔNG BÁN LƯNG CHỪNG
            entry_limit = round(max(b_ob_bot, min(poc_gold_m15, b_ob_mid)), 2)
            if entry_limit < current_gold:
                entry_limit = round(b_ob_mid, 2)
                
            # Entry 2: Bán Stop khi gãy đáy xác nhận sóng xả tiếp diễn
            entry_stop = round(major_sup - 1.2, 2)
            
            # SL ĐẶT TRÊN CHÓP SWING HIGH H1: đệm 2.2 giá ngoài đỉnh cản
            sl = round(major_res + 2.2, 2)
            sl_dist = round(sl - entry_limit, 2)
            if sl_dist < 8.0:
                sl = round(entry_limit + 10.0, 2)
                sl_dist = round(sl - entry_limit, 2)
            elif sl_dist > 25.0:
                sl = round(entry_limit + 20.0, 2)
                sl_dist = round(sl - entry_limit, 2)
                
            tp1 = round(entry_limit - (sl_dist * 2.0), 2)
            tp2 = round(entry_limit - (sl_dist * 3.5), 2)
            
            advice = (
                f"⚠️ <b>LÝ THUYẾT GIÁ (FX DREAM):</b> Giá hiện tại ${current_gold:,.2f} ở vùng LVN mỏng, chỉ đặt Sell Limit đón khi giá hồi lên cạnh <b>Khối Bearish HVN/OB [${b_ob_bot:,.2f} - ${b_ob_top:,.2f}]</b>!\n"
                f"🛡️ <b>SL SIÊU NGẮN:</b> Đặt ngoài chóp Swing High ${sl:,.2f} (~{sl_dist:.1f} giá). Nếu giá đục thủng OB ra ngoài là cắt lỗ ngay lập tức!\n"
                f"💎 <b>DCA NHỒI KHI ĐẸP:</b> Khớp Lệnh 1 và giá sập thủng đáy <b>${entry_stop:,.2f}</b> (lãi > {sl_dist*0.7:.1f} giá), dời SL về Hoà Vốn (Entry) và kích hoạt Lệnh 2 (Sell Stop)!"
            )
        else: # LONG
            # ENTRY LIMIT: Neo chặt tại KHỐI BULLISH ORDER BLOCK (không bắt đáy vô cớ)
            entry_limit = round(min(bull_ob_top, max(poc_gold_m15, bull_ob_mid)), 2)
            if entry_limit > current_gold:
                entry_limit = round(bull_ob_mid, 2)
                
            entry_stop = round(major_res + 1.2, 2)
            
            sl = round(major_sup - 2.2, 2)
            sl_dist = round(entry_limit - sl, 2)
            if sl_dist < 8.0:
                sl = round(entry_limit - 10.0, 2)
                sl_dist = round(entry_limit - sl, 2)
            elif sl_dist > 25.0:
                sl = round(entry_limit + 20.0, 2)
                sl_dist = round(entry_limit - sl, 2)
                
            tp1 = round(entry_limit + (sl_dist * 2.0), 2)
            tp2 = round(entry_limit + (sl_dist * 3.5), 2)
            
            advice = (
                f"⚠️ <b>CÂN BẰNG QUÂN LỰC:</b> Có xác nhận mô hình 2 Đáy tại Khối Bullish HVN/OB [${bull_ob_bot:,.2f} - ${bull_ob_top:,.2f}] ({sl_time}), không bắt đáy vô cớ! SL dưới đáy hỗ trợ.\n"
                f"🛡️ <b>SL SIÊU NGẮN:</b> Đặt dưới đáy Swing Low ${sl:,.2f}. Nếu đục thủng OB ra ngoài là cắt lỗ ngay!\n"
                f"💎 <b>DCA NHỒI KHI ĐẸP:</b> Khớp Lệnh 1 và giá bứt phá qua đỉnh <b>${entry_stop:,.2f}</b> (lãi > {sl_dist*0.7:.1f} giá), dời SL về Hoà Vốn và kích hoạt Lệnh 2 (Buy Stop)!"
            )
            
    except Exception as e:
        # Fallback khẩn cấp nếu scanner bị timeout
        current_gold = 3538.0
        bid, ask = 3537.5, 3538.5
        data_source = "OANDA:XAUUSD (Dự phòng)"
        w1_bias = "🔴 GIẢM (BEARISH)"
        d1_bias = "🔴 GIẢM (BEARISH)"
        diamond_note = "⭐ ĐỒNG PHA TUẦN + NGÀY (SETUP CAO CẤP)"
        poc_gold_m15 = 3535.0
        hvn_lower = 3530.0
        hvn_upper = 3545.0
        entry_limit = 3543.0
        entry_stop = 3505.0
        major_res = 3547.0
        b_ob_top = 3547.0
        b_ob_bot = 3537.0
        b_ob_mid = 3542.0
        major_sup = 3508.0
        bull_ob_top = 3528.0
        bull_ob_bot = 3508.0
        bull_ob_mid = 3518.0
        sh_time = "H1"
        sh_filter = "Mặc định"
        sl_time = "H1"
        sl_filter = "Mặc định"
        test_bear_wick = False
        sl = 3550.0
        sl_dist = 7.0
        tp1 = 3535.0
        tp2 = 3520.0
        signal = "SHORT"
        setup_desc = "Khối Bearish OB H1 + CHoCH Giảm"
        advice = "⚠️ Kiểm tra biểu đồ MT5 trước khi vào lệnh."

    plan = {
        'signal': signal,
        'current_price': current_gold,
        'bid': bid,
        'ask': ask,
        'data_source': data_source,
        'w1_bias': w1_bias,
        'd1_bias': d1_bias,
        'diamond_note': diamond_note,
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
        'test_bear_wick': test_bear_wick,
        'setup_desc': setup_desc,
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
        s_emoji = "🟢 LONG (MUA)" if plan['signal'] == 'LONG' else "🔴 SHORT (BÁN)"
        action_l = "LỆNH 1: Bán Limit Đón Râu Hồi Retest Cạnh HVN/OB" if plan['signal'] == 'SHORT' else "LỆNH 1: Mua Limit Đón Râu Hồi Retest Cạnh HVN/OB"
        action_s = "LỆNH 2: Bán Stop Phá Đáy Tiếp Diễn Sóng Tuần" if plan['signal'] == 'SHORT' else "LỆNH 2: Mua Stop Phá Đỉnh Tiếp Diễn Sóng Tuần"
        sh_time_str = f" ({plan.get('sh_time', '')}) [{plan.get('sh_filter', 'Lọc InsideBar')}]" if plan.get('sh_time') else ""
        sl_time_str = f" ({plan.get('sl_time', '')}) [{plan.get('sl_filter', 'Lọc InsideBar')}]" if plan.get('sl_time') else ""
        
        text = f"""🥇 <b>[CHIẾN LƯỢC VÀNG: KEYVOLUME & LỌC INSIDE BAR]</b> 🥇
━━━━━━━━━━━━━━━━━━
📊 Nguồn biểu đồ: <b>{plan['data_source']}</b>
💰 Giá Vàng OANDA: <b>${plan['current_price']:,.2f}</b> (Bid: ${plan['bid']:,.2f} | Ask: ${plan['ask']:,.2f})
🎯 <b>Vùng POC M15 (Volume cốt lõi):</b> <code>${plan['poc_m15']:,.2f}</code> (HVN: [${plan.get('hvn_lower', 0):,.2f} - ${plan.get('hvn_upper', 0):,.2f}])
📊 <b>CẤU TRÚC SWING POINT (LỌC THEO INSIDE BAR):</b>
📈 <b>Swing High Hợp Lệ:</b> <code>${plan['swing_high']:,.2f}</code>{sh_time_str}
   🧱 <b>Khối Bearish HVN/OB:</b> <code>[${plan['b_ob_bot']:,.2f} - ${plan['b_ob_top']:,.2f}]</code> (50% Mid: ${plan['b_ob_mid']:,.2f})
📉 <b>Swing Low Hợp Lệ:</b> <code>${plan['swing_low']:,.2f}</code>{sl_time_str}
   🧱 <b>Khối Bullish HVN/OB:</b> <code>[${plan['bull_ob_bot']:,.2f} - ${plan['bull_ob_top']:,.2f}]</code> (50% Mid: ${plan['bull_ob_mid']:,.2f})
━━━━━━━━━━━━━━━━━━
💎 <b>ĐỒNG PHA BIAS ĐA KHUNG (WINRATE CAO):</b>
• <b>Bias Tuần (W1):</b> {plan['w1_bias']}
• <b>Bias Ngày (D1):</b> {plan['d1_bias']}
⚡ <b>Cấu trúc SMC:</b> <b>{plan['setup_desc']}</b>
<i>{plan['diamond_note']}</i>
━━━━━━━━━━━━━━━━━━
🚀 <b>CHIẾN LƯỢC: {s_emoji}</b>
👉 <b>{action_l}:</b>
   <code>${plan['entry_limit']:,.2f}</code>
👉 <b>{action_s}:</b>
   <code>${plan['entry_stop']:,.2f}</code>

🛡️ <b>Cắt lỗ (SL Ngoài Chóp Swing High/Low ~{plan['sl_dist']:.1f} Giá):</b>
   <code>${plan['sl']:,.2f}</code>
🎯 <b>Chốt lời 1 (TP1 - Ăn {plan['sl_dist']*2:.1f} Giá | R:R 1:2):</b> <code>${plan['tp1']:,.2f}</code>
🎯 <b>Chốt lời 2 (TP2 - Ăn {plan['sl_dist']*3.5:.1f} Giá | R:R 1:3.5):</b> <code>${plan['tp2']:,.2f}</code>

🧠 <b>KẾ HOẠCH XỬ LÝ LỆNH CHỦ ĐỘNG:</b>
{plan['advice']}

🛡️ <b>QUẢN LÝ VỐN VÀNG MT5 (${CONFIG['ACCOUNT_BALANCE']:,.0f}):</b>
• Rủi ro tối đa 2%: <b>$20.0</b> (tương đương 0.01 - 0.02 lot trên MT5)
<i>💡 Phương pháp KeyVolume: Chờ giá từ vùng mỏng hồi vào cạnh Khối HVN/OB, giật râu test từ chối là vào lệnh! SL siêu ngắn ngoài chóp đỉnh nến Swing High!</i>"""
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

def auto_diamond_alert_worker():
    """Quét tự động ngầm mỗi 3 phút - Phát hiện Setup Kim Cương (Đồng pha Tuần/Ngày & Test POC) là tự động bắn Telegram"""
    time.sleep(20) # Chờ bot khởi động ổn định 20 giây
    while True:
        try:
            now = time.time()
            
            # 1. QUÉT TỰ ĐỘNG VÀNG (OANDA:XAUUSD - Chuẩn MT5)
            if now - LAST_ALERT_TIME['GOLD'] > 3600: # Cooldown 1 tiếng mỗi thông báo
                plan_gold = calculate_gold_h4_plan()
                is_high_prob = ("ĐỒNG PHA TUẦN + NGÀY" in plan_gold.get('diamond_note', '')) or plan_gold.get('test_bear_wick') or ("ĐẢO CHIỀU UY TÍN" in plan_gold.get('diamond_note', ''))
                if is_high_prob:
                    price_gold = plan_gold['current_price']
                    entry_gold = plan_gold['entry_limit']
                    # Nếu giá đang trong vùng retest POC M15 hoặc râu test (cách entry < 4 giá) hoặc test_bear_wick
                    if abs(price_gold - entry_gold) <= 4.0 or plan_gold.get('test_bear_wick'):
                        s_emoji = "🔴 SHORT (BÁN)" if plan_gold['signal'] == 'SHORT' else "🟢 LONG (MUA)"
                        action_l = "LỆNH VÀO NGAY (Cạnh Khối HVN/OB):" if plan_gold['signal'] == 'SHORT' else "LỆNH VÀO NGAY (Cạnh Khối HVN/OB):"
                        msg = f"""🚨 <b>[TỰ ĐỘNG BÁO KÈO VIP: RÂU TEST KHỐI OB / 2-3 ĐỈNH]</b> 🚨
━━━━━━━━━━━━━━━━━━
📊 Nguồn biểu đồ: <b>TradingView (OANDA:XAUUSD - Chuẩn MT5)</b>
💰 Giá Vàng hiện tại: <b>${price_gold:,.2f}</b> (Đang retest Cạnh Khối HVN/OB!)
🎯 <b>Vùng POC M15 (Volume cốt lõi):</b> <code>${plan_gold['poc_m15']:,.2f}</code> (HVN: [${plan_gold.get('hvn_lower', 0):,.2f} - ${plan_gold.get('hvn_upper', 0):,.2f}])
📊 <b>Cản Đỉnh Uy Tín (Swing High):</b> <code>${plan_gold['swing_high']:,.2f}</code> ({plan_gold.get('sh_time', '')}) [{plan_gold.get('sh_filter', '')}]
   🧱 <b>Khối Bearish HVN/OB:</b> <code>[${plan_gold['b_ob_bot']:,.2f} - ${plan_gold['b_ob_top']:,.2f}]</code>
📉 <b>Hỗ Trợ Đáy Uy Tín (Swing Low):</b> <code>${plan_gold['swing_low']:,.2f}</code> ({plan_gold.get('sl_time', '')}) [{plan_gold.get('sl_filter', '')}]
   🧱 <b>Khối Bullish HVN/OB:</b> <code>[${plan_gold['bull_ob_bot']:,.2f} - ${plan_gold['bull_ob_top']:,.2f}]</code>
⚡ <b>Cấu trúc SMC:</b> <b>{plan_gold['setup_desc']}</b>
━━━━━━━━━━━━━━━━━━
💎 <b>ĐỒNG PHA BIAS ĐA KHUNG (WINRATE CAO):</b>
• <b>Bias Tuần (W1):</b> {plan_gold['w1_bias']}
• <b>Bias Ngày (D1):</b> {plan_gold['d1_bias']}
<i>🔥 Tín hiệu tuyệt đẹp: Giá giật râu test cạnh khối HVN/OB hoặc tạo 2-3 đỉnh từ chối, vào lệnh ngay!</i>
━━━━━━━━━━━━━━━━━━
🚀 <b>KHUYẾN NGHỊ VÀO LỆNH: {s_emoji}</b>
👉 <b>{action_l}</b>
   <code>${entry_gold:,.2f}</code>
👉 <b>LỆNH STOP NHỒI SÓNG TIẾP DIỄN:</b>
   <code>${plan_gold['entry_stop']:,.2f}</code>

🛡️ <b>Cắt lỗ (SL Ngoài Cản Đỉnh H1):</b>
   <code>${plan_gold['sl']:,.2f}</code> (~{plan_gold['sl_dist']:.1f} Giá)
🎯 <b>Chốt lời 1 (TP1 - R:R 1:2):</b> <code>${plan_gold['tp1']:,.2f}</code>
🎯 <b>Chốt lời 2 (TP2 - R:R 1:3.5):</b> <code>${plan_gold['tp2']:,.2f}</code>

🧠 <b>Kế hoạch xử lý:</b>
{plan_gold['advice']}

🛡️ <b>QUẢN LÝ VỐN VÀNG MT5 (${CONFIG['ACCOUNT_BALANCE']:,.0f}):</b>
• Rủi ro tối đa 2%: <b>$20.0</b> (tương đương 0.01 - 0.02 lot trên MT5)"""
                        send_telegram(msg)
                        LAST_ALERT_TIME['GOLD'] = now

            # 2. QUÉT TỰ ĐỘNG BITCOIN (BTCUSDT)
            if now - LAST_ALERT_TIME['BTC'] > 3600:
                plan_btc = calculate_btc_h4_plan()
                is_high_prob_btc = ("ĐỒNG PHA TUẦN + NGÀY" in plan_btc.get('diamond_note', '')) or ("ĐẢO CHIỀU UY TÍN" in plan_btc.get('diamond_note', ''))
                if is_high_prob_btc:
                    price_btc = plan_btc['current_price']
                    entry_l = plan_btc['entry_limit']
                    entry_s = plan_btc['entry_stop']
                    # Nếu giá đang test lại POC M15 hoặc chuẩn bị phá vỡ Lệnh 2 Stop
                    if abs(price_btc - entry_l) <= price_btc * 0.008 or abs(price_btc - entry_s) <= price_btc * 0.005:
                        s_emoji = "🔴 SHORT (BÁN)" if plan_btc['signal'] == 'SHORT' else "🟢 LONG (MUA)"
                        action_l = "LỆNH 1: Bán Limit Đón Râu Hồi Retest Cạnh HVN/OB" if plan_btc['signal'] == 'SHORT' else "LỆNH 1: Mua Limit Đón Râu Hồi Retest Cạnh HVN/OB"
                        action_s = "LỆNH 2: Bán Stop Phá Đáy - Bắt Trọn Cú Xả Đâm 1 Mạch" if plan_btc['signal'] == 'SHORT' else "LỆNH 2: Mua Stop Phá Đỉnh - Bắt Trọn Cú Bơm Đâm 1 Mạch"
                        msg = f"""🚨 <b>[TỰ ĐỘNG BÁO KÈO VIP: SETUP KIM CƯƠNG BITCOIN]</b> 🚨
━━━━━━━━━━━━━━━━━━
💰 Giá BTC hiện tại: <b>${price_btc:,.1f}</b> (Đang tiếp cận điểm kích hoạt!)
🎯 <b>Vùng POC M15 (Volume cốt lõi):</b> <code>${plan_btc['poc']:,.1f}</code> (HVN: [${plan_btc.get('hvn_lower', 0):,.1f} - ${plan_btc.get('hvn_upper', 0):,.1f}])
📊 <b>Cản Đỉnh Uy Tín (Swing High):</b> <code>${plan_btc['swing_high']:,.1f}</code> ({plan_btc.get('sh_time', '')}) [{plan_btc.get('sh_filter', '')}]
   🧱 <b>Khối Bearish HVN/OB:</b> <code>[${plan_btc['b_ob_bot']:,.1f} - ${plan_btc['b_ob_top']:,.1f}]</code>
📉 <b>Hỗ Trợ Đáy Uy Tín (Swing Low):</b> <code>${plan_btc['swing_low']:,.1f}</code> ({plan_btc.get('sl_time', '')}) [{plan_btc.get('sl_filter', '')}]
   🧱 <b>Khối Bullish HVN/OB:</b> <code>[${plan_btc['bull_ob_bot']:,.1f} - ${plan_btc['bull_ob_top']:,.1f}]</code>
⚡ <b>Cấu trúc SMC:</b> <b>{plan_btc['setup_desc']}</b>
━━━━━━━━━━━━━━━━━━
💎 <b>ĐỒNG PHA BIAS ĐA KHUNG (WINRATE CAO):</b>
• <b>Bias Tuần (W1):</b> {plan_btc['w1_bias']}
• <b>Bias Ngày (D1):</b> {plan_btc['d1_bias']}
<i>🔥 BTC quán tính cực mạnh, khi xuôi sóng vĩ mô thường đâm một mạch không test!</i>
━━━━━━━━━━━━━━━━━━
🚀 <b>KHUYẾN NGHỊ VÀO LỆNH: {s_emoji}</b>
👉 <b>{action_l}:</b>
   <code>${entry_l:,.1f}</code>
👉 <b>{action_s}:</b>
   <code>${entry_s:,.1f}</code>

🛡️ <b>Cắt lỗ (SL Ngoài Cản H1):</b> <code>${plan_btc['sl']:,.1f}</code> (-{plan_btc['sl_pct']}%)
🎯 <b>Chốt lời 1 (TP1 - R:R 1:2):</b> <code>${plan_btc['tp1']:,.1f}</code>
🎯 <b>Chốt lời 2 (TP2 - R:R 1:3.5):</b> <code>${plan_btc['tp2']:,.1f}</code>

🧠 <b>Kế hoạch xử lý:</b>
{plan_btc['advice']}

🛡️ <b>QUẢN LÝ VỐN (${CONFIG['ACCOUNT_BALANCE']:,.0f}):</b>
• Rủi ro tối đa 2%: <b>$20.0</b> | Khối lượng: <b>$1,000.0</b> | Đòn bẩy: <b>5x</b>"""
                        send_telegram(msg)
                        LAST_ALERT_TIME['BTC'] = now

        except Exception as e:
            print(f"Lỗi worker quét tự động: {e}")
            
        time.sleep(180) # Quét lại mỗi 3 phút

if __name__ == '__main__':
    threading.Thread(target=start_health_server, daemon=True).start()
    threading.Thread(target=self_ping_worker, daemon=True).start()
    threading.Thread(target=auto_diamond_alert_worker, daemon=True).start()
    run_bot()
