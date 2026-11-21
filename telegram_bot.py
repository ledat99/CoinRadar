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
# 1. TÍNH ENTRY THEO POC M15 & CẢN RÂU NẾN H4 (DỄ KHỚP LỆNH, R:R CAO)
# ==========================================
def calculate_btc_h4_plan():
    now = time.time()
    # Cache giữ nguyên trong 1 tiếng để đảm bảo không bị nhảy giá liên tục
    if PLAN_CACHE['BTC']['data'] and (now - PLAN_CACHE['BTC']['candle_time'] < 3600):
        return PLAN_CACHE['BTC']['data']
        
    # Lấy 24 nến M15 (phiên 6 tiếng gần nhất) để tính Volume Profile POC thực tế
    url = 'https://api.bybit.com/v5/market/kline?category=linear&symbol=BTCUSDT&interval=15&limit=24'
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode())['result']['list']
        
    current_price = float(data[0][4])
    
    # 1. Tính POC M15 (Vùng thanh khoản tập trung lớn nhất phiên gần nhất)
    prices = []
    weights = []
    for k in data:
        high = float(k[2])
        low = float(k[3])
        vol = float(k[5])
        for p in np.linspace(low, high, 5):
            prices.append(p)
            weights.append(vol / 5.0)
            
    hist, bin_edges = np.histogram(prices, bins=25, weights=weights)
    poc_m15 = round((bin_edges[np.argmax(hist)] + bin_edges[np.argmax(hist)+1]) / 2, 1)
    
    # 2. Cản râu nến H4 (Đỉnh râu cao nhất & Đáy râu thấp nhất của phiên)
    highs = [float(k[2]) for k in data]
    lows = [float(k[3]) for k in data]
    swing_high_h4 = round(max(highs), 1)
    swing_low_h4 = round(min(lows), 1)
    
    is_uptrend = current_price >= poc_m15
    signal = "LONG" if is_uptrend else "SHORT"
    
    if signal == "SHORT":
        # ENTRY LIMIT: Đặt đúng tại POC M15 (Nếu POC cao hơn giá hiện tại để đón râu hồi)
        # Nếu POC đang thấp hơn giá hiện tại thì lấy cản râu hồi gần nhất
        entry_limit = poc_m15 if poc_m15 > current_price else round(current_price * 1.006, 1)
        # SELL STOP: Đặt khi đâm thủng đáy râu hỗ trợ H4
        entry_stop = round(swing_low_h4 * 0.998, 1)
        # SL LINH HOẠT: Đặt trên cản đỉnh râu H4 + đệm an toàn
        sl = round(max(entry_limit * 1.015, swing_high_h4 + 150.0), 1)
        risk = sl - entry_limit
        tp1 = round(entry_limit - (risk * 2.0), 1)
        tp2 = round(entry_limit - (risk * 3.5), 1)
    else: # LONG
        entry_limit = poc_m15 if poc_m15 < current_price else round(current_price * 0.994, 1)
        entry_stop = round(swing_high_h4 * 1.002, 1)
        sl = round(min(entry_limit * 0.985, swing_low_h4 - 150.0), 1)
        risk = entry_limit - sl
        tp1 = round(entry_limit + (risk * 2.0), 1)
        tp2 = round(entry_limit + (risk * 3.5), 1)
        
    sl_pct = (risk / entry_limit) * 100.0
    dist_to_entry = round(abs(current_price - entry_limit), 1)
    
    plan = {
        'signal': signal,
        'current_price': current_price,
        'poc': poc_m15,
        'swing_high': swing_high_h4,
        'swing_low': swing_low_h4,
        'entry_limit': entry_limit,
        'entry_stop': entry_stop,
        'dist_to_entry': dist_to_entry,
        'sl': sl,
        'sl_pct': round(sl_pct, 2),
        'tp1': tp1,
        'tp2': tp2
    }
    PLAN_CACHE['BTC']['data'] = plan
    PLAN_CACHE['BTC']['candle_time'] = now
    return plan

def handle_btc():
    try:
        plan = calculate_btc_h4_plan()
        s_emoji = "🟢 LONG" if plan['signal'] == 'LONG' else "🔴 SHORT"
        action_l = "Đón Râu Hồi Về Đúng Vùng POC M15" if plan['signal'] == 'SHORT' else "Mua Giá Thấp Tại Vùng POC M15"
        action_s = "Bán Tháo Khi Thủng Đáy Râu H4" if plan['signal'] == 'SHORT' else "Mua Đuổi Khi Vượt Đỉnh Râu H4"
        
        text = f"""👑 <b>[KẾ HOẠCH BITCOIN: ENTRY POC M15 & CẢN RÂU H4]</b> 👑
━━━━━━━━━━━━━━━━━━
💰 Giá hiện tại: <b>${plan['current_price']:,.1f}</b>
🎯 <b>Vùng POC M15 (Volume cốt lõi):</b> <code>${plan['poc']:,.1f}</code> (Cách ${plan['dist_to_entry']:,.1f} giá)
📊 Cản râu đỉnh H4: <b>${plan['swing_high']:,.1f}</b> | Đáy râu H4: <b>${plan['swing_low']:,.1f}</b>
━━━━━━━━━━━━━━━━━━
🚀 <b>CHIẾN LƯỢC: {s_emoji}</b>
👉 <b>1. LỆNH LIMIT THEO POC M15 ({action_l}):</b>
   <code>${plan['entry_limit']:,.1f}</code>
👉 <b>2. LỆNH STOP PHÁ VỠ ({action_s}):</b>
   <code>${plan['entry_stop']:,.1f}</code>

🛡️ <b>Cắt lỗ (SL Linh Hoạt Trên Cản Râu H4):</b> <code>${plan['sl']:,.1f}</code> (-{plan['sl_pct']}%)
🎯 <b>Chốt lời 1 (TP1 - R:R 1:2):</b> <code>${plan['tp1']:,.1f}</code>
🎯 <b>Chốt lời 2 (TP2 - R:R 1:3.5):</b> <code>${plan['tp2']:,.1f}</code>

🛡️ <b>QUẢN LÝ VỐN (${CONFIG['ACCOUNT_BALANCE']:,.0f}):</b>
• Rủi ro tối đa 2%: <b>$20.0</b> | Khối lượng: <b>$1,000.0</b> | Đòn bẩy: <b>5x</b>
<i>💡 Điểm vào Entry bám sát theo vùng POC M15 nên cực kỳ dễ khớp đón nhịp giật râu, SL đặt trên cản râu H4 an toàn!</i>"""
        send_telegram(text, reply_markup=get_main_keyboard())
    except Exception as e:
        send_telegram(f"Lỗi BTC POC: {e}", reply_markup=get_main_keyboard())

# ==========================================
# 2. KẾ HOẠCH VÀNG (SMC) - QUÉT RÂU THANH KHOẢN (SWEEP) + CHoCH & RETEST POC M15
# ==========================================
def fetch_gold_bybit_klines(interval='5', limit=100):
    url = f'https://api.bybit.com/v5/market/kline?category=linear&symbol=XAUUSDT&interval={interval}&limit={limit}'
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=8) as r:
        raw = json.loads(r.read().decode())['result']['list']
    klines = []
    for k in reversed(raw):
        ts = int(k[0]) / 1000
        dt = time.strftime('%H:%M', time.localtime(ts))
        klines.append({
            'time': dt,
            'open': float(k[1]),
            'high': float(k[2]),
            'low': float(k[3]),
            'close': float(k[4]),
            'vol': float(k[5])
        })
    return klines

def calculate_gold_h4_plan():
    now = time.time()
    if PLAN_CACHE['GOLD']['data'] and (now - PLAN_CACHE['GOLD']['candle_time'] < 3600):
        return PLAN_CACHE['GOLD']['data']
        
    try:
        # Lấy dữ liệu nến M5 và M15 từ Bybit XAUUSDT (Dữ liệu tick chuẩn theo Gold quốc tế)
        m5 = fetch_gold_bybit_klines('5', 100)
        m15 = fetch_gold_bybit_klines('15', 60)
        current_gold = m5[-1]['close']
        data_source = "Bybit XAUUSDT (Nến M5/M15 Thực Chiến)"
        
        # 1. Tính POC M15 (Volume profile 24 nến M15 gần nhất ~ 6 tiếng)
        recent_m15 = m15[-24:]
        price_bins = {}
        for c in recent_m15:
            step = 1.0
            for p in [round(c['low']/step)*step, round(((c['high']+c['low'])/2.0)/step)*step, round(c['high']/step)*step]:
                price_bins[p] = price_bins.get(p, 0) + (c['vol'] / 3.0)
        poc_gold_m15 = max(price_bins.items(), key=lambda x: x[1])[0] if price_bins else current_gold

        # 2. Phát hiện Quét Thanh Khoản (Liquidity Sweep) trên nến M5
        highs = [c['high'] for c in m5[-60:-5]]
        lows = [c['low'] for c in m5[-60:-5]]
        swing_high = max(highs) if highs else current_gold + 10.0
        swing_low = min(lows) if lows else current_gold - 10.0
        
        # Quét râu đỉnh (Bearish Sweep): High rướn lên/vượt cản nhưng rút râu xả ngược (như cây nến 22h)
        sweep_bear = None
        for c in reversed(m5[-30:]):
            c_range = c['high'] - c['low']
            upper_wick = c['high'] - max(c['open'], c['close'])
            if c['high'] >= swing_high - 1.0:
                if c['close'] < c['high'] - 1.5 or (c_range > 2.0 and upper_wick / c_range > 0.35):
                    sweep_bear = c
                    break
                    
        # Quét râu đáy (Bullish Sweep): Low quét thủng cản nhưng rút râu tăng ngược
        sweep_bull = None
        for c in reversed(m5[-30:]):
            c_range = c['high'] - c['low']
            lower_wick = min(c['open'], c['close']) - c['low']
            if c['low'] <= swing_low + 1.0:
                if c['close'] > c['low'] + 1.5 or (c_range > 2.0 and lower_wick / c_range > 0.35):
                    sweep_bull = c
                    break
                    
        ema20_m15 = sum([c['close'] for c in m15[-20:]]) / 20.0
        
        if sweep_bear and not sweep_bull:
            signal = "SHORT"
        elif sweep_bull and not sweep_bear:
            signal = "LONG"
        else:
            signal = "SHORT" if current_gold < ema20_m15 else "LONG"
            
        recent_min_5 = min([c['low'] for c in m5[-6:]])
        recent_max_5 = max([c['high'] for c in m5[-6:]])
        
        if signal == "SHORT":
            sweep_level = sweep_bear['high'] if sweep_bear else swing_high
            sweep_time = sweep_bear['time'] if sweep_bear else "Phiên gần"
            
            # Entry 1: Bán Limit đón râu hồi retest vùng POC M15 hoặc FVG/EMA20 (rất dễ khớp)
            entry_limit = round(max(current_gold + 2.5, min(poc_gold_m15, sweep_level - 2.5)), 2)
            # Entry 2: Bán Stop khi gãy đáy xác nhận sóng xả tiếp diễn
            entry_stop = round(recent_min_5 - 1.2, 2)
            
            # SL ĐẶT TRÊN RÂU QUÉT: đệm 1.8 giá ngoài đỉnh quét (Hợp lý trong ngưỡng 12-25 giá)
            sl = round(max(sweep_level + 1.8, entry_limit + 12.0), 2)
            if (sl - entry_limit) > 26.0:
                sl = round(entry_limit + 22.0, 2)
            sl_dist = round(sl - entry_limit, 2)
            
            tp1 = round(entry_limit - (sl_dist * 2.0), 2)
            tp2 = round(entry_limit - (sl_dist * 3.5), 2)
            
            setup_desc = f"Quét Râu Đỉnh ({sweep_time} tại ${sweep_level:,.2f}) + CHoCH Giảm"
            advice = (
                f"⚠️ <b>CẮT SỚM KHI XẤU:</b> Nếu có nến M15 đóng cửa vững chắc vượt qua râu quét <b>${sweep_level:,.2f}</b>, cấu trúc bẫy sụp đổ -> Cắt lỗ sớm bằng tay!\n"
                f"💎 <b>DCA NHỒI KHI ĐẸP:</b> Khi Lệnh 1 khớp và giá sập phá vỡ đáy <b>${entry_stop:,.2f}</b> (lãi > {sl_dist*0.7:.1f} giá), dời SL về Hoà Vốn (Entry) và kích hoạt Lệnh 2 (Sell Stop)!"
            )
        else: # LONG
            sweep_level = sweep_bull['low'] if sweep_bull else swing_low
            sweep_time = sweep_bull['time'] if sweep_bull else "Phiên gần"
            
            entry_limit = round(min(current_gold - 2.5, max(poc_gold_m15, sweep_level + 2.5)), 2)
            entry_stop = round(recent_max_5 + 1.2, 2)
            
            sl = round(min(sweep_level - 1.8, entry_limit - 12.0), 2)
            if (entry_limit - sl) > 26.0:
                sl = round(entry_limit - 22.0, 2)
            sl_dist = round(entry_limit - sl, 2)
            
            tp1 = round(entry_limit + (sl_dist * 2.0), 2)
            tp2 = round(entry_limit + (sl_dist * 3.5), 2)
            
            setup_desc = f"Quét Râu Đáy ({sweep_time} tại ${sweep_level:,.2f}) + CHoCH Tăng"
            advice = (
                f"⚠️ <b>CẮT SỚM KHI XẤU:</b> Nếu có nến M15 đóng cửa gãy qua râu đáy quét <b>${sweep_level:,.2f}</b> -> Cắt lỗ sớm bằng tay!\n"
                f"💎 <b>DCA NHỒI KHI ĐẸP:</b> Khi Lệnh 1 khớp và giá tăng bứt phá đỉnh <b>${entry_stop:,.2f}</b> (lãi > {sl_dist*0.7:.1f} giá), dời SL về Hoà Vốn (Entry) và kích hoạt Lệnh 2 (Buy Stop)!"
            )
            
    except Exception as e:
        # Fallback TradingView CFD Scanner nếu Bybit bận
        url = 'https://scanner.tradingview.com/cfd/scan'
        payload = json.dumps({
            'symbols': {'tickers': ['OANDA:XAUUSD']},
            'columns': ['close', 'open', 'high', 'low', 'high|15', 'low|15', 'close|15', 'EMA20|15', 'high|240', 'low|240', 'EMA20|240']
        }).encode()
        req = urllib.request.Request(url, data=payload, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=10) as resp:
            d = json.loads(resp.read().decode())['data'][0]['d']
        current_gold = d[0]
        data_source = "TradingView (OANDA:XAUUSD)"
        m15_high = d[4]
        m15_low = d[5]
        m15_ema20 = d[7]
        poc_gold_m15 = round((m15_high + m15_low + m15_ema20) / 3.0, 2)
        h4_high = d[8]
        h4_low = d[9]
        signal = "SHORT" if current_gold < d[10] else "LONG"
        
        if signal == "SHORT":
            entry_limit = poc_gold_m15 if poc_gold_m15 > current_gold else round(current_gold + 3.5, 2)
            entry_stop = round(m15_low - 1.2, 2)
            sl = round(max(h4_high + 2.0, entry_limit + 14.0), 2)
            sl_dist = round(sl - entry_limit, 2)
            tp1 = round(entry_limit - (sl_dist * 2.0), 2)
            tp2 = round(entry_limit - (sl_dist * 3.5), 2)
            setup_desc = f"Cản Râu Đỉnh H4 tại ${h4_high:,.2f}"
            advice = (
                f"⚠️ <b>CẮT SỚM KHI XẤU:</b> Nếu có nến M15/H1 đóng cửa vượt đỉnh <b>${h4_high:,.2f}</b> -> Cắt lỗ sớm bằng tay!\n"
                f"💎 <b>DCA NHỒI KHI ĐẸP:</b> Khi Lệnh 1 có lãi > {sl_dist*0.7:.1f} giá và phá đáy <b>${entry_stop:,.2f}</b>, dời SL về Entry và nhồi Lệnh 2!"
            )
        else:
            entry_limit = poc_gold_m15 if poc_gold_m15 < current_gold else round(current_gold - 3.5, 2)
            entry_stop = round(m15_high + 1.2, 2)
            sl = round(min(h4_low - 2.0, entry_limit - 14.0), 2)
            sl_dist = round(entry_limit - sl, 2)
            tp1 = round(entry_limit + (sl_dist * 2.0), 2)
            tp2 = round(entry_limit + (sl_dist * 3.5), 2)
            setup_desc = f"Hỗ Trợ Đáy H4 tại ${h4_low:,.2f}"
            advice = (
                f"⚠️ <b>CẮT SỚM KHI XẤU:</b> Nếu có nến M15/H1 đóng cửa gãy đáy <b>${h4_low:,.2f}</b> -> Cắt lỗ sớm bằng tay!\n"
                f"💎 <b>DCA NHỒI KHI ĐẸP:</b> Khi Lệnh 1 có lãi > {sl_dist*0.7:.1f} giá và vượt đỉnh <b>${entry_stop:,.2f}</b>, dời SL về Entry và nhồi Lệnh 2!"
            )

    plan = {
        'signal': signal,
        'current_price': current_gold,
        'data_source': data_source,
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
        action_s = "LỆNH 2: Bán Stop Phá Đáy Tiếp Diễn Động Lực" if plan['signal'] == 'SHORT' else "LỆNH 2: Mua Stop Phá Đỉnh Tiếp Diễn Động Lực"
        
        text = f"""🥇 <b>[CHIẾN LƯỢC VÀNG SMC: QUÉT RÂU THANH KHOẢN & CHoCH]</b> 🥇
━━━━━━━━━━━━━━━━━━
📊 Nguồn biểu đồ: <b>{plan['data_source']}</b>
💰 Giá Vàng hiện tại: <b>${plan['current_price']:,.2f}</b>
🎯 <b>Vùng POC M15 (Thanh khoản hội tụ):</b> <code>${plan['poc_m15']:,.2f}</code>
⚡ <b>Cấu trúc SMC:</b> <b>{plan['setup_desc']}</b>
━━━━━━━━━━━━━━━━━━
🚀 <b>CHIẾN LƯỢC: {s_emoji}</b>
👉 <b>{action_l}:</b>
   <code>${plan['entry_limit']:,.2f}</code>
👉 <b>{action_s}:</b>
   <code>${plan['entry_stop']:,.2f}</code>

🛡️ <b>Cắt lỗ (SL Trên Râu Quét ~{plan['sl_dist']:.1f} Giá):</b>
   <code>${plan['sl']:,.2f}</code>
🎯 <b>Chốt lời 1 (TP1 - Ăn {plan['sl_dist']*2:.1f} Giá | R:R 1:2):</b> <code>${plan['tp1']:,.2f}</code>
🎯 <b>Chốt lời 2 (TP2 - Ăn {plan['sl_dist']*3.5:.1f} Giá | R:R 1:3.5):</b> <code>${plan['tp2']:,.2f}</code>

🧠 <b>KẾ HOẠCH XỬ LÝ LỆNH CHỦ ĐỘNG:</b>
{plan['advice']}

🛡️ <b>QUẢN LÝ VỐN VÀNG (${CONFIG['ACCOUNT_BALANCE']:,.0f}):</b>
• Rủi ro tối đa 2%: <b>$20.0</b> | Khối lượng: <b>$2,500.0</b> | Đòn bẩy: <b>5x</b>
<i>💡 Setup SMC chuyên trị giật râu: Đón lệnh khi Big Boys đã quét sạch thanh khoản và xác nhận CHoCH. SL đặt bám râu quét cực kỳ an toàn và tối ưu R:R!</i>"""
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
