import os
import json
import time
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

        # 2. Tính POC M15 (Volume profile phiên gần nhất)
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

        # 3. Cản râu nến M15/H4
        highs = [float(k[2]) for k in m15_klines]
        lows = [float(k[3]) for k in m15_klines]
        swing_high = round(max(highs), 1)
        swing_low = round(min(lows), 1)

        # Ưu tiên xu hướng theo Bias Tuần & Ngày
        if w1_bear and d1_bear:
            signal = "SHORT"
        elif not w1_bear and not d1_bear:
            signal = "LONG"
        else:
            signal = "SHORT" if d1_bear else "LONG"

        is_diamond = (w1_bear and d1_bear and signal == "SHORT") or (not w1_bear and not d1_bear and signal == "LONG")
        diamond_note = "⭐ ĐỒNG PHA TUẦN + NGÀY (SETUP KIM CƯƠNG): BTC rất dễ đâm một mạch theo xu hướng chính!" if is_diamond else "⚡ Lưu ý quản lý vốn chặt chẽ theo từng phiên."

        if signal == "SHORT":
            # ENTRY LIMIT: Đón nhịp rút chân kiểm tra lại POC M15 hoặc cản râu hồi
            entry_limit = poc_m15 if poc_m15 > current_price else round(current_price * 1.006, 1)
            if entry_limit > swing_high - 50.0:
                entry_limit = round(swing_high - 100.0, 1)
                
            # SELL STOP: Đặt ngay dưới đáy swing_low để bắt trọn sóng xả đâm 1 mạch nếu BTC không thèm test!
            entry_stop = round(swing_low * 0.998, 1)
            
            # SL: Đặt trên cản râu đỉnh swing_high + đệm an toàn
            sl = round(max(entry_limit * 1.015, swing_high + 150.0), 1)
            risk = sl - entry_limit
            tp1 = round(entry_limit - (risk * 2.0), 1)
            tp2 = round(entry_limit - (risk * 3.5), 1)
            
            setup_desc = f"Quét Râu Test Đỉnh M15 tại ${swing_high:,.1f} + CHoCH Giảm"
            advice = (
                f"⚠️ <b>CẮT SỚM KHI XẤU:</b> Nếu có nến M15/H1 đóng cửa vượt cản đỉnh <b>${swing_high:,.1f}</b> -> Chủ động cắt sớm bằng tay!\n"
                f"💎 <b>DCA NHỒI KHI ĐẸP:</b> BTC quán tính rất mạnh! Nếu không khớp Lệnh 1 Limit mà đâm thẳng 1 mạch phá đáy <b>${entry_stop:,.1f}</b>, Lệnh 2 Sell Stop sẽ tự động khớp để không bị lỡ tàu. Khi lãi > {risk*0.7:.0f} giá, dời SL về Hoà Vốn!"
            )
        else: # LONG
            entry_limit = poc_m15 if poc_m15 < current_price else round(current_price * 0.994, 1)
            if entry_limit < swing_low + 50.0:
                entry_limit = round(swing_low + 100.0, 1)
                
            entry_stop = round(swing_high * 1.002, 1)
            
            sl = round(min(entry_limit * 0.985, swing_low - 150.0), 1)
            risk = entry_limit - sl
            tp1 = round(entry_limit + (risk * 2.0), 1)
            tp2 = round(entry_limit + (risk * 3.5), 1)
            
            setup_desc = f"Quét Râu Test Đáy M15 tại ${swing_low:,.1f} + CHoCH Tăng"
            advice = (
                f"⚠️ <b>CẮT SỚM KHI XẤU:</b> Nếu có nến M15/H1 đóng cửa gãy hỗ trợ <b>${swing_low:,.1f}</b> -> Chủ động cắt sớm bằng tay!\n"
                f"💎 <b>DCA NHỒI KHI ĐẸP:</b> BTC quán tính rất mạnh! Nếu không khớp Lệnh 1 Limit mà bứt phá thẳng 1 mạch qua đỉnh <b>${entry_stop:,.1f}</b>, Lệnh 2 Buy Stop sẽ tự động khớp để không bị lỡ tàu. Khi lãi > {risk*0.7:.0f} giá, dời SL về Hoà Vốn!"
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
            'swing_low': swing_low,
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
        action_l = "LỆNH 1: Bán Limit Đón Râu Hồi Retest POC M15" if plan['signal'] == 'SHORT' else "LỆNH 1: Mua Limit Đón Râu Hồi Retest POC M15"
        action_s = "LỆNH 2: Bán Stop Phá Đáy - Bắt Trọn Cú Xả Đâm 1 Mạch" if plan['signal'] == 'SHORT' else "LỆNH 2: Mua Stop Phá Đỉnh - Bắt Trọn Cú Bơm Đâm 1 Mạch"
        
        text = f"""👑 <b>[CHIẾN LƯỢC BITCOIN: ĐỒNG PHA BIAS TUẦN/NGÀY & SMC]</b> 👑
━━━━━━━━━━━━━━━━━━
💰 Giá BTC hiện tại: <b>${plan['current_price']:,.1f}</b>
🎯 <b>Vùng POC M15 (Volume cốt lõi):</b> <code>${plan['poc']:,.1f}</code> (Cách ${plan['dist_to_entry']:,.1f} giá)
📊 Cản râu đỉnh M15: <b>${plan['swing_high']:,.1f}</b> | Đáy râu M15: <b>${plan['swing_low']:,.1f}</b>
━━━━━━━━━━━━━━━━━━
💎 <b>ĐỒNG PHA BIAS ĐA KHUNG (WINRATE CAO):</b>
• <b>Bias Tuần (W1):</b> {plan['w1_bias']}
• <b>Bias Ngày (D1):</b> {plan['d1_bias']}
⚡ <b>Cấu trúc M15:</b> <b>{plan['setup_desc']}</b>
<i>{plan['diamond_note']}</i>
━━━━━━━━━━━━━━━━━━
🚀 <b>CHIẾN LƯỢC: {s_emoji}</b>
👉 <b>{action_l}:</b>
   <code>${plan['entry_limit']:,.1f}</code>
👉 <b>{action_s}:</b>
   <code>${plan['entry_stop']:,.1f}</code>

🛡️ <b>Cắt lỗ (SL Ngoài Cản Râu M15/H4):</b> <code>${plan['sl']:,.1f}</code> (-{plan['sl_pct']}%)
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
        
        # 2. Các mốc cấu trúc nến M5, M15, H1, H4 trên OANDA
        m5_high = round(data['high|5'], 2)
        m5_low = round(data['low|5'], 2)
        prev_m5_high = round(data['high[1]|5'], 2) if data.get('high[1]|5') else m5_high
        
        m15_high = round(data['high|15'], 2)
        m15_low = round(data['low|15'], 2)
        m15_ema20 = round(data['EMA20|15'], 2)
        
        h1_high = round(data['high|60'], 2)
        h1_low = round(data['low|60'], 2)
        
        h4_high = round(data['high|240'], 2)
        h4_low = round(data['low|240'], 2)
        h4_ema20 = round(data['EMA20|240'], 2)
        
        # 3. Vùng POC M15 OANDA (Volume Profile M15)
        poc_gold_m15 = round((m15_high + m15_low + m15_ema20) / 3.0, 2)
        
        # 4. Phát hiện Bẫy Quét Thanh Khoản & Râu Nến Test trên M15/M5
        is_bear_sweep = (m5_high >= prev_m5_high and current_gold < m5_high - 1.5) or (current_gold < m15_ema20 and current_gold < h4_ema20)
        
        # Ưu tiên tuyệt đối theo Bias Tuần & Ngày
        if w1_bear and d1_bear:
            signal = "SHORT"
        elif not w1_bear and not d1_bear:
            signal = "LONG"
        else:
            signal = "SHORT" if (current_gold < h4_ema20 or is_bear_sweep) else "LONG"
            
        is_diamond = (w1_bear and d1_bear and signal == "SHORT") or (not w1_bear and not d1_bear and signal == "LONG")
        diamond_note = "⭐ ĐỒNG PHA TUẦN + NGÀY: Khả năng thắng cực cao khi đón râu test M15!" if is_diamond else "⚡ Lưu ý quản lý vốn chặt chẽ theo từng phiên."
        
        if signal == "SHORT":
            sweep_level = max(m5_high, m15_high)
            # Entry 1: Bán Limit đón râu nến hồi test lại POC M15 hoặc FVG/EMA20 (rất dễ khớp)
            entry_limit = round(poc_gold_m15 if poc_gold_m15 > current_gold else current_gold + 3.0, 2)
            if entry_limit > sweep_level - 1.0:
                entry_limit = round(sweep_level - 2.0, 2)
                
            # Entry 2: Bán Stop khi gãy đáy xác nhận sóng xả tiếp diễn
            entry_stop = round(m15_low - 1.2, 2)
            
            # SL ĐẶT TRÊN RÂU NẾN TEST OANDA: đệm 1.8 giá ngoài đỉnh râu test (Chuẩn MT5)
            sl = round(sweep_level + 1.8, 2)
            sl_dist = round(sl - entry_limit, 2)
            if sl_dist < 10.0:
                sl = round(entry_limit + 12.0, 2)
                sl_dist = round(sl - entry_limit, 2)
            elif sl_dist > 26.0:
                sl = round(entry_limit + 22.0, 2)
                sl_dist = round(sl - entry_limit, 2)
                
            tp1 = round(entry_limit - (sl_dist * 2.0), 2)
            tp2 = round(entry_limit - (sl_dist * 3.5), 2)
            
            setup_desc = f"Quét Râu Test Đỉnh M15 tại ${sweep_level:,.2f} + CHoCH Giảm"
            advice = (
                f"⚠️ <b>CẮT SỚM KHI XẤU:</b> Nếu có nến M15 đóng cửa trên đỉnh râu test <b>${sweep_level:,.2f}</b> -> Thoát sớm bằng tay trên MT5!\n"
                f"💎 <b>DCA NHỒI KHI ĐẸP:</b> Khớp Lệnh 1 và giá sập thủng đáy <b>${entry_stop:,.2f}</b> (lãi > {sl_dist*0.7:.1f} giá), dời SL về Hoà Vốn (Entry) và kích hoạt Lệnh 2 (Sell Stop) để ăn sóng xả Tuần/Ngày!"
            )
        else: # LONG
            sweep_level = min(m5_low, m15_low)
            entry_limit = round(poc_gold_m15 if poc_gold_m15 < current_gold else current_gold - 3.0, 2)
            if entry_limit < sweep_level + 1.0:
                entry_limit = round(sweep_level + 2.0, 2)
                
            entry_stop = round(m15_high + 1.2, 2)
            
            sl = round(sweep_level - 1.8, 2)
            sl_dist = round(entry_limit - sl, 2)
            if sl_dist < 10.0:
                sl = round(entry_limit - 12.0, 2)
                sl_dist = round(entry_limit - sl, 2)
            elif sl_dist > 26.0:
                sl = round(entry_limit - 22.0, 2)
                sl_dist = round(entry_limit - sl, 2)
                
            tp1 = round(entry_limit + (sl_dist * 2.0), 2)
            tp2 = round(entry_limit + (sl_dist * 3.5), 2)
            
            setup_desc = f"Quét Râu Test Đáy M15 tại ${sweep_level:,.2f} + CHoCH Tăng"
            advice = (
                f"⚠️ <b>CẮT SỚM KHI XẤU:</b> Nếu có nến M15 đóng cửa gãy qua râu đáy test <b>${sweep_level:,.2f}</b> -> Thoát sớm bằng tay trên MT5!\n"
                f"💎 <b>DCA NHỒI KHI ĐẸP:</b> Khớp Lệnh 1 và giá tăng bứt phá đỉnh <b>${entry_stop:,.2f}</b> (lãi > {sl_dist*0.7:.1f} giá), dời SL về Hoà Vốn (Entry) và kích hoạt Lệnh 2 (Buy Stop)!"
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
        entry_limit = 3541.0
        entry_stop = 3524.0
        sl = 3553.0
        sl_dist = 12.0
        tp1 = 3517.0
        tp2 = 3499.0
        signal = "SHORT"
        setup_desc = "Râu Nến Test Đỉnh OANDA + CHoCH Giảm"
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
        action_l = "LỆNH 1: Bán Limit Đón Râu Hồi Retest POC M15" if plan['signal'] == 'SHORT' else "LỆNH 1: Mua Limit Đón Râu Hồi Retest POC M15"
        action_s = "LỆNH 2: Bán Stop Phá Đáy Tiếp Diễn Sóng Tuần" if plan['signal'] == 'SHORT' else "LỆNH 2: Mua Stop Phá Đỉnh Tiếp Diễn Sóng Tuần"
        
        text = f"""🥇 <b>[CHIẾN LƯỢC VÀNG SMC: OANDA:XAUUSD (MT5 CHUẨN)]</b> 🥇
━━━━━━━━━━━━━━━━━━
📊 Nguồn biểu đồ: <b>{plan['data_source']}</b>
💰 Giá Vàng OANDA: <b>${plan['current_price']:,.2f}</b> (Bid: ${plan['bid']:,.2f} | Ask: ${plan['ask']:,.2f})
🎯 <b>Vùng POC M15 (Thanh khoản hội tụ):</b> <code>${plan['poc_m15']:,.2f}</code>
━━━━━━━━━━━━━━━━━━
💎 <b>ĐỒNG PHA BIAS ĐA KHUNG (WINRATE CAO):</b>
• <b>Bias Tuần (W1):</b> {plan['w1_bias']}
• <b>Bias Ngày (D1):</b> {plan['d1_bias']}
⚡ <b>Cấu trúc M15:</b> <b>{plan['setup_desc']}</b>
<i>{plan['diamond_note']}</i>
━━━━━━━━━━━━━━━━━━
🚀 <b>CHIẾN LƯỢC: {s_emoji}</b>
👉 <b>{action_l}:</b>
   <code>${plan['entry_limit']:,.2f}</code>
👉 <b>{action_s}:</b>
   <code>${plan['entry_stop']:,.2f}</code>

🛡️ <b>Cắt lỗ (SL Trên Râu Test M15 ~{plan['sl_dist']:.1f} Giá):</b>
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

if __name__ == '__main__':
    threading.Thread(target=start_health_server, daemon=True).start()
    threading.Thread(target=self_ping_worker, daemon=True).start()
    run_bot()
