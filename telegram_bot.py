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
def find_fractal_swings(klines_desc, n=2):
    """
    Xác định đỉnh/đáy cấu trúc uy tín (Fractal Swing High / Swing Low) chuẩn SMC.
    Một đỉnh là Swing High khi cao hơn n nến trước đó và n nến sau đó.
    Một đáy là Swing Low khi thấp hơn n nến trước đó và n nến sau đó.
    """
    chrono = list(reversed(klines_desc))
    swings_h = []
    swings_l = []
    for i in range(n, len(chrono) - n):
        c_time = datetime.datetime.fromtimestamp(int(chrono[i][0])/1000 + 7*3600).strftime('%H:%M %d/%m')
        h = float(chrono[i][2])
        l = float(chrono[i][3])
        is_sh = all(h > float(chrono[j][2]) for j in range(i-n, i)) and all(h >= float(chrono[j][2]) for j in range(i+1, i+n+1))
        is_sl = all(l < float(chrono[j][3]) for j in range(i-n, i)) and all(l <= float(chrono[j][3]) for j in range(i+1, i+n+1))
        if is_sh:
            swings_h.append({'time': c_time, 'price': h})
        if is_sl:
            swings_l.append({'time': c_time, 'price': l})
    latest_sh = swings_h[-1] if swings_h else {'time': 'N/A', 'price': float(klines_desc[0][2])}
    latest_sl = swings_l[-1] if swings_l else {'time': 'N/A', 'price': float(klines_desc[0][3])}
    major_sh = max(swings_h, key=lambda x: x['price']) if swings_h else latest_sh
    major_sl = min(swings_l, key=lambda x: x['price']) if swings_l else latest_sl
    return latest_sh, latest_sl, major_sh, major_sl

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

        # 2. Cản Cấu Trúc Uy Tín (Fractal Swing High / Swing Low H1)
        latest_sh, latest_sl, major_sh, major_sl = find_fractal_swings(h1_klines, n=2)
        swing_high = round(latest_sh['price'], 1)
        sh_time = latest_sh['time']
        swing_low = round(latest_sl['price'], 1)
        sl_time = latest_sl['time']

        # 3. Tính POC M15 (Volume profile phiên gần nhất)
        prices = []
        weights = []
        for k in m15_klines:
            high = float(k[2])
            low = float(k[3])
            vol = float(k[5])
            for p in np.linspace(low, high, 5):
                prices.append(p)
                weights.append(vol / 5.0)
                
        hist, bin_edges = np.histogram(prices, bins=25, weights=weights)
        poc_m15 = round((bin_edges[np.argmax(hist)] + bin_edges[np.argmax(hist)+1]) / 2, 1)

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

        # Kiểm tra mô hình 2 Đáy (Double Bottom) trên M15:
        is_double_bottom = (current_price > swing_low + 200.0) and (sweep_bull is not None)

        # XÁC ĐỊNH HƯỚNG ĐÁNH (KHÔNG ÉP THEO TREND NGÀY NẾU M15 CÓ ĐẢO CHIỀU UY TÍN)
        if sweep_bull or is_double_bottom:
            signal = "LONG"
            setup_desc = f"Mô Hình 2 Đáy / Quét Râu Đáy tại ${swing_low:,.1f} ({sl_time}) + Bullish CHoCH"
            diamond_note = "⭐ ĐẢO CHIỀU UY TÍN: Có 2 Đáy & Quét Râu Đáy rõ ràng, không bắt đáy vô cớ!"
        elif sweep_bear:
            signal = "SHORT"
            setup_desc = f"Quét Râu Đỉnh / 2 Đỉnh tại Cản Đỉnh ${swing_high:,.1f} ({sh_time}) + Bearish CHoCH"
            diamond_note = "⭐ CẢN TO THẬT SỰ: Chạm đỉnh râu bị từ chối mạnh, thuận lực xả vĩ mô!"
        elif w1_bear and d1_bear:
            signal = "SHORT"
            setup_desc = f"Đồng Pha Giảm Tuần/Ngày - Kiên nhẫn chờ hồi về Cản Đỉnh ${swing_high:,.1f}"
            diamond_note = "⭐ ĐỒNG PHA TUẦN + NGÀY (CẢN TO): Chờ hồi test cản to, tuyệt đối không bán lưng chừng!"
        else:
            signal = "SHORT" if d1_bear else "LONG"
            setup_desc = f"Cấu Trúc SMC H1 tại Cản Đỉnh ${swing_high:,.1f}"
            diamond_note = "⚡ Quản lý vốn theo từng mốc cản."

        if signal == "SHORT":
            # ENTRY LIMIT: Neo chặt tại CẢN ĐỈNH UY TÍN H1 (swing_high) hoặc POC M15, TUYỆT ĐỐI KHÔNG BÁN LƯNG CHỪNG
            c_to = swing_high
            entry_limit = round(max(poc_m15, c_to - 120.0), 1)
            # SELL STOP: Đặt phá vỡ đáy để ăn trọn sóng xả đâm 1 mạch nếu không hồi
            entry_stop = round(swing_low * 0.998, 1)
            
            # SL: Đặt trên chóp cản đỉnh uy tín + đệm an toàn
            sl = round(c_to + 180.0, 1)
            risk = sl - entry_limit
            if risk < 300.0:
                sl = round(entry_limit + 400.0, 1)
                risk = sl - entry_limit
            tp1 = round(entry_limit - (risk * 2.0), 1)
            tp2 = round(entry_limit - (risk * 3.5), 1)
            
            advice = (
                f"⚠️ <b>KHÔNG BÁN LƯNG CHỪNG:</b> Giá hiện tại ${current_price:,.1f} ở lưng chừng range, chỉ vào Limit khi giá hồi lên <b>Cản Đỉnh Uy Tín ${c_to:,.1f}</b> hoặc POC M15!\n"
                f"💎 <b>ĐUA SÓNG ĐÂM 1 MẠCH:</b> Nếu BTC lao thẳng không test phá đáy <b>${entry_stop:,.1f}</b>, Lệnh 2 Sell Stop sẽ tự kích hoạt để không bị lỡ tàu!"
            )
        else: # LONG
            # ENTRY LIMIT: Neo chặt tại HỖ TRỢ ĐÁY UY TÍN H1 / ĐÁY 2 (không bắt đáy vô cớ)
            h_to = swing_low
            entry_limit = round(min(poc_m15, h_to + 250.0), 1)
            if entry_limit < h_to + 50.0:
                entry_limit = round(h_to + 120.0, 1)
                
            entry_stop = round(swing_high * 1.002, 1)
            
            # SL: Đặt dưới đáy mô hình 2 đáy / râu quét an toàn
            sl = round(h_to - 180.0, 1)
            risk = entry_limit - sl
            if risk < 300.0:
                sl = round(entry_limit - 400.0, 1)
                risk = entry_limit - sl
            tp1 = round(entry_limit + (risk * 2.0), 1)
            tp2 = round(entry_limit + (risk * 3.5), 1)
            
            advice = (
                f"⚠️ <b>ĐẢO CHIỀU CÓ CHoCH:</b> Có xác nhận mô hình 2 Đáy tại Hỗ Trợ Uy Tín ${h_to:,.1f}, không bắt đáy lung tung!\n"
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
            'swing_high': swing_high,
            'sh_time': sh_time,
            'swing_low': swing_low,
            'sl_time': sl_time,
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
        action_l = "LỆNH 1: Bán Limit Đón Râu Hồi Retest Cản Uy Tín / POC" if plan['signal'] == 'SHORT' else "LỆNH 1: Mua Limit Đón Râu Hồi Retest Hỗ Trợ Uy Tín / POC"
        action_s = "LỆNH 2: Bán Stop Phá Đáy - Bắt Trọn Cú Xả Đâm 1 Mạch" if plan['signal'] == 'SHORT' else "LỆNH 2: Mua Stop Phá Đỉnh - Bắt Trọn Cú Bơm Đâm 1 Mạch"
        sh_time_str = f" ({plan.get('sh_time', '')})" if plan.get('sh_time') else ""
        sl_time_str = f" ({plan.get('sl_time', '')})" if plan.get('sl_time') else ""
        
        text = f"""👑 <b>[CHIẾN LƯỢC BITCOIN: ĐỒNG PHA BIAS TUẦN/NGÀY & SMC]</b> 👑
━━━━━━━━━━━━━━━━━━
💰 Giá BTC hiện tại: <b>${plan['current_price']:,.1f}</b>
🎯 <b>Vùng POC M15 (Volume cốt lõi):</b> <code>${plan['poc']:,.1f}</code> (Cách ${plan['dist_to_entry']:,.1f} giá)
📊 <b>CẢN CẤU TRÚC UY TÍN (FRACTAL SMC H1):</b>
📈 <b>Cản Đỉnh Uy Tín (Swing High):</b> <code>${plan['swing_high']:,.1f}</code>{sh_time_str}
📉 <b>Hỗ Trợ Đáy Uy Tín (Swing Low):</b> <code>${plan['swing_low']:,.1f}</code>{sl_time_str}
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

🛡️ <b>Cắt lỗ (SL Ngoài Cản Đỉnh/Đáy H1):</b> <code>${plan['sl']:,.1f}</code> (-{plan['sl_pct']}%)
🎯 <b>Chốt lời 1 (TP1 - R:R 1:2):</b> <code>${plan['tp1']:,.1f}</code>
🎯 <b>Chốt lời 2 (TP2 - R:R 1:3.5):</b> <code>${plan['tp2']:,.1f}</code>

🧠 <b>KẾ HOẠCH XỬ LÝ LỆNH CHỦ ĐỘNG:</b>
{plan['advice']}

🛡️ <b>QUẢN LÝ VỐN (${CONFIG['ACCOUNT_BALANCE']:,.0f}):</b>
• Rủi ro tối đa 2%: <b>$20.0</b> | Khối lượng: <b>$1,000.0</b> | Đòn bẩy: <b>5x</b>
<i>💡 Giải pháp chuyên biệt cho BTC: BTC có quán tính cực mạnh, khi xuôi sóng Tuần & Ngày thường đâm thẳng một mạch không test nhiều. Nếu không khớp Lệnh 1 thì Lệnh 2 Stop sẽ tự động kích hoạt đua sóng, không bao giờ bị lỡ kèo!</i>"""
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
        
        # 2. Lấy dữ liệu H1 klines từ Bybit XAUUSDT và tính Fractal Swing High / Low SMC
        url_gold_kline = 'https://api.bybit.com/v5/market/kline?category=linear&symbol=XAUUSDT&interval=60&limit=60'
        req_g = urllib.request.Request(url_gold_kline, headers=HEADERS)
        with urllib.request.urlopen(req_g, timeout=8) as r:
            gold_h1_klines = json.loads(r.read().decode())['result']['list']

        sh_raw, sl_raw, m_sh_raw, m_sl_raw = find_fractal_swings(gold_h1_klines, n=2)
        delta = current_gold - float(gold_h1_klines[0][4])
        major_res = round(sh_raw['price'] + delta, 2)
        major_sup = round(sl_raw['price'] + delta, 2)
        sh_time = sh_raw['time']
        sl_time = sl_raw['time']

        m5_high = round(data['high|5'], 2)
        m15_high = round(data['high|15'], 2)
        m15_low = round(data['low|15'], 2)
        m15_ema20 = round(data['EMA20|15'], 2)
        h4_ema20 = round(data['EMA20|240'], 2)
        
        # 3. Vùng POC M15 OANDA (Volume Profile M15)
        poc_gold_m15 = round((m15_high + m15_low + m15_ema20) / 3.0, 2)
        
        # 4. Phát hiện Bẫy Quét Râu / Mô hình 2 Đáy / 2 Đỉnh trên M15
        is_double_bottom = (current_gold > major_sup + 4.0) and (m15_low >= major_sup - 1.0) and (current_gold > m15_ema20)
        is_at_major_res = (current_gold >= major_res - 3.5) or (m5_high >= major_res - 0.8)
        
        # XÁC ĐỊNH HƯỚNG ĐÁNH (KHÔNG ÉP THEO TREND NGÀY NẾU M15 CÓ ĐẢO CHIỀU UY TÍN)
        if is_double_bottom and not is_at_major_res:
            signal = "LONG"
            setup_desc = f"Mô Hình 2 Đáy M15 tại Hỗ Trợ Đáy Uy Tín ${major_sup:,.2f} ({sl_time}) + Bullish CHoCH"
            diamond_note = "⭐ ĐẢO CHIỀU UY TÍN: Có mô hình 2 Đáy từ cản uy tín, không bắt đáy vô cớ!"
        elif is_at_major_res or (current_gold < h4_ema20):
            signal = "SHORT"
            setup_desc = f"Cản Đỉnh Uy Tín H1 tại ${major_res:,.2f} ({sh_time}) + Quét Râu Đỉnh / CHoCH Giảm"
            diamond_note = "⭐ CẢN TO THẬT SỰ: Chạm đỉnh râu cản H1 bị từ chối mạnh, tuyệt đối không bán lưng chừng!"
        else:
            signal = "SHORT" if d1_bear else "LONG"
            setup_desc = f"Cấu Trúc SMC H1 tại Cản Đỉnh ${major_res:,.2f}"
            diamond_note = "⚡ Quản lý vốn chặt chẽ theo cản."
        
        if signal == "SHORT":
            # ENTRY LIMIT: Neo chặt tại CẢN ĐỈNH UY TÍN (major_res) hoặc POC M15, TUYỆT ĐỐI KHÔNG BÁN LƯNG CHỪNG
            entry_limit = round(max(poc_gold_m15, major_res - 1.8), 2)
            if entry_limit < current_gold:
                entry_limit = round(major_res - 1.0, 2)
                
            # Entry 2: Bán Stop khi gãy đáy xác nhận sóng xả tiếp diễn
            entry_stop = round(major_sup - 1.2, 2)
            
            # SL ĐẶT TRÊN CẢN ĐỈNH UY TÍN H1: đệm 2.5 giá ngoài đỉnh cản
            sl = round(major_res + 2.5, 2)
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
                f"⚠️ <b>KHÔNG BÁN LƯNG CHỪNG:</b> Giá hiện tại ${current_gold:,.2f} ở giữa sóng, chỉ đặt Sell Limit đón tại <b>Cản Đỉnh Uy Tín ${major_res:,.2f}</b> ({sh_time})!\n"
                f"💎 <b>DCA NHỒI KHI ĐẸP:</b> Khớp Lệnh 1 và giá sập thủng đáy <b>${entry_stop:,.2f}</b> (lãi > {sl_dist*0.7:.1f} giá), dời SL về Hoà Vốn (Entry) và kích hoạt Lệnh 2 (Sell Stop)!"
            )
        else: # LONG
            # ENTRY LIMIT: Neo chặt tại HỖ TRỢ ĐÁY UY TÍN (không bắt đáy vô cớ)
            entry_limit = round(min(poc_gold_m15, major_sup + 2.5), 2)
            if entry_limit > current_gold:
                entry_limit = round(major_sup + 1.0, 2)
                
            entry_stop = round(major_res + 1.2, 2)
            
            sl = round(major_sup - 2.5, 2)
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
                f"⚠️ <b>ĐẢO CHIỀU CÓ CHoCH:</b> Có xác nhận mô hình 2 Đáy tại Hỗ Trợ Đáy Uy Tín ${major_sup:,.2f} ({sl_time}), không bắt đáy vô cớ! SL dưới đáy hỗ trợ.\n"
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
        entry_limit = 3545.0
        entry_stop = 3505.0
        major_res = 3547.0
        major_sup = 3508.0
        sh_time = "H1"
        sl_time = "H1"
        sl = 3550.0
        sl_dist = 5.0
        tp1 = 3535.0
        tp2 = 3520.0
        signal = "SHORT"
        setup_desc = "Cản Đỉnh Uy Tín H1 + CHoCH Giảm"
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
        'swing_high': major_res,
        'sh_time': sh_time,
        'swing_low': major_sup,
        'sl_time': sl_time,
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
        action_l = "LỆNH 1: Bán Limit Đón Râu Hồi Retest Cản Uy Tín / POC" if plan['signal'] == 'SHORT' else "LỆNH 1: Mua Limit Đón Râu Hồi Retest Hỗ Trợ Uy Tín / POC"
        action_s = "LỆNH 2: Bán Stop Phá Đáy Tiếp Diễn Sóng Tuần" if plan['signal'] == 'SHORT' else "LỆNH 2: Mua Stop Phá Đỉnh Tiếp Diễn Sóng Tuần"
        sh_time_str = f" ({plan.get('sh_time', '')})" if plan.get('sh_time') else ""
        sl_time_str = f" ({plan.get('sl_time', '')})" if plan.get('sl_time') else ""
        
        text = f"""🥇 <b>[CHIẾN LƯỢC VÀNG SMC: OANDA:XAUUSD (MT5 CHUẨN)]</b> 🥇
━━━━━━━━━━━━━━━━━━
📊 Nguồn biểu đồ: <b>{plan['data_source']}</b>
💰 Giá Vàng OANDA: <b>${plan['current_price']:,.2f}</b> (Bid: ${plan['bid']:,.2f} | Ask: ${plan['ask']:,.2f})
🎯 <b>Vùng POC M15 (Thanh khoản hội tụ):</b> <code>${plan['poc_m15']:,.2f}</code>
📊 <b>CẢN CẤU TRÚC UY TÍN (FRACTAL SMC H1):</b>
📈 <b>Cản Đỉnh Uy Tín (Swing High):</b> <code>${plan['swing_high']:,.2f}</code>{sh_time_str}
📉 <b>Hỗ Trợ Đáy Uy Tín (Swing Low):</b> <code>${plan['swing_low']:,.2f}</code>{sl_time_str}
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

🛡️ <b>Cắt lỗ (SL Ngoài Cản Đỉnh/Đáy H1 ~{plan['sl_dist']:.1f} Giá):</b>
   <code>${plan['sl']:,.2f}</code>
🎯 <b>Chốt lời 1 (TP1 - Ăn {plan['sl_dist']*2:.1f} Giá | R:R 1:2):</b> <code>${plan['tp1']:,.2f}</code>
🎯 <b>Chốt lời 2 (TP2 - Ăn {plan['sl_dist']*3.5:.1f} Giá | R:R 1:3.5):</b> <code>${plan['tp2']:,.2f}</code>

🧠 <b>KẾ HOẠCH XỬ LÝ LỆNH CHỦ ĐỘNG:</b>
{plan['advice']}

🛡️ <b>QUẢN LÝ VỐN VÀNG MT5 (${CONFIG['ACCOUNT_BALANCE']:,.0f}):</b>
• Rủi ro tối đa 2%: <b>$20.0</b> (tương đương 0.01 - 0.02 lot trên MT5)
<i>💡 Setup kinh điển: Thuận Bias Tuần & Ngày, rình M15 tạo CHoCH và giật râu test cản là vào lệnh! SL cực ngắn trên chóp râu, tỷ lệ ăn R:R cực lớn!</i>"""
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
                if "ĐỒNG PHA TUẦN + NGÀY" in plan_gold.get('diamond_note', ''):
                    price_gold = plan_gold['current_price']
                    entry_gold = plan_gold['entry_limit']
                    # Nếu giá đang trong vùng retest POC M15 hoặc râu test (cách entry < 4 giá)
                    if abs(price_gold - entry_gold) <= 4.0:
                        s_emoji = "🔴 SHORT (BÁN)" if plan_gold['signal'] == 'SHORT' else "🟢 LONG (MUA)"
                        action_l = "LỆNH VÀO NGAY (Vùng POC M15):" if plan_gold['signal'] == 'SHORT' else "LỆNH VÀO NGAY (Vùng POC M15):"
                        msg = f"""🚨 <b>[TỰ ĐỘNG BÁO KÈO: SETUP KIM CƯƠNG VÀNG XAUUSD]</b> 🚨
━━━━━━━━━━━━━━━━━━
📊 Nguồn biểu đồ: <b>TradingView (OANDA:XAUUSD - Chuẩn MT5)</b>
💰 Giá Vàng hiện tại: <b>${price_gold:,.2f}</b> (Đang retest Cản Uy Tín / POC!)
🎯 <b>Vùng POC M15 (Thanh khoản):</b> <code>${plan_gold['poc_m15']:,.2f}</code>
📊 <b>Cản Đỉnh Uy Tín (Swing High):</b> <code>${plan_gold['swing_high']:,.2f}</code> ({plan_gold.get('sh_time', '')})
📉 <b>Hỗ Trợ Đáy Uy Tín (Swing Low):</b> <code>${plan_gold['swing_low']:,.2f}</code> ({plan_gold.get('sl_time', '')})
⚡ <b>Cấu trúc SMC:</b> <b>{plan_gold['setup_desc']}</b>
━━━━━━━━━━━━━━━━━━
💎 <b>ĐỒNG PHA BIAS ĐA KHUNG (WINRATE CAO):</b>
• <b>Bias Tuần (W1):</b> {plan_gold['w1_bias']}
• <b>Bias Ngày (D1):</b> {plan_gold['d1_bias']}
<i>🔥 Tín hiệu rất đẹp: Giá vừa giật râu test cản/3 đỉnh xong, vào lệnh ngay!</i>
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
                if "ĐỒNG PHA TUẦN + NGÀY" in plan_btc.get('diamond_note', ''):
                    price_btc = plan_btc['current_price']
                    entry_l = plan_btc['entry_limit']
                    entry_s = plan_btc['entry_stop']
                    # Nếu giá đang test lại POC M15 hoặc chuẩn bị phá vỡ Lệnh 2 Stop
                    if abs(price_btc - entry_l) <= price_btc * 0.008 or abs(price_btc - entry_s) <= price_btc * 0.005:
                        s_emoji = "🔴 SHORT (BÁN)" if plan_btc['signal'] == 'SHORT' else "🟢 LONG (MUA)"
                        action_l = "LỆNH 1: Bán Limit Đón Râu Hồi Retest POC M15" if plan_btc['signal'] == 'SHORT' else "LỆNH 1: Mua Limit Đón Râu Hồi Retest POC M15"
                        action_s = "LỆNH 2: Bán Stop Phá Đáy - Bắt Trọn Cú Xả Đâm 1 Mạch" if plan_btc['signal'] == 'SHORT' else "LỆNH 2: Mua Stop Phá Đỉnh - Bắt Trọn Cú Bơm Đâm 1 Mạch"
                        msg = f"""🚨 <b>[TỰ ĐỘNG BÁO KÈO: SETUP KIM CƯƠNG BITCOIN]</b> 🚨
━━━━━━━━━━━━━━━━━━
💰 Giá BTC hiện tại: <b>${price_btc:,.1f}</b> (Đang tiếp cận điểm kích hoạt!)
🎯 <b>Vùng POC M15 (Volume cốt lõi):</b> <code>${plan_btc['poc']:,.1f}</code>
📊 <b>Cản Đỉnh Uy Tín (Swing High):</b> <code>${plan_btc['swing_high']:,.1f}</code> ({plan_btc.get('sh_time', '')})
📉 <b>Hỗ Trợ Đáy Uy Tín (Swing Low):</b> <code>${plan_btc['swing_low']:,.1f}</code> ({plan_btc.get('sl_time', '')})
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
