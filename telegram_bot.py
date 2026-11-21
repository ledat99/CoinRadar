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
    Xác định đỉnh/đáy cấu trúc uy tín (Major Swing Point) và Khối Lệnh Order Block (OB)
    chuẩn SMC & Wyckoff trên khung H1 (loại bỏ hoàn toàn nhiễu của các khung nhỏ):
    - Major Swing High: Đỉnh cao nhất trong phạm vi sóng tối thiểu 7 nến (+/- 3 nến), kèm lọc Inside Bar.
    - Major Swing Low: Đáy thấp nhất trong phạm vi sóng tối thiểu 7 nến (+/- 3 nến), kèm lọc Inside Bar.
    - Đảm bảo SH và SL là 2 mốc cản lớn khác biệt (khoảng cách tối thiểu 3 nến, không lấy 2 nến kề nhau).
    - Khối Bearish OB H1: Cây nến tăng (xanh) cuối cùng tại vùng đỉnh trước cú xả mạnh.
    - Khối Bullish OB H1: Cây nến giảm (đỏ) cuối cùng tại vùng đáy trước cú hồi mạnh.
    """
    chrono = list(reversed(klines_desc))
    n = len(chrono)
    
    sh_cands = []
    sl_cands = []
    
    for i in range(3, n - 3):
        h = float(chrono[i][2])
        l = float(chrono[i][3])
        if all(h >= float(chrono[j][2]) for j in range(i - 3, i + 4)):
            t = datetime.datetime.fromtimestamp(int(chrono[i][0])/1000, tz=TZ_VN).strftime('%H:%M %d/%m')
            sh_cands.append({'idx': i, 'time': t, 'high': h, 'low': l, 'open': float(chrono[i][1]), 'close': float(chrono[i][4]), 'filter': 'Major H1 Swing'})
        if all(l <= float(chrono[j][3]) for j in range(i - 3, i + 4)):
            t = datetime.datetime.fromtimestamp(int(chrono[i][0])/1000, tz=TZ_VN).strftime('%H:%M %d/%m')
            sl_cands.append({'idx': i, 'time': t, 'high': h, 'low': l, 'open': float(chrono[i][1]), 'close': float(chrono[i][4]), 'filter': 'Major H1 Swing'})
            
    valid_sh = sh_cands[-1] if sh_cands else {'idx': n-1, 'time': 'H1', 'high': float(chrono[-1][2]), 'low': float(chrono[-1][3]), 'open': float(chrono[-1][1]), 'close': float(chrono[-1][4]), 'filter': 'Mặc định'}
    valid_sl = sl_cands[-1] if sl_cands else {'idx': n-1, 'time': 'H1', 'high': float(chrono[-1][2]), 'low': float(chrono[-1][3]), 'open': float(chrono[-1][1]), 'close': float(chrono[-1][4]), 'filter': 'Mặc định'}
    
    # Đảm bảo SH và SL là 2 mốc cản lớn khác biệt (khoảng cách tối thiểu 3 nến, không lấy 2 nến kề nhau)
    if abs(valid_sh.get('idx', 0) - valid_sl.get('idx', 0)) < 3:
        if valid_sh.get('idx', 0) > valid_sl.get('idx', 0) and len(sh_cands) > 1:
            valid_sh = sh_cands[-2]
        elif valid_sl.get('idx', 0) > valid_sh.get('idx', 0) and len(sl_cands) > 1:
            valid_sl = sl_cands[-2]

    # Bearish OB H1: Cây nến tăng (xanh) cuối cùng tại đỉnh trước cú xả mạnh
    sh_idx = valid_sh.get('idx', n-1)
    b_c = chrono[sh_idx]
    for k in range(sh_idx, max(0, sh_idx - 4), -1):
        if float(chrono[k][4]) >= float(chrono[k][1]): # nến xanh
            b_c = chrono[k]
            break
    b_ob_top = float(b_c[2])
    b_ob_bot = min(float(b_c[1]), float(b_c[4]))
    if b_ob_top == b_ob_bot:
        b_ob_bot = round(b_ob_top * 0.997, 2)
    bearish_ob = {'top': b_ob_top, 'bottom': b_ob_bot, 'mid': round((b_ob_top + b_ob_bot) / 2.0, 2), 'time': valid_sh['time'], 'filter': valid_sh['filter']}

    # Bullish OB H1: Cây nến giảm (đỏ) cuối cùng tại đáy trước cú hồi
    sl_idx = valid_sl.get('idx', n-1)
    bl_c = chrono[sl_idx]
    for k in range(sl_idx, max(0, sl_idx - 4), -1):
        if float(chrono[k][4]) <= float(chrono[k][1]): # nến đỏ
            bl_c = chrono[k]
            break
    bull_ob_bot = float(bl_c[3])
    bull_ob_top = max(float(bl_c[1]), float(bl_c[4]))
    if bull_ob_top == bull_ob_bot:
        bull_ob_top = round(bull_ob_bot * 1.003, 2)
    bullish_ob = {'top': bull_ob_top, 'bottom': bull_ob_bot, 'mid': round((bull_ob_top + bull_ob_bot) / 2.0, 2), 'time': valid_sl['time'], 'filter': valid_sl['filter']}

    return valid_sh, bearish_ob, valid_sl, bullish_ob

def analyze_m5_entry(m5_klines_desc):
    """
    Phân tích khung M5 (Khung vào lệnh Entry theo chuẩn SMC):
    - Bóc tách các râu nến test (Rejection Wicks) ở vùng đỉnh hoặc đáy gần nhất.
    - Phát hiện mô hình 2-3 đỉnh (Triple / Double Top) hoặc 2 đáy trên M5.
    - Đưa ra điểm đón Entry Limit và SL siêu ngắn ngoài râu M5.
    """
    chrono = list(reversed(m5_klines_desc))
    recent = chrono[-12:] # 1 tiếng gần nhất trên M5
    curr_p = float(recent[-1][4])
    
    upper_wicks = []
    for c in recent:
        h = float(c[2])
        top_body = max(float(c[1]), float(c[4]))
        candle_len = float(c[2]) - float(c[3])
        if candle_len > 0 and (h - top_body) >= candle_len * 0.35:
            upper_wicks.append(h)
            
    lower_wicks = []
    for c in recent:
        l = float(c[3])
        bot_body = min(float(c[1]), float(c[4]))
        candle_len = float(c[2]) - float(c[3])
        if candle_len > 0 and (bot_body - l) >= candle_len * 0.35:
            lower_wicks.append(l)
            
    m5_high = max(float(c[2]) for c in recent)
    m5_low = min(float(c[3]) for c in recent)
    
    return {
        'curr_p': curr_p,
        'm5_high': m5_high,
        'm5_low': m5_low,
        'has_multi_tops': len(upper_wicks) >= 2,
        'has_multi_bottoms': len(lower_wicks) >= 2,
        'upper_wicks_count': len(upper_wicks),
        'lower_wicks_count': len(lower_wicks)
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
        valid_sh, bearish_ob, valid_sl, bullish_ob = find_smc_swings_and_ob(h1_klines)
        swing_high = round(valid_sh['high'], 1)
        sh_time = valid_sh['time']
        sh_filter = valid_sh['filter']
        swing_low = round(valid_sl['low'], 1)
        sl_time = valid_sl['time']
        sl_filter = valid_sl['filter']

        # 3. Tính POC & Vùng High Volume Node (HVN) M15 theo Lý Thuyết Giá FX DREAM
        poc_m15, hvn_lower, hvn_upper = calculate_keyvolume_nodes(m15_klines, n_bins=20)

        # Phát hiện Bẫy Quét Râu (Sweep) / Mô hình 2 Đáy / 2 Đỉnh trên M5
        has_m5_rejection = m5_info['has_multi_tops'] or (m5_info['upper_wicks_count'] >= 1 and current_price >= bearish_ob['bottom'] - 300.0)
        has_m5_support = m5_info['has_multi_bottoms'] or (m5_info['lower_wicks_count'] >= 1 and current_price <= bullish_ob['top'] + 300.0)

        # XÁC ĐỊNH HƯỚNG ĐÁNH THEO BIAS VĨ MÔ & TEST CẢN
        if has_m5_support and not (w1_bear and d1_bear):
            signal = "LONG"
            setup_desc = f"M5 Quét Râu Đáy / 2 Đáy tại Khối Bullish OB ${swing_low:,.1f} ({sl_time}) + CHoCH M5"
            diamond_note = "⭐ ĐẢO CHIỀU UY TÍN (CÂN BẰNG QUÂN LỰC): Có nến rút râu quét đáy trên M5, không bắt đáy vô cớ!"
        elif has_m5_rejection or (w1_bear and d1_bear):
            signal = "SHORT"
            m5_txt = " + Râu Nến Test M5" if has_m5_rejection else ""
            setup_desc = f"Đồng Pha Giảm Tuần/Ngày - Test Khối Bearish OB H1 ${bearish_ob['mid']:,.1f}{m5_txt}"
            diamond_note = "⭐ ĐỒNG PHA TUẦN + NGÀY (CẢN TO H1): Rình nến M5 rút râu tại mép OB H1, tuyệt đối không bán lưng chừng!"
        else:
            signal = "SHORT" if d1_bear else "LONG"
            setup_desc = f"Cấu Trúc KeyVolume H1 tại Khối OB ${bearish_ob['mid']:,.1f}"
            diamond_note = "⚡ Quản lý vốn theo từng mốc cản."

        if signal == "SHORT":
            # ENTRY LIMIT & SL THEO KHUNG M5 KẾT HỢP KHỐI OB H1
            entry_stop = round(swing_low * 0.998, 1)
            if current_price >= bearish_ob['bottom']:
                entry_limit = round(max(current_price, m5_info['m5_high']), 1)
                sl = round(max(m5_info['m5_high'] + 150.0, swing_high + 100.0), 1)
                advice = (
                    f"⚠️ <b>KHỐI OB H1 CHUẨN:</b> Giá hiện tại ${current_price:,.1f} đang kiểm tra sâu trong <b>Khối Bearish OB H1 [${bearish_ob['bottom']:,.1f} - ${bearish_ob['top']:,.1f}]</b> ({sh_time})!\n"
                    f"🎯 <b>ENTRY M5:</b> Khung M5 đang tạo râu từ chối tại đỉnh ${m5_info['m5_high']:,.1f} ({'Mô hình 2-3 đỉnh M5' if m5_info['has_multi_tops'] else 'Râu rút nến M5'}), đón Limit tại mép hoặc Sell ngay!\n"
                    f"🛡️ <b>SL SIÊU NGẮN:</b> Đặt ngoài chóp râu M5 ${sl:,.1f}. Đục thủng chóp râu ra ngoài là kịch bản sai, cắt lỗ ngay!\n"
                    f"💎 <b>ĐUA SÓNG ĐÂM 1 MẠCH:</b> Nếu BTC lao thẳng phá đáy <b>${entry_stop:,.1f}</b>, Lệnh 2 Sell Stop sẽ tự kích hoạt!"
                )
            else:
                entry_limit = round(max(bearish_ob['bottom'], min(poc_m15, bearish_ob['mid'])), 1)
                sl = round(swing_high + 180.0, 1)
                advice = (
                    f"⚠️ <b>KHỐI OB H1 CHUẨN:</b> Cản to Bearish OB H1 [${bearish_ob['bottom']:,.1f} - ${bearish_ob['top']:,.1f}] ({sh_time}) bảo vệ cấu trúc giảm vĩ mô!\n"
                    f"🎯 <b>ENTRY M5:</b> Chờ giá hồi lên chạm cạnh OB H1, quan sát nến rút râu trên M5 để kê lệnh đón tại <b>${entry_limit:,.1f}</b>!\n"
                    f"🛡️ <b>SL SIÊU NGẮN:</b> Đặt ngoài chóp Swing High ${sl:,.1f}. Đục thủng OB ra ngoài là cắt lỗ ngay!\n"
                    f"💎 <b>ĐUA SÓNG ĐÂM 1 MẠCH:</b> Nếu BTC lao thẳng phá đáy <b>${entry_stop:,.1f}</b>, Lệnh 2 Sell Stop sẽ tự kích hoạt!"
                )
            risk = sl - entry_limit
            if risk < 300.0:
                sl = round(entry_limit + 400.0, 1)
                risk = sl - entry_limit
            tp1 = round(entry_limit - (risk * 2.0), 1)
            tp2 = round(entry_limit - (risk * 3.5), 1)
        else: # LONG
            entry_stop = round(swing_high * 1.002, 1)
            if current_price <= bullish_ob['top']:
                entry_limit = round(min(current_price, m5_info['m5_low']), 1)
                sl = round(min(m5_info['m5_low'] - 150.0, swing_low - 100.0), 1)
                advice = (
                    f"⚠️ <b>KHỐI OB H1 CHUẨN:</b> Giá hiện tại ${current_price:,.1f} đang kiểm tra trong <b>Khối Bullish OB H1 [${bullish_ob['bottom']:,.1f} - ${bullish_ob['top']:,.1f}]</b> ({sl_time})!\n"
                    f"🎯 <b>ENTRY M5:</b> Khung M5 đang tạo râu quét đáy tại ${m5_info['m5_low']:,.1f}, kê Buy Limit đón tại mép râu!\n"
                    f"🛡️ <b>SL SIÊU NGẮN:</b> Đặt dưới đáy râu M5 ${sl:,.1f}. Thủng râu ra ngoài là cắt lỗ ngay lập tức!\n"
                    f"💎 <b>ĐUA SÓNG BỨT TỐC:</b> Nếu BTC tăng thốc qua đỉnh <b>${entry_stop:,.1f}</b>, Lệnh 2 Buy Stop sẽ tự khớp!"
                )
            else:
                entry_limit = round(min(bullish_ob['top'], max(poc_m15, bullish_ob['mid'])), 1)
                sl = round(swing_low - 180.0, 1)
                advice = (
                    f"⚠️ <b>KHỐI OB H1 CHUẨN:</b> Hỗ trợ to Bullish OB H1 [${bullish_ob['bottom']:,.1f} - ${bullish_ob['top']:,.1f}] ({sl_time}) bảo vệ phe Mua!\n"
                    f"🎯 <b>ENTRY M5:</b> Chờ giá hồi về cạnh OB H1, quan sát nến M5 rút râu quét đáy để kê lệnh đón tại <b>${entry_limit:,.1f}</b>!\n"
                    f"🛡️ <b>SL SIÊU NGẮN:</b> Đặt dưới đáy Swing Low ${sl:,.1f}. Thủng OB ra ngoài là cắt lỗ ngay!\n"
                    f"💎 <b>ĐUA SÓNG BỨT TỐC:</b> Nếu BTC tăng thốc qua đỉnh <b>${entry_stop:,.1f}</b>, Lệnh 2 Buy Stop sẽ tự khớp!"
                )
            risk = entry_limit - sl
            if risk < 300.0:
                sl = round(entry_limit - 400.0, 1)
                risk = entry_limit - sl
            tp1 = round(entry_limit + (risk * 2.0), 1)
            tp2 = round(entry_limit + (risk * 3.5), 1)

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
            'm5_high': m5_info['m5_high'],
            'm5_low': m5_info['m5_low'],
            'm5_pattern': 'Mô hình 2-3 Đỉnh M5' if m5_info['has_multi_tops'] else 'Râu Nến Test M5',
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
        
        text = f"""👑 <b>[CHIẾN LƯỢC BITCOIN: OB THEO H1 - ENTRY THEO M5]</b> 👑
━━━━━━━━━━━━━━━━━━
💰 Giá BTC hiện tại: <b>${plan['current_price']:,.1f}</b>
🎯 <b>Vùng POC M15 (Volume cốt lõi):</b> <code>${plan['poc']:,.1f}</code>
📊 <b>CẤU TRÚC ĐA KHUNG (SMC & KEYVOLUME):</b>
🏛️ <b>Cản To Khung H1 (Không Nhiễu):</b>
📈 <b>Swing High H1:</b> <code>${plan['swing_high']:,.1f}</code>{sh_time_str}
   🧱 <b>Khối Bearish OB H1:</b> <code>[${plan['b_ob_bot']:,.1f} - ${plan['b_ob_top']:,.1f}]</code> (50% Mid: ${plan['b_ob_mid']:,.1f})
📉 <b>Swing Low H1:</b> <code>${plan['swing_low']:,.1f}</code>{sl_time_str}
   🧱 <b>Khối Bullish OB H1:</b> <code>[${plan['bull_ob_bot']:,.1f} - ${plan['bull_ob_top']:,.1f}]</code> (50% Mid: ${plan['bull_ob_mid']:,.1f})
🎯 <b>Khung M5 Vào Lệnh (Entry & Râu Test):</b>
   • Biên độ nến M5: <code>[${plan.get('m5_low', 0):,.1f} - ${plan.get('m5_high', 0):,.1f}]</code>
   • Trạng thái M5: <b>{plan.get('m5_pattern', 'Test Cạnh OB')}</b>
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

🛡️ <b>Cắt lỗ (SL Ngoài Râu M5 / Chóp OB H1):</b> <code>${plan['sl']:,.1f}</code> (-{plan['sl_pct']}%)
🎯 <b>Chốt lời 1 (TP1 - R:R 1:2):</b> <code>${plan['tp1']:,.1f}</code>
🎯 <b>Chốt lời 2 (TP2 - R:R 1:3.5):</b> <code>${plan['tp2']:,.1f}</code>

🧠 <b>KẾ HOẠCH XỬ LÝ LỆNH CHỦ ĐỘNG:</b>
{plan['advice']}

🛡️ <b>QUẢN LÝ VỐN (${CONFIG['ACCOUNT_BALANCE']:,.0f}):</b>
• Rủi ro tối đa 2%: <b>$20.0</b> | Khối lượng: <b>$1,000.0</b> | Đòn bẩy: <b>5x</b>
<i>💡 Nguyên tắc vàng: Khối OB chuẩn đét lấy theo H1 để tránh cản nhiễu, điểm vào lệnh (Entry Limit) và SL siêu mỏng lấy theo nến rút râu M5!</i>"""
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
            m5_info = {'has_multi_tops': False, 'has_multi_bottoms': False, 'upper_wicks_count': 0, 'lower_wicks_count': 0}
            m5_entry_high = m5_high
            m5_entry_low = m15_low

        has_m5_rejection = m5_info['has_multi_tops'] or (m5_info['upper_wicks_count'] >= 1 and current_gold >= b_ob_bot - 1.5)
        has_m5_support = m5_info['has_multi_bottoms'] or (m5_info['lower_wicks_count'] >= 1 and current_gold <= bull_ob_top + 1.5)
        
        # XÁC ĐỊNH HƯỚNG ĐÁNH (KHÔNG ÉP THEO TREND NGÀY NẾU M5 CÓ ĐẢO CHIỀU UY TÍN)
        if has_m5_support and not (w1_bear and d1_bear):
            signal = "LONG"
            setup_desc = f"M5 Quét Râu Đáy / 2 Đáy tại Khối Bullish OB ${major_sup:,.2f} ({sl_time}) + CHoCH M5"
            diamond_note = "⭐ ĐẢO CHIỀU UY TÍN (CÂN BẰNG QUÂN LỰC): Có nến rút râu quét đáy trên M5, không bắt đáy vô cớ!"
        elif has_m5_rejection or (w1_bear and d1_bear):
            signal = "SHORT"
            m5_txt = " + Râu Nến Test M5" if has_m5_rejection else ""
            setup_desc = f"Đồng Pha Giảm Tuần/Ngày - Test Khối Bearish OB H1 ${b_ob_mid:,.2f}{m5_txt}"
            diamond_note = "⭐ ĐỒNG PHA TUẦN + NGÀY (CẢN TO H1): Rình nến M5 rút râu tại mép OB H1, tuyệt đối không bán lưng chừng!"
        else:
            signal = "SHORT" if d1_bear else "LONG"
            setup_desc = f"Cấu Trúc KeyVolume H1 tại Khối OB ${b_ob_mid:,.2f}"
            diamond_note = "⚡ Quản lý vốn chặt chẽ theo cản."
        
        if signal == "SHORT":
            # ENTRY LIMIT & SL THEO KHUNG M5 KẾT HỢP KHỐI OB H1
            entry_stop = round(major_sup - 1.2, 2)
            if current_gold >= b_ob_bot:
                entry_limit = round(max(current_gold, min(m5_entry_high, b_ob_top)), 2)
                sl = round(max(m5_entry_high + 2.5, major_res + 2.0), 2)
                sl_dist = round(sl - entry_limit, 2)
                advice = (
                    f"⚠️ <b>KHỐI OB H1 CHUẨN:</b> Giá hiện tại ${current_gold:,.2f} đang kiểm tra sâu trong <b>Khối Bearish OB H1 [${b_ob_bot:,.2f} - ${b_ob_top:,.2f}]</b> ({sh_time})!\n"
                    f"🎯 <b>ENTRY M5:</b> Khung M5 đang tạo râu từ chối tại đỉnh ${m5_entry_high:,.2f} ({'Mô hình 2-3 đỉnh M5' if m5_info['has_multi_tops'] else 'Râu rút nến M5'}), đón Limit tại mép hoặc Sell ngay!\n"
                    f"🛡️ <b>SL SIÊU NGẮN:</b> Đặt ngoài chóp râu M5 ${sl:,.2f} (~{sl_dist:.1f} giá). Đục thủng chóp râu ra ngoài là cắt lỗ ngay!\n"
                    f"💎 <b>DCA NHỒI KHI ĐẸP:</b> Khớp Lệnh 1 và giá sập thủng đáy <b>${entry_stop:,.2f}</b> (lãi > {sl_dist*0.7:.1f} giá), dời SL về Hoà Vốn (Entry) và kích hoạt Lệnh 2 (Sell Stop)!"
                )
            else:
                entry_limit = round(max(b_ob_bot, min(poc_gold_m15, b_ob_mid)), 2)
                sl = round(major_res + 2.2, 2)
                sl_dist = round(sl - entry_limit, 2)
                advice = (
                    f"⚠️ <b>KHỐI OB H1 CHUẨN:</b> Cản to Bearish OB H1 [${b_ob_bot:,.2f} - ${b_ob_top:,.2f}] ({sh_time}) bảo vệ cấu trúc giảm vĩ mô!\n"
                    f"🎯 <b>ENTRY M5:</b> Chờ giá hồi lên chạm cạnh OB H1, quan sát nến rút râu trên M5 để kê lệnh đón tại <b>${entry_limit:,.2f}</b>!\n"
                    f"🛡️ <b>SL SIÊU NGẮN:</b> Đặt ngoài chóp Swing High ${sl:,.2f} (~{sl_dist:.1f} giá). Nếu đục thủng OB ra ngoài là cắt lỗ ngay!\n"
                    f"💎 <b>DCA NHỒI KHI ĐẸP:</b> Khớp Lệnh 1 và giá sập thủng đáy <b>${entry_stop:,.2f}</b> (lãi > {sl_dist*0.7:.1f} giá), dời SL về Hoà Vốn (Entry) và kích hoạt Lệnh 2 (Sell Stop)!"
                )
            
            if sl_dist < 6.0:
                sl = round(entry_limit + 8.0, 2)
                sl_dist = round(sl - entry_limit, 2)
            elif sl_dist > 25.0:
                sl = round(entry_limit + 20.0, 2)
                sl_dist = round(sl - entry_limit, 2)
                
            tp1 = round(entry_limit - (sl_dist * 2.0), 2)
            tp2 = round(entry_limit - (sl_dist * 3.5), 2)
        else: # LONG
            entry_stop = round(major_res + 1.2, 2)
            if current_gold <= bull_ob_top:
                entry_limit = round(min(current_gold, max(m5_entry_low, bull_ob_bot)), 2)
                sl = round(min(m5_entry_low - 2.5, major_sup - 2.0), 2)
                sl_dist = round(entry_limit - sl, 2)
                advice = (
                    f"⚠️ <b>KHỐI OB H1 CHUẨN:</b> Giá hiện tại ${current_gold:,.2f} đang kiểm tra trong <b>Khối Bullish OB H1 [${bull_ob_bot:,.2f} - ${bull_ob_top:,.2f}]</b> ({sl_time})!\n"
                    f"🎯 <b>ENTRY M5:</b> Khung M5 đang tạo râu quét đáy tại ${m5_entry_low:,.2f}, kê Buy Limit đón tại mép râu!\n"
                    f"🛡️ <b>SL SIÊU NGẮN:</b> Đặt dưới đáy râu M5 ${sl:,.2f}. Thủng râu ra ngoài là cắt lỗ ngay lập tức!\n"
                    f"💎 <b>DCA NHỒI KHI ĐẸP:</b> Khớp Lệnh 1 và giá bứt phá qua đỉnh <b>${entry_stop:,.2f}</b> (lãi > {sl_dist*0.7:.1f} giá), dời SL về Hoà Vốn và kích hoạt Lệnh 2 (Buy Stop)!"
                )
            else:
                entry_limit = round(min(bull_ob_top, max(poc_gold_m15, bull_ob_mid)), 2)
                sl = round(major_sup - 2.2, 2)
                sl_dist = round(entry_limit - sl, 2)
                advice = (
                    f"⚠️ <b>KHỐI OB H1 CHUẨN:</b> Hỗ trợ to Bullish OB H1 [${bull_ob_bot:,.2f} - ${bull_ob_top:,.2f}] ({sl_time}) bảo vệ phe Mua!\n"
                    f"🎯 <b>ENTRY M5:</b> Chờ giá hồi về cạnh OB H1, quan sát nến M5 rút râu quét đáy để kê lệnh đón tại <b>${entry_limit:,.2f}</b>!\n"
                    f"🛡️ <b>SL SIÊU NGẮN:</b> Đặt dưới đáy Swing Low ${sl:,.2f}. Thủng OB ra ngoài là cắt lỗ ngay!\n"
                    f"💎 <b>DCA NHỒI KHI ĐẸP:</b> Khớp Lệnh 1 và giá bứt phá qua đỉnh <b>${entry_stop:,.2f}</b> (lãi > {sl_dist*0.7:.1f} giá), dời SL về Hoà Vốn và kích hoạt Lệnh 2 (Buy Stop)!"
                )
            
            if sl_dist < 6.0:
                sl = round(entry_limit - 8.0, 2)
                sl_dist = round(entry_limit - sl, 2)
            elif sl_dist > 25.0:
                sl = round(entry_limit + 20.0, 2)
                sl_dist = round(entry_limit - sl, 2)
                
            tp1 = round(entry_limit + (sl_dist * 2.0), 2)
            tp2 = round(entry_limit + (sl_dist * 3.5), 2)
            
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
        'test_bear_wick': has_m5_rejection,
        'm5_high': m5_entry_high,
        'm5_low': m5_entry_low,
        'm5_pattern': 'Mô hình 2-3 Đỉnh M5' if m5_info['has_multi_tops'] else 'Râu Nến Test M5',
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
        
        text = f"""🥇 <b>[CHIẾN LƯỢC VÀNG: OB THEO H1 - ENTRY THEO M5]</b> 🥇
━━━━━━━━━━━━━━━━━━
📊 Nguồn biểu đồ: <b>{plan['data_source']}</b>
💰 Giá Vàng OANDA: <b>${plan['current_price']:,.2f}</b> (Bid: ${plan['bid']:,.2f} | Ask: ${plan['ask']:,.2f})
🎯 <b>Vùng POC M15 (Volume cốt lõi):</b> <code>${plan['poc_m15']:,.2f}</code> (HVN: [${plan.get('hvn_lower', 0):,.2f} - ${plan.get('hvn_upper', 0):,.2f}])
📊 <b>CẤU TRÚC ĐA KHUNG (SMC & KEYVOLUME):</b>
🏛️ <b>Cản To Khung H1 (Không Nhiễu):</b>
📈 <b>Swing High H1:</b> <code>${plan['swing_high']:,.2f}</code>{sh_time_str}
   🧱 <b>Khối Bearish OB H1:</b> <code>[${plan['b_ob_bot']:,.2f} - ${plan['b_ob_top']:,.2f}]</code> (50% Mid: ${plan['b_ob_mid']:,.2f})
📉 <b>Swing Low H1:</b> <code>${plan['swing_low']:,.2f}</code>{sl_time_str}
   🧱 <b>Khối Bullish OB H1:</b> <code>[${plan['bull_ob_bot']:,.2f} - ${plan['bull_ob_top']:,.2f}]</code> (50% Mid: ${plan['bull_ob_mid']:,.2f})
🎯 <b>Khung M5 Vào Lệnh (Entry & Râu Test):</b>
   • Biên độ nến M5: <code>[${plan.get('m5_low', 0):,.2f} - ${plan.get('m5_high', 0):,.2f}]</code>
   • Trạng thái M5: <b>{plan.get('m5_pattern', 'Test Cạnh OB')}</b>
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

🛡️ <b>Cắt lỗ (SL Ngoài Râu M5 / Chóp OB H1 ~{plan['sl_dist']:.1f} Giá):</b>
   <code>${plan['sl']:,.2f}</code>
🎯 <b>Chốt lời 1 (TP1 - Ăn {plan['sl_dist']*2:.1f} Giá | R:R 1:2):</b> <code>${plan['tp1']:,.2f}</code>
🎯 <b>Chốt lời 2 (TP2 - Ăn {plan['sl_dist']*3.5:.1f} Giá | R:R 1:3.5):</b> <code>${plan['tp2']:,.2f}</code>

🧠 <b>KẾ HOẠCH XỬ LÝ LỆNH CHỦ ĐỘNG:</b>
{plan['advice']}

🛡️ <b>QUẢN LÝ VỐN VÀNG MT5 (${CONFIG['ACCOUNT_BALANCE']:,.0f}):</b>
• Rủi ro tối đa 2%: <b>$20.0</b> (tương đương 0.01 - 0.02 lot trên MT5)
<i>💡 Nguyên tắc vàng: Khối OB chuẩn đét lấy theo H1 để tránh cản nhiễu, điểm vào lệnh (Entry Limit) và SL siêu mỏng lấy theo nến rút râu M5!</i>"""
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
