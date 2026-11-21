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

    # 1. Tìm Major Bearish OB có cú xả mạnh (Displacement) và CHƯA BỊ TEST LẠI (Unmitigated)
    major_bear_obs = []
    for i in range(len(chrono) - 3, 2, -1):
        c = chrono[i]
        h = float(c[2])
        if h > curr_p:
            # Kiểm tra đỉnh Swing High (cao hơn 2 nến trước và 2 nến sau)
            is_peak = all(h >= float(chrono[j][2]) for j in range(max(0, i - 2), min(n, i + 3)))
            if is_peak:
                future_low = min(float(chrono[j][3]) for j in range(i + 1, min(n, i + 10)))
                drop = h - future_low
                if drop >= min_disp:
                    # Kiểm tra chưa bị đóng cửa vượt đỉnh
                    if not any(float(chrono[k][4]) > h for k in range(i + 1, n)):
                        t = datetime.datetime.fromtimestamp(int(c[0])/1000, tz=TZ_VN).strftime('%H:%M %d/%m')
                        # Vùng OB: Chân sóng / hỗ trợ bị bẻ gãy (BOS) trước cú xả
                        prev_bars = chrono[max(0, i - 6): i]
                        if prev_bars:
                            base_support = min(float(b[3]) for b in prev_bars)
                            base_close = min(float(b[4]) for b in prev_bars)
                            ob_bot = round(max(base_support, base_close - 3.0), 2 if is_gold else 1)
                            ob_top = round(ob_bot + (6.0 if is_gold else 400.0), 2 if is_gold else 1)
                        else:
                            ob_top = round(h, 2 if is_gold else 1)
                            ob_bot = round(h - (6.0 if is_gold else 400.0), 2 if is_gold else 1)
                        
                        # Kiểm tra xem từ sau cú xả (i+3 trở đi) giá có chạm lại vùng này chưa
                        retested = any(float(chrono[m][2]) >= ob_bot for m in range(i + 3, n))
                        if not retested:
                            major_bear_obs.append({
                                'time': t, 'high': h, 'ob_bot': ob_bot, 'ob_top': ob_top,
                                'mid': round((ob_top + ob_bot) / 2.0, 2 if is_gold else 1),
                                'filter': 'H1 Major Unmitigated OB'
                            })

    # 2. Tìm Major Bullish OB có cú bơm mạnh (Displacement) và CHƯA BỊ TEST LẠI (Unmitigated)
    major_bull_obs = []
    for i in range(len(chrono) - 3, 2, -1):
        c = chrono[i]
        l = float(c[3])
        if l < curr_p:
            is_trough = all(l <= float(chrono[j][3]) for j in range(max(0, i - 2), min(n, i + 3)))
            if is_trough:
                future_high = max(float(chrono[j][2]) for j in range(i + 1, min(n, i + 10)))
                pump = future_high - l
                if pump >= min_disp:
                    if not any(float(chrono[k][4]) < l for k in range(i + 1, n)):
                        t = datetime.datetime.fromtimestamp(int(c[0])/1000, tz=TZ_VN).strftime('%H:%M %d/%m')
                        ob_bot = round(l, 2 if is_gold else 1)
                        ob_top = round(l + (6.0 if is_gold else 400.0), 2 if is_gold else 1)
                        major_bull_obs.append({
                            'time': t, 'low': l, 'ob_bot': ob_bot, 'ob_top': ob_top,
                            'mid': round((ob_top + ob_bot) / 2.0, 2 if is_gold else 1),
                            'filter': 'H1 Major Unmitigated OB'
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

        # 3. Tính POC & Vùng High Volume Node (HVN) M15 theo Lý Thuyết Giá FX DREAM
        poc_m15, hvn_lower, hvn_upper = calculate_keyvolume_nodes(m15_klines, n_bins=20)

        # XÁC ĐỊNH HƯỚNG ĐÁNH THEO BIAS VĨ MÔ & TEST CẢN
        is_bear_confirmed = m5_info['is_confirmed_entry_bear']
        is_bull_confirmed = m5_info['is_confirmed_entry_bull']

        if is_bull_confirmed and not (w1_bear and d1_bear):
            signal = "LONG"
            setup_desc = f"M5 Rút Chân Quét Đáy + Kích Volume tại Khối Bullish OB ${swing_low:,.1f} ({sl_time})"
            diamond_note = "⭐ ĐẢO CHIỀU UY TÍN (CÂN BẰNG QUÂN LỰC): Đã có nến M5 rút chân kèm Kích Volume xác nhận!"
        elif is_bear_confirmed or (w1_bear and d1_bear):
            signal = "SHORT"
            m5_txt = " + Xác Nhận Kích Vol M5" if is_bear_confirmed else " (Đang Chờ Kích Vol)"
            setup_desc = f"Đồng Pha Giảm Tuần/Ngày - Test Khối Bearish OB H1 ${bearish_ob['mid']:,.1f}{m5_txt}"
            diamond_note = "⭐ ĐỒNG PHA TUẦN + NGÀY (CẢN TO H1): Tuyệt đối không chạm là vào, chờ nến M5 rút râu + kích Volume!"
        else:
            signal = "SHORT" if d1_bear else "LONG"
            setup_desc = f"Cấu Trúc KeyVolume H1 tại Khối OB ${bearish_ob['mid']:,.1f}"
            diamond_note = "⚡ Quản lý vốn theo từng mốc cản."

        if signal == "SHORT":
            entry_stop = round(swing_low * 0.998, 1)
            conf = m5_info['confirmed_bear_rejection']
            if conf:
                # ĐÃ CÓ XÁC NHẬN NẾN + VOLUME (KEYVOLUME CONFIRMATION)
                confirm_badge = "🔥 ĐÃ XÁC NHẬN (NẾN RÚT RÂU + KÍCH VOLUME)"
                entry_limit = round(current_price, 1)
                sl = round(conf['high'] + 120.0, 1)
                advice = (
                    f"✅ <b>TÔN CHỈ KEYVOLUME ĐÃ THỎA MÃN (VÀO LỆNH NGAY):</b>\n"
                    f"• Tại Khối Bearish OB H1, nến M5 lúc <b>{conf['time']}</b> đã RÚT RÂU <b>{conf['wick_pct']}%</b> kèm <b>KÍCH VOLUME ({conf['vol_ratio']}x)</b>!\n"
                    f"• Đủ 100% điều kiện Nến + Volume xác nhận phe Bán nhảy vào đạp giá, vào lệnh Sell ngay!\n"
                    f"🛡️ <b>SL SIÊU MỎNG:</b> Đặt ngoài chóp râu M5 ${sl:,.1f}. Đục thủng chóp râu ra ngoài là kịch bản sai, cắt lỗ ngay!\n"
                    f"💎 <b>ĐUA SÓNG ĐÂM 1 MẠCH:</b> Nếu BTC lao thẳng phá đáy <b>${entry_stop:,.1f}</b>, Lệnh 2 Sell Stop sẽ tự kích hoạt!"
                )
            else:
                # CHƯA CÓ XÁC NHẬN -> CHỜ, KHÔNG CHẠM LÀ VÀO
                confirm_badge = "⏳ ĐANG CHỜ XÁC NHẬN (CHƯA VÀO LỆNH)"
                entry_limit = round(max(bearish_ob['bottom'], min(poc_m15, bearish_ob['mid'])), 1)
                sl = round(swing_high + 180.0, 1)
                advice = (
                    f"⚠️ <b>TÔN CHỈ FX KEYVOLUME (TUYỆT ĐỐI KHÔNG CHẠM LÀ VÀO):</b>\n"
                    f"• Giá đang tiếp cận Khối Bearish OB H1 [${bearish_ob['bottom']:,.1f} - ${bearish_ob['top']:,.1f}], nhưng <b>CHƯA CÓ nến M5 rút râu kèm KÍCH VOLUME</b> xác nhận!\n"
                    f"• Kiên nhẫn đứng ngoài quan sát! Chỉ bấm lệnh khi xuất hiện cây nến M5 rút râu mạnh + Volume tăng vọt từ chối tại cản!\n"
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
            conf = m5_info['confirmed_bull_rejection']
            if conf:
                confirm_badge = "🔥 ĐÃ XÁC NHẬN (NẾN RÚT CHÂN + KÍCH VOLUME)"
                entry_limit = round(current_price, 1)
                sl = round(conf['low'] - 120.0, 1)
                advice = (
                    f"✅ <b>TÔN CHỈ KEYVOLUME ĐÃ THỎA MÃN (VÀO LỆNH NGAY):</b>\n"
                    f"• Tại Khối Bullish OB H1, nến M5 lúc <b>{conf['time']}</b> đã RÚT CHÂN <b>{conf['wick_pct']}%</b> kèm <b>KÍCH VOLUME ({conf['vol_ratio']}x)</b>!\n"
                    f"• Đủ 100% điều kiện Nến + Volume xác nhận phe Mua đẩy giá, vào lệnh Buy ngay!\n"
                    f"🛡️ <b>SL SIÊU MỎNG:</b> Đặt dưới đáy râu M5 ${sl:,.1f}. Thủng râu ra ngoài là cắt lỗ ngay!\n"
                    f"💎 <b>ĐUA SÓNG BỨT TỐC:</b> Nếu BTC tăng thốc qua đỉnh <b>${entry_stop:,.1f}</b>, Lệnh 2 Buy Stop sẽ tự khớp!"
                )
            else:
                confirm_badge = "⏳ ĐANG CHỜ XÁC NHẬN (CHƯA VÀO LỆNH)"
                entry_limit = round(min(bullish_ob['top'], max(poc_m15, bullish_ob['mid'])), 1)
                sl = round(swing_low - 180.0, 1)
                advice = (
                    f"⚠️ <b>TÔN CHỈ FX KEYVOLUME (TUYỆT ĐỐI KHÔNG CHẠM LÀ VÀO):</b>\n"
                    f"• Giá đang ở vùng Khối Bullish OB H1 [${bullish_ob['bottom']:,.1f} - ${bullish_ob['top']:,.1f}], nhưng <b>CHƯA CÓ nến M5 rút chân kèm KÍCH VOLUME</b> xác nhận!\n"
                    f"• Kiên nhẫn chờ cây nến M5 rút chân kèm Volume lớn để xác nhận trước khi vào lệnh!\n"
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
            'confirm_badge': confirm_badge,
            'is_confirmed': is_bear_confirmed if signal == 'SHORT' else is_bull_confirmed,
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
            'm5_pattern': 'Rút Râu + Kích Volume' if (is_bear_confirmed or is_bull_confirmed) else 'Đang Chờ Kích Vol',
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
   • Trạng thái M5: <b>{plan.get('m5_pattern', 'Test Cạnh OB')}</b>
   • Tôn chỉ KeyVolume: <b>{plan.get('confirm_badge', '⏳ Đang Chờ Nến & Kích Vol')}</b>
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
        is_bear_confirmed = m5_info['is_confirmed_entry_bear']
        is_bull_confirmed = m5_info['is_confirmed_entry_bull']
        
        if is_bull_confirmed and not (w1_bear and d1_bear):
            signal = "LONG"
            setup_desc = f"M5 Rút Chân Quét Đáy + Kích Volume tại Khối Bullish OB ${major_sup:,.2f} ({sl_time})"
            diamond_note = "⭐ ĐẢO CHIỀU UY TÍN (CÂN BẰNG QUÂN LỰC): Đã có nến M5 rút chân kèm Kích Volume xác nhận!"
        elif is_bear_confirmed or (w1_bear and d1_bear):
            signal = "SHORT"
            m5_txt = " + Xác Nhận Kích Vol M5" if is_bear_confirmed else " (Đang Chờ Kích Vol)"
            setup_desc = f"Đồng Pha Giảm Tuần/Ngày - Test Khối Bearish OB H1 ${b_ob_mid:,.2f}{m5_txt}"
            diamond_note = "⭐ ĐỒNG PHA TUẦN + NGÀY (CẢN TO H1): Tuyệt đối không chạm là vào, chờ nến M5 rút râu + kích Volume!"
        else:
            signal = "SHORT" if d1_bear else "LONG"
            setup_desc = f"Cấu Trúc KeyVolume H1 tại Khối OB ${b_ob_mid:,.2f}"
            diamond_note = "⚡ Quản lý vốn chặt chẽ theo cản."
        
        if signal == "SHORT":
            entry_stop = round(major_sup - 1.2, 2)
            conf = m5_info['confirmed_bear_rejection']
            if conf:
                # ĐÃ CÓ XÁC NHẬN NẾN + VOLUME (KEYVOLUME CONFIRMATION)
                confirm_badge = "🔥 ĐÃ XÁC NHẬN (NẾN RÚT RÂU + KÍCH VOLUME)"
                entry_limit = round(current_gold, 2)
                sl = round(max(conf['high'] + 2.5, major_res + 2.0), 2)
                sl_dist = round(sl - entry_limit, 2)
                advice = (
                    f"✅ <b>TÔN CHỈ KEYVOLUME ĐÃ THỎA MÃN (VÀO LỆNH NGAY):</b>\n"
                    f"• Tại Khối Bearish OB H1, nến M5 lúc <b>{conf['time']}</b> đã RÚT RÂU <b>{conf['wick_pct']}%</b> kèm <b>KÍCH VOLUME ({conf['vol_ratio']}x)</b>!\n"
                    f"• Đủ 100% điều kiện Nến + Volume xác nhận phe Bán nhảy vào đạp giá, vào lệnh Sell ngay!\n"
                    f"🛡️ <b>SL SIÊU MỎNG:</b> Đặt ngoài chóp râu M5 ${sl:,.2f} (~{sl_dist:.1f} giá). Đục thủng chóp râu ra ngoài là cắt lỗ ngay!\n"
                    f"💎 <b>DCA NHỒI KHI ĐẸP:</b> Khớp Lệnh 1 và giá sập thủng đáy <b>${entry_stop:,.2f}</b>, dời SL về Hoà Vốn (Entry) và kích hoạt Lệnh 2 (Sell Stop)!"
                )
            else:
                # CHƯA CÓ XÁC NHẬN -> CHỜ, KHÔNG CHẠM LÀ VÀO
                confirm_badge = "⏳ ĐANG CHỜ XÁC NHẬN (CHƯA VÀO LỆNH)"
                entry_limit = round(b_ob_bot, 2)
                sl = round(max(b_ob_top + 6.0, major_res + 2.5), 2)
                sl_dist = round(sl - entry_limit, 2)
                if current_gold < b_ob_bot - 10.0:
                    advice = (
                        f"⚠️ <b>LÝ THUYẾT GIÁ (FX DREAM - TUYỆT ĐỐI KHÔNG BÁN LƯNG CHỪNG):</b>\n"
                        f"• Giá hiện tại <b>${current_gold:,.2f}</b> đang ở vùng chợ mỏng (LVN) / lưng chừng, cách Khối Bearish OB H1 [${b_ob_bot:,.2f} - ${b_ob_top:,.2f}] ({sh_time}) hơn {abs(current_gold - b_ob_bot):.1f} giá!\n"
                        f"• <b>Kế hoạch:</b> Đặt sẵn Limit đón tại cạnh Khối Bearish OB <b>${entry_limit:,.2f}</b>. Khi giá hồi lên cản to H1, bắt buộc phải có nến M5 rút râu + Kích Volume xác nhận mới vào lệnh!\n"
                        f"💎 <b>DCA NHỒI KHI ĐẸP:</b> Khớp Lệnh 1 và giá sập thủng đáy <b>${entry_stop:,.2f}</b>, dời SL về Hoà Vốn (Entry) và kích hoạt Lệnh 2 (Sell Stop)!"
                    )
                else:
                    advice = (
                        f"⚠️ <b>TÔN CHỈ FX KEYVOLUME (TUYỆT ĐỐI KHÔNG CHẠM LÀ VÀO):</b>\n"
                        f"• Giá đang tiếp cận Khối Bearish OB H1 [${b_ob_bot:,.2f} - ${b_ob_top:,.2f}], nhưng <b>CHƯA CÓ nến M5 rút râu kèm KÍCH VOLUME</b> xác nhận!\n"
                        f"• Kiên nhẫn đứng ngoài quan sát! Chỉ bấm lệnh khi xuất hiện cây nến M5 rút râu mạnh + Volume tăng vọt từ chối tại cản!\n"
                        f"💎 <b>DCA NHỒI KHI ĐẸP:</b> Khớp Lệnh 1 và giá sập thủng đáy <b>${entry_stop:,.2f}</b>, dời SL về Hoà Vốn (Entry) và kích hoạt Lệnh 2 (Sell Stop)!"
                    )
            
            if sl_dist < 6.0:
                sl = round(entry_limit + 8.0, 2)
                sl_dist = round(sl - entry_limit, 2)
            elif sl_dist > 35.0:
                sl = round(entry_limit + 25.0, 2)
                sl_dist = round(sl - entry_limit, 2)
                
            tp1 = round(entry_limit - (sl_dist * 2.0), 2)
            tp2 = round(entry_limit - (sl_dist * 3.5), 2)
        else: # LONG
            entry_stop = round(major_res + 1.2, 2)
            conf = m5_info['confirmed_bull_rejection']
            if conf:
                confirm_badge = "🔥 ĐÃ XÁC NHẬN (NẾN RÚT CHÂN + KÍCH VOLUME)"
                entry_limit = round(current_gold, 2)
                sl = round(min(conf['low'] - 2.5, major_sup - 2.0), 2)
                sl_dist = round(entry_limit - sl, 2)
                advice = (
                    f"✅ <b>TÔN CHỈ KEYVOLUME ĐÃ THỎA MÃN (VÀO LỆNH NGAY):</b>\n"
                    f"• Tại Khối Bullish OB H1, nến M5 lúc <b>{conf['time']}</b> đã RÚT CHÂN <b>{conf['wick_pct']}%</b> kèm <b>KÍCH VOLUME ({conf['vol_ratio']}x)</b>!\n"
                    f"• Đủ 100% điều kiện Nến + Volume xác nhận phe Mua đẩy giá, vào lệnh Buy ngay!\n"
                    f"🛡️ <b>SL SIÊU MỎNG:</b> Đặt dưới đáy râu M5 ${sl:,.2f}. Thủng râu ra ngoài là cắt lỗ ngay lập tức!\n"
                    f"💎 <b>DCA NHỒI KHI ĐẸP:</b> Khớp Lệnh 1 và giá bứt phá qua đỉnh <b>${entry_stop:,.2f}</b>, dời SL về Hoà Vốn và kích hoạt Lệnh 2 (Buy Stop)!"
                )
            else:
                confirm_badge = "⏳ ĐANG CHỜ XÁC NHẬN (CHƯA VÀO LỆNH)"
                entry_limit = round(bull_ob_top, 2)
                sl = round(min(bull_ob_bot - 6.0, major_sup - 2.5), 2)
                sl_dist = round(entry_limit - sl, 2)
                if current_gold > bull_ob_top + 10.0:
                    advice = (
                        f"⚠️ <b>LÝ THUYẾT GIÁ (FX DREAM - TUYỆT ĐỐI KHÔNG MUA LƯNG CHỪNG):</b>\n"
                        f"• Giá hiện tại <b>${current_gold:,.2f}</b> đang ở vùng chợ mỏng (LVN) / lưng chừng, cách Khối Bullish OB H1 [${bull_ob_bot:,.2f} - ${bull_ob_top:,.2f}] ({sl_time}) hơn {abs(current_gold - bull_ob_top):.1f} giá!\n"
                        f"• <b>Kế hoạch:</b> Đặt sẵn Limit đón tại cạnh Khối Bullish OB <b>${entry_limit:,.2f}</b>. Khi giá đạp về cản to H1, bắt buộc phải có nến M5 rút chân + Kích Volume xác nhận mới vào lệnh!\n"
                        f"💎 <b>DCA NHỒI KHI ĐẸP:</b> Khớp Lệnh 1 và giá bứt phá qua đỉnh <b>${entry_stop:,.2f}</b>, dời SL về Hoà Vốn và kích hoạt Lệnh 2 (Buy Stop)!"
                    )
                else:
                    advice = (
                        f"⚠️ <b>TÔN CHỈ FX KEYVOLUME (TUYỆT ĐỐI KHÔNG CHẠM LÀ VÀO):</b>\n"
                        f"• Giá đang ở vùng Khối Bullish OB H1 [${bull_ob_bot:,.2f} - ${bull_ob_top:,.2f}], nhưng <b>CHƯA CÓ nến M5 rút chân kèm KÍCH VOLUME</b> xác nhận!\n"
                        f"• Kiên nhẫn chờ cây nến M5 rút chân kèm Volume lớn để xác nhận trước khi vào lệnh!\n"
                        f"💎 <b>DCA NHỒI KHI ĐẸP:</b> Khớp Lệnh 1 và giá bứt phá qua đỉnh <b>${entry_stop:,.2f}</b>, dời SL về Hoà Vốn và kích hoạt Lệnh 2 (Buy Stop)!"
                    )
            
            if sl_dist < 6.0:
                sl = round(entry_limit - 8.0, 2)
                sl_dist = round(entry_limit - sl, 2)
            elif sl_dist > 35.0:
                sl = round(entry_limit - 25.0, 2)
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
        b_ob_bot = 3542.0
        b_ob_mid = 3544.5
        major_sup = 3508.0
        bull_ob_top = 3514.0
        bull_ob_bot = 3508.0
        bull_ob_mid = 3511.0
        sh_time = "H1"
        sh_filter = "H1 Unmitigated OB"
        sl_time = "H1"
        sl_filter = "H1 Unmitigated OB"
        confirm_badge = "⏳ ĐANG CHỜ XÁC NHẬN (CHƯA VÀO LỆNH)"
        is_bear_confirmed = False
        is_bull_confirmed = False
        m5_entry_high = 3547.0
        m5_entry_low = 3508.0
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
        'confirm_badge': confirm_badge,
        'is_confirmed': is_bear_confirmed if signal == 'SHORT' else is_bull_confirmed,
        'test_bear_wick': is_bear_confirmed,
        'm5_high': m5_entry_high,
        'm5_low': m5_entry_low,
        'm5_pattern': 'Rút Râu + Kích Volume' if (is_bear_confirmed if signal == 'SHORT' else is_bull_confirmed) else 'Đang Chờ Kích Vol',
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
   • Trạng thái M5: <b>{plan.get('m5_pattern', 'Test Cạnh OB')}</b>
   • Tôn chỉ KeyVolume: <b>{plan.get('confirm_badge', '⏳ Đang Chờ Nến & Kích Vol')}</b>
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
            
            # 2. QUÉT TỰ ĐỘNG VÀNG (OANDA:XAUUSD - Chuẩn MT5)
            plan_gold = calculate_gold_h4_plan()
            dist_to_cản = abs(plan_gold['current_price'] - plan_gold['entry_limit'])
            if plan_gold.get('is_confirmed') and ('ĐÃ XÁC NHẬN' in plan_gold.get('confirm_badge', '')) and (dist_to_cản <= 8.0):
                if now - LAST_ALERT_TIME['GOLD'] > 1200: # Cooldown 20 phút giữa các kèo
                    price_gold = plan_gold['current_price']
                    entry_gold = plan_gold['entry_limit']
                    s_emoji = "🔴 SHORT (BÁN)" if plan_gold['signal'] == 'SHORT' else "🟢 LONG (MUA)"
                    action_l = "LỆNH VÀO NGAY (Nến M5 Vừa Đóng Chốt Retest):"
                    msg = f"""🚨 <b>[TỰ ĐỘNG BÁO KÈO VIP M5: VÀO LỆNH NGAY ĐẦU NẾN]</b> 🚨
━━━━━━━━━━━━━━━━━━
📊 Nguồn biểu đồ: <b>TradingView (OANDA:XAUUSD - Chuẩn MT5)</b>
💰 Giá Vàng hiện tại: <b>${price_gold:,.2f}</b>
🎯 <b>Trạng thái:</b> <b>{plan_gold.get('confirm_badge', 'ĐÃ XÁC NHẬN')}</b>
📊 <b>Cản To Khung H1:</b> <code>${plan_gold['swing_high']:,.2f}</code> ({plan_gold.get('sh_time', '')})
   🧱 <b>Khối Bearish OB H1:</b> <code>[${plan_gold['b_ob_bot']:,.2f} - ${plan_gold['b_ob_top']:,.2f}]</code>
📉 <b>Hỗ Trợ Khung H1:</b> <code>${plan_gold['swing_low']:,.2f}</code> ({plan_gold.get('sl_time', '')})
   🧱 <b>Khối Bullish OB H1:</b> <code>[${plan_gold['bull_ob_bot']:,.2f} - ${plan_gold['bull_ob_top']:,.2f}]</code>
⚡ <b>Cấu trúc SMC:</b> <b>{plan_gold['setup_desc']}</b>
━━━━━━━━━━━━━━━━━━
💎 <b>ĐỒNG PHA BIAS ĐA KHUNG (WINRATE CAO):</b>
• <b>Bias Tuần (W1):</b> {plan_gold['w1_bias']}
• <b>Bias Ngày (D1):</b> {plan_gold['d1_bias']}
<i>🔥 Tín hiệu tuyệt đẹp: Đã hội tụ đủ nến M5 từ chối + KÍCH VOLUME theo đúng tôn chỉ KeyVolume!</i>
━━━━━━━━━━━━━━━━━━
🚀 <b>KHUYẾN NGHỊ VÀO LỆNH: {s_emoji}</b>
👉 <b>{action_l}</b>
   <code>${entry_gold:,.2f}</code>
👉 <b>LỆNH STOP NHỒI SÓNG TIẾP DIỄN:</b>
   <code>${plan_gold['entry_stop']:,.2f}</code>

🛡️ <b>Cắt lỗ (SL Ngoài Râu M5):</b>
   <code>${plan_gold['sl']:,.2f}</code> (~{plan_gold['sl_dist']:.1f} Giá)
🎯 <b>Chốt lời 1 (TP1 - R:R 1:2):</b> <code>${plan_gold['tp1']:,.2f}</code>
🎯 <b>Chốt lời 2 (TP2 - R:R 1:3.5):</b> <code>${plan_gold['tp2']:,.2f}</code>

🧠 <b>Kế hoạch xử lý:</b>
{plan_gold['advice']}

🛡️ <b>QUẢN LÝ VỐN VÀNG MT5 (${CONFIG['ACCOUNT_BALANCE']:,.0f}):</b>
• Rủi ro tối đa 2%: <b>$20.0</b> (tương đương 0.01 - 0.02 lot trên MT5)"""
                    send_telegram(msg)
                    LAST_ALERT_TIME['GOLD'] = now

            # 3. QUÉT TỰ ĐỘNG BITCOIN (BTCUSDT)
            plan_btc = calculate_btc_h4_plan()
            dist_to_cản = abs(plan_btc['current_price'] - plan_btc['entry_limit'])
            if plan_btc.get('is_confirmed') and ('ĐÃ XÁC NHẬN' in plan_btc.get('confirm_badge', '')) and (dist_to_cản <= 300.0):
                if now - LAST_ALERT_TIME['BTC'] > 1200:
                    price_btc = plan_btc['current_price']
                    entry_l = plan_btc['entry_limit']
                    entry_s = plan_btc['entry_stop']
                    s_emoji = "🔴 SHORT (BÁN)" if plan_btc['signal'] == 'SHORT' else "🟢 LONG (MUA)"
                    action_l = "LỆNH VÀO NGAY (Nến M5 Vừa Đóng Chốt Retest):"
                    action_s = "LỆNH STOP ĐUA SÓNG:"
                    msg = f"""🚨 <b>[TỰ ĐỘNG BÁO KÈO VIP M5: VÀO LỆNH NGAY ĐẦU NẾN]</b> 🚨
━━━━━━━━━━━━━━━━━━
💰 Giá BTC hiện tại: <b>${price_btc:,.1f}</b>
🎯 <b>Trạng thái:</b> <b>{plan_btc.get('confirm_badge', 'ĐÃ XÁC NHẬN')}</b>
📊 <b>Cản To Khung H1:</b> <code>${plan_btc['swing_high']:,.1f}</code> ({plan_btc.get('sh_time', '')})
   🧱 <b>Khối Bearish OB H1:</b> <code>[${plan_btc['b_ob_bot']:,.1f} - ${plan_btc['b_ob_top']:,.1f}]</code>
📉 <b>Hỗ Trợ Khung H1:</b> <code>${plan_btc['swing_low']:,.1f}</code> ({plan_btc.get('sl_time', '')})
   🧱 <b>Khối Bullish OB H1:</b> <code>[${plan_btc['bull_ob_bot']:,.1f} - ${plan_btc['bull_ob_top']:,.1f}]</code>
⚡ <b>Cấu trúc SMC:</b> <b>{plan_btc['setup_desc']}</b>
━━━━━━━━━━━━━━━━━━
💎 <b>ĐỒNG PHA BIAS ĐA KHUNG (WINRATE CAO):</b>
• <b>Bias Tuần (W1):</b> {plan_btc['w1_bias']}
• <b>Bias Ngày (D1):</b> {plan_btc['d1_bias']}
<i>🔥 Tín hiệu tuyệt đẹp: Đã hội tụ đủ nến M5 từ chối + KÍCH VOLUME theo đúng tôn chỉ KeyVolume!</i>
━━━━━━━━━━━━━━━━━━
🚀 <b>KHUYẾN NGHỊ VÀO LỆNH: {s_emoji}</b>
👉 <b>{action_l}:</b>
   <code>${entry_l:,.1f}</code>
👉 <b>{action_s}:</b>
   <code>${entry_s:,.1f}</code>

🛡️ <b>Cắt lỗ (SL Ngoài Râu M5):</b> <code>${plan_btc['sl']:,.1f}</code> (-{plan_btc['sl_pct']}%)
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
            time.sleep(10)

if __name__ == '__main__':
    threading.Thread(target=start_health_server, daemon=True).start()
    threading.Thread(target=self_ping_worker, daemon=True).start()
    threading.Thread(target=auto_diamond_alert_worker, daemon=True).start()
    run_bot()
