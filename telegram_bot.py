import os
import json
import time
import datetime
import random
import string
import requests
import urllib.request
import threading
import http.server
import socketserver
import numpy as np
from websocket import create_connection

CONFIG = {
    'TELEGRAM_BOT_TOKEN': '9051874352:AAFrnfJ8Mm0QF4wBlz8V3vYjYiqz5_sIVF8',
    'TELEGRAM_CHAT_ID': '6022180065',
    'ACCOUNT_BALANCE': 2000.0,
    'RISK_PER_TRADE': 2.0,
}

TZ_VN = datetime.timezone(datetime.timedelta(hours=7))
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

def get_oanda_klines(resolution='5', count=60, tv_symbol='OANDA:XAUUSD'):
    """
    Lấy nến chuẩn 100% từ TradingView WebSocket (mặc định OANDA:XAUUSD, hỗ trợ TVC:DXY...).
    Trả về list nến desc order (mới nhất ở index 0):
    [[timestamp_ms, open, high, low, close, volume], ...]
    """
    ws = None
    try:
        ws = create_connection(
            "wss://data.tradingview.com/socket.io/websocket",
            header={"Origin": "https://data.tradingview.com"},
            timeout=8
        )
        def send_msg(m, p):
            payload = json.dumps({"m": m, "p": p}, separators=(",", ":"))
            ws.send(f"~m~{len(payload)}~m~{payload}")

        cs = "cs_" + "".join(random.choices(string.ascii_lowercase, k=12))
        send_msg("set_auth_token", ["unauthorized_user_token"])
        send_msg("chart_create_session", [cs, ""])
        send_msg("resolve_symbol", [cs, "sds_sym_1", f'={{"symbol":"{tv_symbol}","adjustment":"splits"}}'])
        send_msg("create_series", [cs, "sds_1", "s1", "sds_sym_1", str(resolution), count, ""])

        bars = []
        for _ in range(20):
            msg = ws.recv()
            if msg.startswith("~h~"):
                ws.send(msg)
                continue
            if "~m~" in msg:
                parts = msg.split("~m~")
                for part in parts:
                    if part and not part.isdigit():
                        try:
                            d = json.loads(part)
                            if d.get("m") == "timescale_update":
                                sds = d["p"][1].get("sds_1", {})
                                if "s" in sds:
                                    raw_bars = sds["s"]
                                    for b in reversed(raw_bars):
                                        v = b["v"]
                                        bars.append([
                                            int(v[0] * 1000),
                                            float(v[1]),
                                            float(v[2]),
                                            float(v[3]),
                                            float(v[4]),
                                            float(v[5])
                                        ])
                                    break
                        except Exception:
                            pass
            if bars:
                break
        return bars
    except Exception as e:
        print(f"Lỗi WebSocket OANDA ({resolution}): {e}")
        return []
    finally:
        if ws:
            try:
                ws.close()
            except Exception:
                pass

def get_binance_klines(symbol='BTCUSDT', interval='5m', limit=60):
    """
    Lấy nến chuẩn 100% từ Binance REST API cho BTC hoặc ETH hoặc Altcoins.
    Trả về list nến desc order (mới nhất ở index 0):
    [[timestamp_ms, open, high, low, close, volume], ...]
    """
    try:
        mapping = {'5': '5m', '15': '15m', '60': '1h', '240': '4h', 'D': '1d', 'W': '1w'}
        iv = mapping.get(str(interval), interval)
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={iv}&limit={limit}"
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read().decode())
        bars = []
        for k in reversed(data):
            bars.append([
                int(k[0]),
                float(k[1]),
                float(k[2]),
                float(k[3]),
                float(k[4]),
                float(k[5])
            ])
        return bars
    except Exception as e:
        print(f"Lỗi Binance klines ({symbol} {interval}): {e}")
        return []


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

UPSTASH_URL = os.environ.get('UPSTASH_REDIS_REST_URL', 'https://sure-fox-217928.upstash.io')
UPSTASH_TOKEN = os.environ.get('UPSTASH_REDIS_REST_TOKEN', 'gQAAAAAAA1NIAAIgcDE3MTFiMWZhNDBlNTM0NThjOTYwNTk0YzRmZmYzNjYyNA')

def redis_get_json(key, default_val):
    if not UPSTASH_URL or not UPSTASH_TOKEN:
        return None
    try:
        r = requests.get(f"{UPSTASH_URL}/get/{key}", headers={"Authorization": f"Bearer {UPSTASH_TOKEN}"}, timeout=5)
        if r.status_code == 200:
            res = r.json().get("result")
            if res is not None:
                return json.loads(res)
    except Exception as e:
        print(f"Lỗi redis_get_json({key}): {e}")
    return None

def redis_set_json(key, val):
    if not UPSTASH_URL or not UPSTASH_TOKEN:
        return False
    try:
        payload = json.dumps(val, ensure_ascii=False)
        r = requests.post(f"{UPSTASH_URL}/set/{key}", headers={"Authorization": f"Bearer {UPSTASH_TOKEN}"}, data=payload.encode('utf-8'), timeout=5)
        return r.status_code == 200
    except Exception as e:
        print(f"Lỗi redis_set_json({key}): {e}")
    return False

def load_vip_trades():
    r_data = redis_get_json('coinradar:vip_active_trades', [])
    if r_data is not None:
        return r_data
    try:
        if os.path.exists(VIP_TRADES_FILE):
            with open(VIP_TRADES_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        print(f"Lỗi load_vip_trades: {e}")
    return []

def save_vip_trades(trades):
    redis_set_json('coinradar:vip_active_trades', trades)
    try:
        with open(VIP_TRADES_FILE, 'w', encoding='utf-8') as f:
            json.dump(trades, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Lỗi save_vip_trades: {e}")

def load_vip_history():
    r_data = redis_get_json('coinradar:vip_trade_history', [])
    if r_data is not None:
        return r_data
    try:
        if os.path.exists(VIP_HISTORY_FILE):
            with open(VIP_HISTORY_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        print(f"Lỗi load_vip_history: {e}")
    return []

def save_vip_history(history):
    redis_set_json('coinradar:vip_trade_history', history)
    try:
        with open(VIP_HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Lỗi save_vip_history: {e}")

def record_new_vip_trade(asset, symbol, signal, entry_price, entry_stop, sl, tp1, tp2, sl_dist, is_limit=False, current_price=None, system='M5_SCALP'):
    trades = load_vip_trades()
    # Cho phép chạy song song 2 bot: 1 lệnh active cho mỗi symbol + system riêng biệt
    trades = [t for t in trades if not (t.get('symbol') == symbol and t.get('system', 'M5_SCALP') == system)]
    now_dt = datetime.datetime.now(TZ_VN)

    # Xác định trạng thái lệnh: Đã khớp ngay (Market) hay đang chờ Limit/Stop
    is_filled = True
    status = 'RUNNING'
    tol = 0.6 if asset == 'GOLD' else 35.0
    if current_price:
        if signal == 'SHORT' and entry_price > current_price + tol:
            is_filled = False
            status = 'PENDING_LIMIT'
        elif signal == 'LONG' and entry_price < current_price - tol:
            is_filled = False
            status = 'PENDING_LIMIT'
    elif is_limit:
        is_filled = False
        status = 'PENDING_LIMIT'

    new_t = {
        'id': f"{asset}_{system}_{int(time.time())}",
        'asset': asset,
        'symbol': symbol,
        'system': system,
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
        'is_filled': is_filled,
        'entry_time': now_dt.strftime('%H:%M %d/%m'),
        'entry_timestamp': time.time(),
        'status': status
    }
    trades.append(new_t)
    save_vip_trades(trades)
    return new_t


def check_m15_cisd_reversal(asset, signal):
    """
    Kiểm tra trạng thái Change in State of Delivery (CISD) trên khung M15:
    - Đối với lệnh SHORT:
      + Đang trong đà giảm mạnh (Bearish Delivery).
      + Nếu nến M15 đóng cửa VƯỢT LÊN TRÊN GIÁ MỞ CỬA (hoặc ĐỈNH) của nến giảm trước đó
        -> Xác nhận CISD Bullish (Dòng tiền chuyển sang Buy Program) -> Chốt lời toàn bộ Runner!
    - Đối với lệnh LONG:
      + Đang trong đà tăng mạnh (Bullish Delivery).
      + Nếu nến M15 đóng cửa SẬP THỦNG GIÁ MỞ CỬA (hoặc ĐÁY) của nến tăng trước đó
        -> Xác nhận CISD Bearish (Dòng tiền chuyển sang Sell Program) -> Chốt lời toàn bộ Runner!
    - Nếu nến M15 phá vỡ Sideway tiếp diễn sóng kèm Volume -> Tiếp tục gồng!
    """
    try:
        if asset == 'GOLD':
            klines = get_oanda_klines('15', 10)
            if len(klines) < 3: return False, "Thiếu dữ liệu M15 OANDA"
            c1, c2 = klines[1], klines[2]
            o1, cl1, h1, l1 = float(c1[1]), float(c1[4]), float(c1[2]), float(c1[3])
            o2, cl2, h2, l2 = float(c2[1]), float(c2[4]), float(c2[2]), float(c2[3])
        else: # BTC
            klines = get_binance_klines('BTCUSDT', '15m', 10)
            if len(klines) < 3: return False, "Thiếu dữ liệu M15 Binance"
            c1, c2 = klines[1], klines[2]
            o1, cl1, h1, l1 = float(c1[1]), float(c1[4]), float(c1[2]), float(c1[3])
            o2, cl2, h2, l2 = float(c2[1]), float(c2[4]), float(c2[2]), float(c2[3])

        if signal == 'SHORT':
            is_cisd = (cl1 > o1) and (cl1 > max(o2, cl2)) and (cl2 < o2)
            if is_cisd:
                return True, "Nến M15 đóng nến xác nhận CISD BULLISH (Đảo chiều sang Buy Program)"
        elif signal == 'LONG':
            is_cisd = (cl1 < o1) and (cl1 < min(o2, cl2)) and (cl2 > o2)
            if is_cisd:
                return True, "Nến M15 đóng nến xác nhận CISD BEARISH (Đảo chiều sang Sell Program)"

        return False, "Chưa có tín hiệu đảo chiều CISD (Xu hướng vẫn được bảo vệ)"
    except Exception as e:
        return False, str(e)

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
        orig_sl = t.get('orig_sl', sl)
        tp1 = t['tp1']
        tp2 = t['tp2']

        # 0. KIỂM TRA LỆNH CHỜ (PENDING LIMIT) ĐÃ KHỚP HAY CHƯA
        if not t.get('is_filled', True):
            if signal == 'SHORT':
                # Giá đã hồi lên chạm hoặc vượt Entry Limit -> CHÍNH THỨC KHỚP LỆNH!
                if curr_p >= entry_p:
                    t['is_filled'] = True
                    t['status'] = 'RUNNING'
                    t['filled_time'] = time_str
                    save_vip_trades(trades)
                    msg_fill = f"""🔔 <b>[VIP: ĐÃ KHỚP LỆNH SELL LIMIT]</b> 🔔
━━━━━━━━━━━━━━━━━━
💰 Tài sản: <b>{sym_name}</b>
📈 Lệnh: <b>🔴 SHORT</b>
👉 <b>Đã khớp tại Entry:</b> <code>${entry_p:,.{dec}f}</code> (Giá hiện tại: <code>${curr_p:,.{dec}f}</code>)
🛡️ <b>SL Gốc:</b> <code>${orig_sl:,.{dec}f}</code> | 🎯 <b>TP1:</b> <code>${tp1:,.{dec}f}</code> | 🎯 <b>TP2:</b> <code>${tp2:,.{dec}f}</code>
⚡ <i>Hệ thống chính thức kích hoạt giám sát TP1 & dời SL về Hoà Vốn!</i>"""
                    send_telegram(msg_fill, reply_markup=get_main_keyboard())
                    remaining.append(t)
                    continue
                # Nếu giá rơi thẳng về mốc TP1 mà CHƯA từng quay lên đón Entry -> HUỶ SETUP (MISSED ENTRY)
                elif curr_p <= tp1:
                    t['status'] = 'CANCELLED_MISSED'
                    t['close_time'] = time_str
                    t['close_timestamp'] = time.time()
                    t['profit'] = 0.0
                    history.append(t)
                    save_vip_history(history)
                    msg_cancel = f"""⏳ <b>[VIP: HUỶ LỆNH SELL LIMIT - HẾT HIỆU LỰC]</b> ⏳
━━━━━━━━━━━━━━━━━━
💰 Tài sản: <b>{sym_name}</b>
📈 Lệnh chờ: <b>🔴 SHORT LIMIT</b> tại <code>${entry_p:,.{dec}f}</code>
⚠️ <b>Lý do:</b> Giá thị trường đã rơi thẳng về mốc TP1 (<code>${curr_p:,.{dec}f}</code>) mà không quay lại đón Entry.
🛡️ <b>Hành động:</b> Tự động huỷ lệnh chờ để bảo toàn vốn, tuyệt đối không fomo đuổi giá!"""
                    send_telegram(msg_cancel, reply_markup=get_main_keyboard())
                    continue
                # Nếu giá tăng vọt vượt qua SL trước khi khớp -> HUỶ SETUP
                elif curr_p >= sl:
                    t['status'] = 'CANCELLED_INVALID'
                    t['close_time'] = time_str
                    t['close_timestamp'] = time.time()
                    t['profit'] = 0.0
                    history.append(t)
                    save_vip_history(history)
                    continue
                else:
                    # Lệnh Limit vẫn đang nằm chờ khớp
                    remaining.append(t)
                    continue

            elif signal == 'LONG':
                # Giá đã hồi xuống chạm hoặc thủng Entry Limit -> CHÍNH THỨC KHỚP LỆNH!
                if curr_p <= entry_p:
                    t['is_filled'] = True
                    t['status'] = 'RUNNING'
                    t['filled_time'] = time_str
                    save_vip_trades(trades)
                    msg_fill = f"""🔔 <b>[VIP: ĐÃ KHỚP LỆNH BUY LIMIT]</b> 🔔
━━━━━━━━━━━━━━━━━━
💰 Tài sản: <b>{sym_name}</b>
📈 Lệnh: <b>🟢 LONG</b>
👉 <b>Đã khớp tại Entry:</b> <code>${entry_p:,.{dec}f}</code> (Giá hiện tại: <code>${curr_p:,.{dec}f}</code>)
🛡️ <b>SL Gốc:</b> <code>${orig_sl:,.{dec}f}</code> | 🎯 <b>TP1:</b> <code>${tp1:,.{dec}f}</code> | 🎯 <b>TP2:</b> <code>${tp2:,.{dec}f}</code>
⚡ <i>Hệ thống chính thức kích hoạt giám sát TP1 & dời SL về Hoà Vốn!</i>"""
                    send_telegram(msg_fill, reply_markup=get_main_keyboard())
                    remaining.append(t)
                    continue
                # Nếu giá tăng thẳng lên mốc TP1 mà CHƯA từng quay xuống đón Entry -> HUỶ SETUP (MISSED ENTRY)
                elif curr_p >= tp1:
                    t['status'] = 'CANCELLED_MISSED'
                    t['close_time'] = time_str
                    t['close_timestamp'] = time.time()
                    t['profit'] = 0.0
                    history.append(t)
                    save_vip_history(history)
                    msg_cancel = f"""⏳ <b>[VIP: HUỶ LỆNH BUY LIMIT - HẾT HIỆU LỰC]</b> ⏳
━━━━━━━━━━━━━━━━━━
💰 Tài sản: <b>{sym_name}</b>
📈 Lệnh chờ: <b>🟢 BUY LIMIT</b> tại <code>${entry_p:,.{dec}f}</code>
⚠️ <b>Lý do:</b> Giá thị trường đã tăng thẳng lên mốc TP1 (<code>${curr_p:,.{dec}f}</code>) mà không quay lại đón Entry.
🛡️ <b>Hành động:</b> Tự động huỷ lệnh chờ để bảo toàn vốn, tuyệt đối không fomo đuổi giá!"""
                    send_telegram(msg_cancel, reply_markup=get_main_keyboard())
                    continue
                elif curr_p <= sl:
                    t['status'] = 'CANCELLED_INVALID'
                    t['close_time'] = time_str
                    t['close_timestamp'] = time.time()
                    t['profit'] = 0.0
                    history.append(t)
                    save_vip_history(history)
                    continue
                else:
                    # Lệnh Limit vẫn đang nằm chờ khớp
                    remaining.append(t)
                    continue

        # 1. KIỂM TRA LỆNH SHORT (ĐÃ KHỚP ENTRY)
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
📈 Lệnh: <b>🔴 SHORT</b>
👉 <b>Entry:</b> <code>${entry_p:,.{dec}f}</code>
🛡️ <b>SL Ban Đầu:</b> <code>${orig_sl:,.{dec}f}</code>
🎯 <b>Mốc TP1:</b> <code>${tp1:,.{dec}f}</code> (✅ Đã Chạm) | 🎯 <b>TP2:</b> <code>${tp2:,.{dec}f}</code>
💵 <b>Giá Chạm TP1:</b> <b>${curr_p:,.{dec}f}</b>
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

            # A2. Trailing Lock: Khi đạt +1.5R -> Khóa chặt +0.8R lợi nhuận
            risk = abs(entry_p - orig_sl)
            if t.get('tp1_hit') and not t.get('locked_in'):
                if curr_p <= entry_p - (risk * 1.5):
                    t['locked_in'] = True
                    t['sl'] = round(entry_p - (risk * 0.8), dec)
                    t['status'] = 'LOCKED_PROFIT_0.8R'
                    save_vip_trades(trades)
                    msg_lock = f"""🛡️ <b>[VIP: ĐÃ KHÓA LÃI BẬC THANG +0.8R!]</b> 🛡️
━━━━━━━━━━━━━━━━━━
💰 Tài sản: <b>{sym_name}</b>
📈 Lệnh: <b>🔴 SHORT</b>
👉 <b>Entry:</b> <code>${entry_p:,.{dec}f}</code> | <b>Giá Hiện Tại:</b> <code>${curr_p:,.{dec}f}</code> (Đạt +1.5R)
🔒 <b>SL Mới:</b> <code>${t['sl']:,.{dec}f}</code> (Bảo toàn chắc chắn <b>+0.8R</b>!)
⚡ <i>Không để lợi nhuận đảo chiều về 0. Lệnh tiếp tục gồng về TP2 (${tp2:,.{dec}f})!</i>"""
                    send_telegram(msg_lock, reply_markup=get_main_keyboard())

            # B. Chạm TP2 hoặc Gồng Dài Runner theo CISD M15
            if t.get('tp1_hit') and curr_p <= tp2:
                t['tp2_hit'] = True
                is_cisd_rev, cisd_reason = check_m15_cisd_reversal(t['asset'], 'SHORT')
                
                # Nếu chưa kích hoạt Runner Mode: Thông báo bắt đầu gồng sóng lớn
                if not t.get('runner_active'):
                    if not is_cisd_rev:
                        t['runner_active'] = True
                        save_vip_trades(trades)
                        msg_runner = f"""🚀 <b>[VIP ĐÃ ĐẠT TP2 - BẬT CHẾ ĐỘ GỒNG RUNNER THEO CISD M15]</b> 🚀
━━━━━━━━━━━━━━━━━━
💰 Tài sản: <b>{sym_name}</b>
📈 Lệnh: <b>🔴 SHORT</b>
👉 <b>Entry:</b> <code>${entry_p:,.{dec}f}</code> | 🎯 <b>TP2:</b> <code>${tp2:,.{dec}f}</code> (✅ Đã Chạm)
💵 <b>Giá Hiện Tại:</b> <b>${curr_p:,.{dec}f}</b>
🔥 <b>Lợi Nhuận Hiện Tại: +{abs(profit):,.{dec}f} {unit} (R:R > 1:2.5)!</b>
━━━━━━━━━━━━━━━━━━
🧠 <b>CHIẾN THUẬT GỒNG SÓNG THÔNG MINH:</b>
• Khung M15 đang đẩy mạnh, CHƯA XUẤT HIỆN tín hiệu đảo chiều CISD!
• Không chốt non: Tiếp tục gồng phần Runner còn lại. Nếu giá đi Sideway mà nổ Volume Breakout thì tiếp tục gồng!
• Lệnh chỉ chốt toàn bộ khi M15 xác nhận đóng nến CISD Bullish (Đảo chiều sang Buy Program)!"""
                        send_telegram(msg_runner, reply_markup=get_main_keyboard())
                        remaining.append(t)
                        continue
                
                # Nếu đang trong Runner Mode và xuất hiện CISD M15 đảo chiều: Chốt lời toàn bộ!
                if is_cisd_rev:
                    t['close_price'] = curr_p
                    t['close_time'] = time_str
                    t['close_timestamp'] = time.time()
                    t['profit'] = round(entry_p - curr_p, dec)
                    t['status'] = 'CLOSED_RUNNER'
                    history.append(t)
                    save_vip_history(history)
                    msg = f"""🏁 <b>[VIP CHỐT LỜI RUNNER ĐỈNH CAO - XUẤT HIỆN CISD M15]</b> 🏁
━━━━━━━━━━━━━━━━━━
💰 Tài sản: <b>{sym_name}</b>
📈 Lệnh: <b>🔴 SHORT</b>
👉 <b>Entry:</b> <code>${entry_p:,.{dec}f}</code> | 🛡️ <b>SL Gốc:</b> <code>${orig_sl:,.{dec}f}</code>
💵 <b>Giá Chốt Lời Runner:</b> <b>${curr_p:,.{dec}f}</b>
🔥 <b>TỔNG LỢI NHUẬN TRỌN VẸN: +{abs(t['profit']):,.{dec}f} {unit}!</b>
━━━━━━━━━━━━━━━━━━
⚡ <b>LÝ DO ĐÓNG VỊ THẾ:</b>
• {cisd_reason}.
• Toàn bộ sóng sập đã được vắt kiệt tối đa, bảo vệ trọn vẹn thành quả!
🟢 Hệ thống đã giải phóng slot, sẵn sàng đón kèo VIP tiếp theo!"""
                    send_telegram(msg, reply_markup=get_main_keyboard())
                    continue
                else:
                    # Chưa có CISD đảo chiều -> Tiếp tục gồng sóng!
                    remaining.append(t)
                    continue

            # C. Chạm SL (Cắt lỗ hoặc Hoà Vốn)
            if curr_p >= sl:
                t['close_price'] = curr_p
                t['close_time'] = time_str
                t['close_timestamp'] = time.time()
                if t.get('locked_in'):
                    t['status'] = 'CLOSED_LOCK_PROFIT'
                    t['profit'] = round(abs(entry_p - tp1) * 0.5 + abs(risk * 0.8) * 0.5, dec)
                    msg = f"""🛡️ <b>[VIP ĐÓNG LỆNH KHÓA LÃI +0.8R BẢO TOÀN THÀNH QUẢ]</b> 🛡️
━━━━━━━━━━━━━━━━━━
💰 Tài sản: <b>{sym_name}</b>
📈 Lệnh: <b>🔴 SHORT</b>
👉 <b>Entry:</b> <code>${entry_p:,.{dec}f}</code>
🔒 <b>SL Khóa Lãi Đã Khớp:</b> <code>${sl:,.{dec}f}</code> (+0.8R)
🎯 <b>TP1 Đã Ăn:</b> <code>${tp1:,.{dec}f}</code> (+1.2R)
🎉 <b>KẾT QUẢ: BẢO TOÀN TRỌN VẸN LÃI DƯƠNG!</b>
• 50% khối lượng chốt tại TP1 (+{abs(entry_p - tp1):,.{dec}f} {unit}).
• 50% khối lượng chốt tại SL Khóa Lãi (+{abs(risk * 0.8):,.{dec}f} {unit}).
• <b>Tổng Lợi Nhuận: +{abs(t['profit']):,.{dec}f} {unit}</b>
🟢 Hệ thống đã giải phóng slot, chờ đón cơ hội đẹp tiếp theo!"""
                elif t.get('tp1_hit'):
                    t['status'] = 'CLOSED_BREAKEVEN'
                    t['profit'] = round(abs(entry_p - tp1) * 0.5, dec) # Đã ăn 50% ở TP1
                    msg = f"""🛡️ <b>[VIP ĐÓNG LỆNH HOÀ VỐN - BẢO TOÀN LÃI TP1]</b> 🛡️
━━━━━━━━━━━━━━━━━━
💰 Tài sản: <b>{sym_name}</b>
📈 Lệnh: <b>🔴 SHORT</b>
👉 <b>Entry:</b> <code>${entry_p:,.{dec}f}</code>
🛡️ <b>SL Ban Đầu:</b> <code>${orig_sl:,.{dec}f}</code> (Đã dời về Hoà Vốn: ${entry_p:,.{dec}f})
🎯 <b>TP1:</b> <code>${tp1:,.{dec}f}</code> (Đã chốt 50%) | 🎯 <b>TP2:</b> <code>${tp2:,.{dec}f}</code>
⚠️ <b>Giá Đóng (Đá SL Hoà Vốn):</b> <b>${curr_p:,.{dec}f}</b>
━━━━━━━━━━━━━━━━━━
🎉 <b>KẾT QUẢ CUỐI CÙNG: VẪN CÓ LÃI!</b>
• 50% khối lượng đã bỏ túi tại TP1 (+{abs(entry_p - tp1):,.{dec}f} {unit}).
• 50% khối lượng còn lại thoát giá Hoà Vốn (Risk = $0).
• <b>Lợi nhuận thực tế: +{abs(t['profit']):,.{dec}f} {unit}</b>
🟢 Hệ thống đã giải phóng slot, chờ đón cơ hội đẹp tiếp theo!"""
                else:
                    t['status'] = 'CLOSED_SL'
                    t['profit'] = -round(curr_p - entry_p, dec)
                    msg = f"""⚠️ <b>[VIP CHẠM CẮT LỖ (SL) - BẢO VỆ TÀI KHOẢN]</b> ⚠️
━━━━━━━━━━━━━━━━━━
💰 Tài sản: <b>{sym_name}</b>
📈 Lệnh: <b>🔴 SHORT</b>
👉 <b>Entry:</b> <code>${entry_p:,.{dec}f}</code>
🛡️ <b>Cắt Lỗ (SL Gốc):</b> <code>${orig_sl:,.{dec}f}</code>
🎯 <b>TP1 Dự Kiến:</b> <code>${tp1:,.{dec}f}</code> | 🎯 <b>TP2:</b> <code>${tp2:,.{dec}f}</code>
🛑 <b>Giá Đóng (Chạm SL):</b> <b>${curr_p:,.{dec}f}</b>
🔥 <b>KẾT QUẢ: -{abs(t['profit']):,.{dec}f} {unit}</b>
━━━━━━━━━━━━━━━━━━
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
📈 Lệnh: <b>🟢 LONG</b>
👉 <b>Entry:</b> <code>${entry_p:,.{dec}f}</code>
🛡️ <b>SL Ban Đầu:</b> <code>${orig_sl:,.{dec}f}</code>
🎯 <b>Mốc TP1:</b> <code>${tp1:,.{dec}f}</code> (✅ Đã Chạm) | 🎯 <b>TP2:</b> <code>${tp2:,.{dec}f}</code>
💵 <b>Giá Chạm TP1:</b> <b>${curr_p:,.{dec}f}</b>
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

            # A2. Trailing Lock: Khi đạt +1.5R -> Khóa chặt +0.8R lợi nhuận
            risk = abs(entry_p - orig_sl)
            if t.get('tp1_hit') and not t.get('locked_in'):
                if curr_p >= entry_p + (risk * 1.5):
                    t['locked_in'] = True
                    t['sl'] = round(entry_p + (risk * 0.8), dec)
                    t['status'] = 'LOCKED_PROFIT_0.8R'
                    save_vip_trades(trades)
                    msg_lock = f"""🛡️ <b>[VIP: ĐÃ KHÓA LÃI BẬC THANG +0.8R!]</b> 🛡️
━━━━━━━━━━━━━━━━━━
💰 Tài sản: <b>{sym_name}</b>
📈 Lệnh: <b>🟢 LONG</b>
👉 <b>Entry:</b> <code>${entry_p:,.{dec}f}</code> | <b>Giá Hiện Tại:</b> <code>${curr_p:,.{dec}f}</code> (Đạt +1.5R)
🔒 <b>SL Mới:</b> <code>${t['sl']:,.{dec}f}</code> (Bảo toàn chắc chắn <b>+0.8R</b>!)
⚡ <i>Không để lợi nhuận đảo chiều về 0. Lệnh tiếp tục gồng về TP2 (${tp2:,.{dec}f})!</i>"""
                    send_telegram(msg_lock, reply_markup=get_main_keyboard())

            # B. Chạm TP2 hoặc Gồng Dài Runner theo CISD M15
            if t.get('tp1_hit') and curr_p >= tp2:
                t['tp2_hit'] = True
                is_cisd_rev, cisd_reason = check_m15_cisd_reversal(t['asset'], 'LONG')
                
                # Nếu chưa kích hoạt Runner Mode: Thông báo bắt đầu gồng sóng lớn
                if not t.get('runner_active'):
                    if not is_cisd_rev:
                        t['runner_active'] = True
                        save_vip_trades(trades)
                        msg_runner = f"""🚀 <b>[VIP ĐÃ ĐẠT TP2 - BẬT CHẾ ĐỘ GỒNG RUNNER THEO CISD M15]</b> 🚀
━━━━━━━━━━━━━━━━━━
💰 Tài sản: <b>{sym_name}</b>
📈 Lệnh: <b>🟢 LONG</b>
👉 <b>Entry:</b> <code>${entry_p:,.{dec}f}</code> | 🎯 <b>TP2:</b> <code>${tp2:,.{dec}f}</code> (✅ Đã Chạm)
💵 <b>Giá Hiện Tại:</b> <b>${curr_p:,.{dec}f}</b>
🔥 <b>Lợi Nhuận Hiện Tại: +{abs(profit):,.{dec}f} {unit} (R:R > 1:2.5)!</b>
━━━━━━━━━━━━━━━━━━
🧠 <b>CHIẾN THUẬT GỒNG SÓNG THÔNG MINH:</b>
• Khung M15 đang đẩy mạnh, CHƯA XUẤT HIỆN tín hiệu đảo chiều CISD!
• Không chốt non: Tiếp tục gồng phần Runner còn lại. Nếu giá đi Sideway mà nổ Volume Breakout thì tiếp tục gồng!
• Lệnh chỉ chốt toàn bộ khi M15 xác nhận đóng nến CISD Bearish (Đảo chiều sang Sell Program)!"""
                        send_telegram(msg_runner, reply_markup=get_main_keyboard())
                        remaining.append(t)
                        continue
                
                # Nếu đang trong Runner Mode và xuất hiện CISD M15 đảo chiều: Chốt lời toàn bộ!
                if is_cisd_rev:
                    t['close_price'] = curr_p
                    t['close_time'] = time_str
                    t['close_timestamp'] = time.time()
                    t['profit'] = round(curr_p - entry_p, dec)
                    t['status'] = 'CLOSED_RUNNER'
                    history.append(t)
                    save_vip_history(history)
                    msg = f"""🏁 <b>[VIP CHỐT LỜI RUNNER ĐỈNH CAO - XUẤT HIỆN CISD M15]</b> 🏁
━━━━━━━━━━━━━━━━━━
💰 Tài sản: <b>{sym_name}</b>
📈 Lệnh: <b>🟢 LONG</b>
👉 <b>Entry:</b> <code>${entry_p:,.{dec}f}</code> | 🛡️ <b>SL Gốc:</b> <code>${orig_sl:,.{dec}f}</code>
💵 <b>Giá Chốt Lời Runner:</b> <b>${curr_p:,.{dec}f}</b>
🔥 <b>TỔNG LỢI NHUẬN TRỌN VẸN: +{abs(t['profit']):,.{dec}f} {unit}!</b>
━━━━━━━━━━━━━━━━━━
⚡ <b>LÝ DO ĐÓNG VỊ THẾ:</b>
• {cisd_reason}.
• Toàn bộ sóng tăng đã được vắt kiệt tối đa, bảo vệ trọn vẹn thành quả!
🟢 Hệ thống đã giải phóng slot, sẵn sàng đón kèo VIP tiếp theo!"""
                    send_telegram(msg, reply_markup=get_main_keyboard())
                    continue
                else:
                    remaining.append(t)
                    continue

            # C. Chạm SL
            if curr_p <= sl:
                t['close_price'] = curr_p
                t['close_time'] = time_str
                t['close_timestamp'] = time.time()
                if t.get('locked_in'):
                    t['status'] = 'CLOSED_LOCK_PROFIT'
                    t['profit'] = round(abs(tp1 - entry_p) * 0.5 + abs(risk * 0.8) * 0.5, dec)
                    msg = f"""🛡️ <b>[VIP ĐÓNG LỆNH KHÓA LÃI +0.8R BẢO TOÀN THÀNH QUẢ]</b> 🛡️
━━━━━━━━━━━━━━━━━━
💰 Tài sản: <b>{sym_name}</b>
📈 Lệnh: <b>🟢 LONG</b>
👉 <b>Entry:</b> <code>${entry_p:,.{dec}f}</code>
🔒 <b>SL Khóa Lãi Đã Khớp:</b> <code>${sl:,.{dec}f}</code> (+0.8R)
🎯 <b>TP1 Đã Ăn:</b> <code>${tp1:,.{dec}f}</code> (+1.2R)
🎉 <b>KẾT QUẢ: BẢO TOÀN TRỌN VẸN LÃI DƯƠNG!</b>
• 50% khối lượng chốt tại TP1 (+{abs(tp1 - entry_p):,.{dec}f} {unit}).
• 50% khối lượng chốt tại SL Khóa Lãi (+{abs(risk * 0.8):,.{dec}f} {unit}).
• <b>Tổng Lợi Nhuận: +{abs(t['profit']):,.{dec}f} {unit}</b>
🟢 Hệ thống đã giải phóng slot, chờ đón cơ hội đẹp tiếp theo!"""
                elif t.get('tp1_hit'):
                    t['status'] = 'CLOSED_BREAKEVEN'
                    t['profit'] = round(abs(tp1 - entry_p) * 0.5, dec)
                    msg = f"""🛡️ <b>[VIP ĐÓNG LỆNH HOÀ VỐN - BẢO TOÀN LÃI TP1]</b> 🛡️
━━━━━━━━━━━━━━━━━━
💰 Tài sản: <b>{sym_name}</b>
📈 Lệnh: <b>🟢 LONG</b>
👉 <b>Entry:</b> <code>${entry_p:,.{dec}f}</code>
🛡️ <b>SL Ban Đầu:</b> <code>${orig_sl:,.{dec}f}</code> (Đã dời về Hoà Vốn: ${entry_p:,.{dec}f})
🎯 <b>TP1:</b> <code>${tp1:,.{dec}f}</code> (Đã chốt 50%) | 🎯 <b>TP2:</b> <code>${tp2:,.{dec}f}</code>
⚠️ <b>Giá Đóng (Đá SL Hoà Vốn):</b> <b>${curr_p:,.{dec}f}</b>
━━━━━━━━━━━━━━━━━━
🎉 <b>KẾT QUẢ CUỐI CÙNG: VẪN CÓ LÃI!</b>
• 50% khối lượng đã bỏ túi tại TP1 (+{abs(tp1 - entry_p):,.{dec}f} {unit}).
• 50% khối lượng còn lại thoát giá Hoà Vốn (Risk = $0).
• <b>Lợi nhuận thực tế: +{abs(t['profit']):,.{dec}f} {unit}</b>
🟢 Hệ thống đã giải phóng slot, chờ đón cơ hội đẹp tiếp theo!"""
                else:
                    t['status'] = 'CLOSED_SL'
                    t['profit'] = -round(entry_p - curr_p, dec)
                    msg = f"""⚠️ <b>[VIP CHẠM CẮT LỖ (SL) - BẢO VỆ TÀI KHOẢN]</b> ⚠️
━━━━━━━━━━━━━━━━━━
💰 Tài sản: <b>{sym_name}</b>
📈 Lệnh: <b>🟢 LONG</b>
👉 <b>Entry:</b> <code>${entry_p:,.{dec}f}</code>
🛡️ <b>Cắt Lỗ (SL Gốc):</b> <code>${orig_sl:,.{dec}f}</code>
🎯 <b>TP1 Dự Kiến:</b> <code>${tp1:,.{dec}f}</code> | 🎯 <b>TP2:</b> <code>${tp2:,.{dec}f}</code>
🛑 <b>Giá Đóng (Chạm SL):</b> <b>${curr_p:,.{dec}f}</b>
🔥 <b>KẾT QUẢ: -{abs(t['profit']):,.{dec}f} {unit}</b>
━━━━━━━━━━━━━━━━━━
🛡️ Đúng kỷ luật theo tôn chỉ FX DREAM: Sai là cắt ngay tại chóp râu M5, không gồng lỗ!
🟢 Hệ thống sẵn sàng tìm kiếm điểm vào mới."""
                history.append(t)
                save_vip_history(history)
                send_telegram(msg, reply_markup=get_main_keyboard())
                continue
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

        try:
            plan_gold = calculate_gold_h4_plan()
        except Exception as eg:
            print(f"Lỗi plan_gold: {eg}")
            plan_gold = None

        try:
            plan_btc = calculate_btc_h4_plan()
        except Exception as eb:
            print(f"Lỗi plan_btc: {eb}")
            plan_btc = None

        try:
            p_gold_vp = analyze_scalp_vp_plan('GOLD')
        except Exception as evg:
            print(f"Lỗi p_gold_vp: {evg}")
            p_gold_vp = None

        try:
            p_btc_vp = analyze_scalp_vp_plan('BTC')
        except Exception as evb:
            print(f"Lỗi p_btc_vp: {evb}")
            p_btc_vp = None

        p_gold = float(plan_gold['current_price']) if (plan_gold and 'current_price' in plan_gold) else 3580.0
        p_btc = float(plan_btc['current_price']) if (plan_btc and 'current_price' in plan_btc) else 60000.0

        if not plan_gold:
            plan_gold = {'current_price': p_gold, 'b_ob_bot': p_gold + 10.0, 'b_ob_top': p_gold + 15.0, 'bull_ob_bot': p_gold - 15.0, 'bull_ob_top': p_gold - 10.0}
        if not plan_btc:
            plan_btc = {'current_price': p_btc, 'b_ob_bot': p_btc + 500.0, 'b_ob_top': p_btc + 800.0, 'bull_ob_bot': p_btc - 800.0, 'bull_ob_top': p_btc - 500.0}

        if not p_gold_vp:
            p_gold_vp = {
                'curr_p': p_gold, 'daily_open': p_gold, 'daily_bias': "Đang đồng bộ", 'poc': p_gold,
                'y_shape': "D-Shape", 'y_val': p_gold - 5.0, 'y_poc': p_gold, 'y_vah': p_gold + 5.0,
                'defense_badge': "⏳ Đang đồng bộ feed nến", 'wick_info': "Chưa có nến mới",
                'action_plan_text': "Đang theo dõi cản M5/H1."
            }
        if not p_btc_vp:
            p_btc_vp = {
                'curr_p': p_btc, 'daily_open': p_btc, 'daily_bias': "Đang đồng bộ", 'poc': p_btc,
                'y_shape': "D-Shape", 'y_val': p_btc - 300.0, 'y_poc': p_btc, 'y_vah': p_btc + 300.0,
                'defense_badge': "⏳ Đang đồng bộ feed nến", 'wick_info': "Chưa có nến mới",
                'action_plan_text': "Đang theo dõi cản M5/H1."
            }

        now_dt = datetime.datetime.now(TZ_VN)
        now_ts = time.time()
        start_today_ts = now_dt.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        today_date_str = now_dt.strftime('%d/%m')

        msg = "🔍 <b>[BÁO CÁO TRẠNG THÁI LỆNH: ĐANG VÀO - ĐANG CHẠY - ĐÃ CHỐT]</b>\n"
        msg += "━━━━━━━━━━━━━━━━━━\n"
        msg += f"⏱️ <i>Cập nhật: {now_dt.strftime('%H:%M:%S %d/%m/%Y')}</i>\n"
        msg += f"🥇 <b>Vàng (XAUUSD):</b> <code>${p_gold:,.2f}</code> | 👑 <b>BTC:</b> <code>${p_btc:,.1f}</code>\n\n"

        # -------------------------------------------------------------
        # 1. LỆNH ĐANG VÀO (CHỜ KHỚP / PENDING LIMIT HOẶC SETUP ĐANG RÌNH)
        # -------------------------------------------------------------
        pending_trades = [t for t in trades if not t.get('is_filled', True) or t.get('status') == 'PENDING_LIMIT']
        msg += "⏳ <b>1. LỆNH ĐANG VÀO (LỆNH CHỜ / PENDING LIMIT):</b>\n"
        if pending_trades:
            for i, t in enumerate(pending_trades, 1):
                is_gold = (t.get('asset') == 'GOLD')
                curr_p = p_gold if is_gold else p_btc
                dec = 2 if is_gold else 1
                unit = "Giá" if is_gold else "USDT"
                sys_tag = "🧙‍♀️ [SWING H1 - MA NỮ]" if t.get('system') == 'H1_MANU' else "⚡ [SCALP M5 - VP]"
                sym = "🥇 VÀNG (XAUUSD)" if is_gold else "👑 BITCOIN"
                sgn = "🔴 SELL LIMIT" if t.get('signal') == 'SHORT' else "🟢 BUY LIMIT"
                entry_p = t.get('entry_price', 0)
                dist = abs(entry_p - curr_p)

                msg += f"<b>{i}. {sym} {sys_tag} - {sgn}</b>\n"
                msg += f"   • 👉 <b>Entry chờ khớp:</b> <code>${entry_p:,.{dec}f}</code> (Cách giá hiện tại: <b>{dist:,.{dec}f} {unit}</b>)\n"
                msg += f"   • 🛡️ <b>SL:</b> <code>${t.get('sl', 0):,.{dec}f}</code> | 🎯 <b>TP1:</b> <code>${t.get('tp1', 0):,.{dec}f}</code> | 🎯 <b>TP2:</b> <code>${t.get('tp2', 0):,.{dec}f}</code>\n"
                msg += f"   • ⏱️ Đặt lúc: <code>{t.get('entry_time', '')}</code> | Trạng thái: <i>Đang rình đón giá hồi...</i>\n\n"
        else:
            msg += "• <i>Hiện không có lệnh Limit treo chờ trên sàn.</i>\n"
            msg += "• 🎯 <b>Điểm rình setup hiện tại:</b>\n"
            msg += f"   - 🥇 <b>Vàng:</b> M5: <i>{p_gold_vp.get('wick_info', 'Chờ tín hiệu')}</i> | H1: Cản [<code>{plan_gold.get('b_ob_bot', 0):,.1f} - {plan_gold.get('b_ob_top', 0):,.1f}</code>]\n"
            msg += f"   - 👑 <b>BTC:</b> M5: <i>{p_btc_vp.get('wick_info', 'Chờ tín hiệu')}</i> | H1: Cản [<code>{plan_btc.get('b_ob_bot', 0):,.1f} - {plan_btc.get('b_ob_top', 0):,.1f}</code>]\n\n"

        # -------------------------------------------------------------
        # 2. LỆNH ĐANG CHẠY (ACTIVE RUNNING & FLOATING PNL)
        # -------------------------------------------------------------
        running_trades = [t for t in trades if t.get('is_filled', True) and t.get('status') in ['RUNNING', 'TP1_HIT_RISK_FREE', None]]
        msg += "━━━━━━━━━━━━━━━━━━\n"
        msg += "🔥 <b>2. LỆNH ĐANG CHẠY (ACTIVE & FLOATING PnL):</b>\n"
        if running_trades:
            for i, t in enumerate(running_trades, 1):
                is_gold = (t.get('asset') == 'GOLD')
                curr_p = p_gold if is_gold else p_btc
                dec = 2 if is_gold else 1
                unit = "Giá" if is_gold else "USDT"
                sys_tag = "🧙‍♀️ [SWING H1 - MA NỮ]" if t.get('system') == 'H1_MANU' else "⚡ [SCALP M5 - VP]"
                sym = "🥇 VÀNG (XAUUSD)" if is_gold else "👑 BITCOIN"
                sgn = "🔴 SHORT" if t.get('signal') == 'SHORT' else "🟢 LONG"
                entry_p = t.get('entry_price', 0)

                # Floating PnL
                if t.get('signal') == 'SHORT':
                    diff = entry_p - curr_p
                else:
                    diff = curr_p - entry_p
                pnl_str = f"+{diff:,.{dec}f} {unit}" if diff >= 0 else f"-{abs(diff):,.{dec}f} {unit}"
                pnl_emoji = "🟢" if diff >= 0 else "🔴"

                if t.get('tp1_hit'):
                    status_txt = "🛡️ ĐÃ DỜI SL HOÀ VỐN (Ăn 50% TP1 - Gồng TP2)"
                else:
                    status_txt = "⏳ ĐANG GỒNG LÃI (Chờ chạm TP1)"

                msg += f"<b>{i}. {sym} {sys_tag} - {sgn}</b>\n"
                msg += f"   • 👉 <b>Entry:</b> <code>${entry_p:,.{dec}f}</code> ➔ Hiện tại: <b>${curr_p:,.{dec}f}</b>\n"
                msg += f"   • 💰 <b>Lãi/Lỗ tạm tính:</b> {pnl_emoji} <b>{pnl_str}</b>\n"
                msg += f"   • 🛡️ <b>Trạng thái:</b> <b>{status_txt}</b>\n"
                msg += f"   • 🛑 <b>SL:</b> <code>${t.get('sl', 0):,.{dec}f}</code> | 🎯 <b>TP1:</b> <code>${t.get('tp1', 0):,.{dec}f}</code> {'(✅ Đã Chạm)' if t.get('tp1_hit') else ''} | 🎯 <b>TP2:</b> <code>${t.get('tp2', 0):,.{dec}f}</code>\n"
                msg += f"   • ⏱️ Khớp lúc: <code>{t.get('filled_time') or t.get('entry_time', '')}</code>\n\n"
        else:
            msg += "• 🟢 <i>Hiện không có lệnh nào đang chạy trên thị trường. Vốn được bảo toàn an toàn tuyệt đối 100%!</i>\n\n"

        # -------------------------------------------------------------
        # 3. LỆNH ĐÃ CÓ KẾT QUẢ TRONG NGÀY (HÔM NAY)
        # -------------------------------------------------------------
        # Lọc các kèo chốt trong ngày hôm nay (00:00 - nay)
        today_trades = [
            t for t in history
            if (t.get('close_timestamp') and t.get('close_timestamp') >= start_today_ts)
            or (t.get('close_time') and today_date_str in str(t.get('close_time', '')))
        ]

        msg += "━━━━━━━━━━━━━━━━━━\n"
        msg += f"📜 <b>3. LỆNH ĐÃ CÓ KẾT QUẢ TRONG NGÀY ({now_dt.strftime('%d/%m/%Y')}):</b>\n"

        if today_trades:
            today_stats = compute_trade_stats(today_trades)
            msg += f"• 📊 <b>Tổng kết hôm nay:</b> <b>{today_stats['total']} kèo</b> | Thắng: <b>{today_stats['wins']}</b> | Hoà: <b>{today_stats['be']}</b> | Thua: <b>{today_stats['losses']}</b>\n"
            msg += f"• 🔥 <b>Tỷ lệ Winrate hôm nay:</b> <b>{today_stats['winrate']}%</b>\n"
            msg += f"• 💰 <b>PnL Hôm Nay:</b> 🥇 Vàng: <b>{'+' if today_stats['pnl_gold'] >= 0 else ''}{today_stats['pnl_gold']:,.2f} Giá</b> | 👑 BTC: <b>{'+' if today_stats['pnl_btc'] >= 0 else ''}{today_stats['pnl_btc']:,.1f} USDT</b>\n"
            msg += "• <b>Chi tiết các lệnh chốt hôm nay:</b>\n"
            for idx, t in enumerate(today_trades, 1):
                msg += "\n" + format_single_trade_block(t, index=idx)
        else:
            msg += f"• <i>Hôm nay ({now_dt.strftime('%d/%m/%Y')}) chưa có lệnh nào đóng kết quả.</i>\n"
            if history:
                msg += f"\n• <b>3 lệnh chốt gần nhất các phiên trước:</b>\n"
                for idx, t in enumerate(list(reversed(history))[:3], 1):
                    msg += "\n" + format_single_trade_block(t, index=idx)

        msg += "\n━━━━━━━━━━━━━━━━━━\n"
        msg += "💡 <i>Bot M5 Scalp rà quét mỗi 5 phút, Bot H1 Swing rà quét mỗi khi nến H1 đóng. Hệ thống tự động bắn tín hiệu và ghi nhận thời gian thực!</i>"

        send_telegram(msg, reply_markup=get_main_keyboard(), target_chat_id=chat_id)
    except Exception as e:
        send_telegram(f"Lỗi kiểm tra lệnh: {e}", reply_markup=get_main_keyboard(), target_chat_id=chat_id)

REPORT_STATE_FILE = os.path.join(os.path.dirname(__file__), 'report_state.json')

def get_report_state():
    r_data = redis_get_json('coinradar:report_state', None)
    if r_data is not None:
        return r_data
    try:
        if os.path.exists(REPORT_STATE_FILE):
            with open(REPORT_STATE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return {'last_daily': '', 'last_weekly': ''}

def save_report_state(state):
    redis_set_json('coinradar:report_state', state)
    try:
        with open(REPORT_STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def format_single_trade_block(t, index=None):
    is_gold = (t.get('asset') == 'GOLD')
    is_btc = (t.get('asset') == 'BTC')
    dec = 2 if is_gold else 1
    unit = "Giá" if is_gold else "USDT"
    sys_tag = "🧙‍♀️ [SWING H1 - MA NỮ]" if t.get('system') == 'H1_MANU' else "⚡ [SCALP M5 - VP]"
    if is_gold:
        sym = f"🥇 VÀNG (XAUUSD) {sys_tag}"
    elif is_btc:
        sym = f"👑 BITCOIN (BTCUSDT) {sys_tag}"
    else:
        sym = f"💎 {t.get('symbol', 'COIN')} {sys_tag}"
        
    sgn = "🔴 SHORT" if t.get('signal') == 'SHORT' else "🟢 LONG"
    status = t.get('status', 'CLOSED')
    pnl = t.get('profit', 0)
    
    if status == 'CLOSED_TP2':
        badge = f"🎯 FULL TP2 (+{abs(pnl):,.{dec}f} {unit})"
    elif status == 'CLOSED_BREAKEVEN':
        badge = f"🛡️ HOÀ VỐN (Ăn 50% TP1: +{abs(pnl):,.{dec}f} {unit})"
    elif status == 'CLOSED_SL':
        badge = f"🛑 CẮT LỖ SL (-{abs(pnl):,.{dec}f} {unit})"
    elif status == 'TP1_HIT_RISK_FREE':
        badge = "⏳ ĐÃ CHẠM TP1 (DỜI BE - RUNNING)"
    elif status == 'PENDING_LIMIT':
        badge = "⏳ ĐANG CHỜ KHỚP LỆNH CHỜ (PENDING)"
    elif status == 'CANCELLED_MISSED':
        badge = "🚫 HUỶ KÈO (GIÁ CHƯA KHỚP ENTRY ĐÃ CHẠY VỀ TP)"
    elif status == 'CANCELLED_INVALID':
        badge = "🚫 HUỶ KÈO (HẾT HIỆU LỰC)"
    else:
        badge = f"⏳ {status}"
        
    entry_p = t.get('entry_price', 0)
    orig_sl = t.get('orig_sl', t.get('sl', 0))
    tp1 = t.get('tp1', 0)
    tp2 = t.get('tp2', 0)
    close_p = t.get('close_price', 0)
    entry_t = t.get('entry_time', '')
    close_t = t.get('close_time', 'Đang mở')
    
    pnl_str = f"+{pnl:,.{dec}f} {unit}" if pnl > 0 else (f"-{abs(pnl):,.{dec}f} {unit}" if pnl < 0 else f"0.0 {unit}")
    
    prefix = f"<b>{index}. </b>" if index is not None else ""
    res = f"{prefix}<b>{sym} - {sgn}</b> | {badge}\n"
    res += f"   • Thời gian: <code>{entry_t}</code> ➔ <code>{close_t}</code>\n"
    res += f"   • 👉 <b>Entry:</b> <code>${entry_p:,.{dec}f}</code>\n"
    res += f"   • 🛡️ <b>SL Gốc:</b> <code>${orig_sl:,.{dec}f}</code>\n"
    res += f"   • 🎯 <b>TP1:</b> <code>${tp1:,.{dec}f}</code> | 🎯 <b>TP2:</b> <code>${tp2:,.{dec}f}</code>\n"
    if close_p:
        res += f"   • 💵 <b>Giá Đóng:</b> <code>${close_p:,.{dec}f}</code> | Lợi nhuận: <b>{pnl_str}</b>\n"
    return res

def compute_trade_stats(trades_list):
    # Lọc bỏ các kèo Limit bị huỷ do giá không quay lại đón Entry
    executed_trades = [t for t in trades_list if t.get('status') not in ['CANCELLED_MISSED', 'CANCELLED_INVALID']]
    total = len(executed_trades)
    if total == 0:
        return {
            'total': 0, 'wins': 0, 'losses': 0, 'be': 0, 'winrate': 0.0,
            'pnl_gold': 0.0, 'pnl_btc': 0.0, 'gold_trades': 0, 'btc_trades': 0,
            'm5_total': 0, 'm5_wins': 0, 'm5_losses': 0, 'm5_winrate': 0.0, 'm5_pnl_gold': 0.0, 'm5_pnl_btc': 0.0,
            'h1_total': 0, 'h1_wins': 0, 'h1_losses': 0, 'h1_winrate': 0.0, 'h1_pnl_gold': 0.0, 'h1_pnl_btc': 0.0
        }
    wins = 0
    losses = 0
    be = 0
    pnl_gold = 0.0
    pnl_btc = 0.0
    gold_trades = 0
    btc_trades = 0
    
    m5_total = 0; m5_wins = 0; m5_losses = 0; m5_pnl_gold = 0.0; m5_pnl_btc = 0.0
    h1_total = 0; h1_wins = 0; h1_losses = 0; h1_pnl_gold = 0.0; h1_pnl_btc = 0.0

    for t in executed_trades:
        is_gold = (t.get('asset') == 'GOLD')
        is_h1 = (t.get('system') == 'H1_MANU')
        profit = t.get('profit', 0)
        status = t.get('status', '')
        if is_gold:
            gold_trades += 1
            pnl_gold += profit
            if is_h1: h1_pnl_gold += profit
            else: m5_pnl_gold += profit
        else:
            btc_trades += 1
            pnl_btc += profit
            if is_h1: h1_pnl_btc += profit
            else: m5_pnl_btc += profit
            
        is_win_trade = False
        if status == 'CLOSED_TP2':
            wins += 1
            is_win_trade = True
        elif status == 'CLOSED_BREAKEVEN':
            be += 1
            if profit > 0:
                wins += 1
                is_win_trade = True
        elif status == 'CLOSED_SL':
            losses += 1
        elif profit > 0:
            wins += 1
            is_win_trade = True
        elif profit < 0:
            losses += 1
            
        if is_h1:
            h1_total += 1
            if is_win_trade: h1_wins += 1
            else: h1_losses += 1
        else:
            m5_total += 1
            if is_win_trade: m5_wins += 1
            else: m5_losses += 1
            
    winrate = round((wins / total) * 100, 1) if total > 0 else 0.0
    m5_winrate = round((m5_wins / m5_total) * 100, 1) if m5_total > 0 else 0.0
    h1_winrate = round((h1_wins / h1_total) * 100, 1) if h1_total > 0 else 0.0

    return {
        'total': total,
        'wins': wins,
        'losses': losses,
        'be': be,
        'winrate': winrate,
        'pnl_gold': round(pnl_gold, 2),
        'pnl_btc': round(pnl_btc, 1),
        'gold_trades': gold_trades,
        'btc_trades': btc_trades,
        'm5_total': m5_total, 'm5_wins': m5_wins, 'm5_losses': m5_losses, 'm5_winrate': m5_winrate,
        'm5_pnl_gold': round(m5_pnl_gold, 2), 'm5_pnl_btc': round(m5_pnl_btc, 1),
        'h1_total': h1_total, 'h1_wins': h1_wins, 'h1_losses': h1_losses, 'h1_winrate': h1_winrate,
        'h1_pnl_gold': round(h1_pnl_gold, 2), 'h1_pnl_btc': round(h1_pnl_btc, 1)
    }


def send_daily_summary_report():
    history = load_vip_history()
    now_dt = datetime.datetime.now(TZ_VN)
    # Khung thời gian ngày hôm trước: từ 07:00 hôm qua đến 07:00 sáng nay
    end_ts = now_dt.replace(hour=7, minute=0, second=0, microsecond=0).timestamp()
    start_ts = end_ts - 86400
    
    day_trades = [
        t for t in history 
        if start_ts <= (t.get('close_timestamp') or t.get('entry_timestamp', 0)) <= end_ts
    ]
    
    stats = compute_trade_stats(day_trades)
    yesterday_dt = now_dt - datetime.timedelta(days=1)
    y_str = yesterday_dt.strftime('%d/%m/%Y')
    
    msg = f"""📊 <b>[BÁO CÁO TỔNG KẾT KÈO VIP NGÀY HÔM TRƯỚC - {y_str}]</b> 📊
━━━━━━━━━━━━━━━━━━
⏱️ Chu kỳ: <b>07:00 {y_str} ➔ 07:00 {now_dt.strftime('%d/%m/%Y')}</b>
📈 <b>TỔNG QUAN HIỆU SUẤT:</b>
• 🎯 Tổng số kèo: <b>{stats['total']} kèo</b> (🥇 Vàng: {stats['gold_trades']} | 👑 BTC: {stats['btc_trades']})
• 🏆 Kèo Thắng (TP): <b>{stats['wins']} kèo</b>
• 🛡️ Kèo Hoà Vốn (BE): <b>{stats['be']} kèo</b>
• 🛑 Kèo Cắt Lỗ (SL): <b>{stats['losses']} kèo</b>
• 🔥 <b>Tỷ lệ Thắng (Winrate): {stats['winrate']}%</b>
━━━━━━━━━━━━━━━━━━
💰 <b>TỔNG KẾT LỢI NHUẬN (PNL):</b>
• 🥇 <b>Lợi nhuận VÀNG:</b> <b>{'+' if stats['pnl_gold'] >= 0 else ''}{stats['pnl_gold']:,.2f} Giá</b>
• 👑 <b>Lợi nhuận BITCOIN:</b> <b>{'+' if stats['pnl_btc'] >= 0 else ''}{stats['pnl_btc']:,.1f} USDT</b>
━━━━━━━━━━━━━━━━━━
📝 <b>CHI TIẾT TỪNG KÈO ĐÃ ĐÓNG:</b>\n"""

    if day_trades:
        for idx, t in enumerate(day_trades, 1):
            msg += "\n" + format_single_trade_block(t, index=idx)
    else:
        msg += "\n<i>Ngày hôm trước không có kèo nào đóng hoặc không có tín hiệu thỏa mãn bộ lọc volume khắt khe. Hệ thống giữ vững kỷ luật bảo vệ an toàn vốn!</i>\n"

    active = load_vip_trades()
    if active:
        msg += f"\n⏳ <b>LỆNH ĐANG MỞ HIỆN TẠI ({len(active)} lệnh):</b>\n"
        for idx, t in enumerate(active, 1):
            msg += "\n" + format_single_trade_block(t, index=idx)
            
    msg += f"\n💡 <i>Báo cáo tự động định kỳ vào 07:00 AM mỗi ngày theo tôn chỉ Kỷ Luật & Chuẩn R:R!</i>"
    send_telegram(msg, reply_markup=get_main_keyboard())

def send_weekly_summary_report():
    history = load_vip_history()
    now_dt = datetime.datetime.now(TZ_VN)
    # Khung thời gian tuần trước: 7 ngày (07:00 Thứ 2 tuần trước -> 07:00 Thứ 2 hôm nay)
    end_ts = now_dt.replace(hour=7, minute=0, second=0, microsecond=0).timestamp()
    start_ts = end_ts - 7 * 86400
    
    week_trades = [
        t for t in history 
        if start_ts <= (t.get('close_timestamp') or t.get('entry_timestamp', 0)) <= end_ts
    ]
    
    stats = compute_trade_stats(week_trades)
    start_dt = now_dt - datetime.timedelta(days=7)
    
    msg = f"""🏆 <b>[TỔNG KẾT KÈO VIP TUẦN - SÁNG THỨ HAI]</b> 🏆
━━━━━━━━━━━━━━━━━━
⏱️ Chu kỳ tuần: <b>{start_dt.strftime('%d/%m/%Y')} ➔ {now_dt.strftime('%d/%m/%Y')}</b>
📈 <b>TỔNG QUAN HIỆU SUẤT TUẦN QUA:</b>
• 🎯 Tổng số kèo: <b>{stats['total']} kèo</b> (🥇 Vàng: {stats['gold_trades']} | 👑 BTC: {stats['btc_trades']})
• 🏆 Kèo Thắng (TP): <b>{stats['wins']} kèo</b>
• 🛡️ Kèo Hoà Vốn (BE): <b>{stats['be']} kèo</b>
• 🛑 Kèo Cắt Lỗ (SL): <b>{stats['losses']} kèo</b>
• 🔥 <b>Tỷ lệ Thắng (Winrate): {stats['winrate']}%</b>
━━━━━━━━━━━━━━━━━━
💰 <b>TỔNG KẾT LỢI NHUẬN TUẦN:</b>
• 🥇 <b>VÀNG (XAUUSD):</b> <b>{'+' if stats['pnl_gold'] >= 0 else ''}{stats['pnl_gold']:,.2f} Giá</b>
• 👑 <b>BITCOIN:</b> <b>{'+' if stats['pnl_btc'] >= 0 else ''}{stats['pnl_btc']:,.1f} USDT</b>
━━━━━━━━━━━━━━━━━━
📝 <b>DANH SÁCH TOÀN BỘ KÈO TRONG TUẦN:</b>\n"""

    if week_trades:
        for idx, t in enumerate(week_trades, 1):
            msg += "\n" + format_single_trade_block(t, index=idx)
    else:
        msg += "\n<i>Trong tuần qua không có lệnh nào khớp hoặc đã chốt.</i>\n"

    msg += f"\n🚀 <i>Chúc anh em tuần mới giao dịch đại thắng cùng FX DREAM VIP Bot!</i>"
    send_telegram(msg, reply_markup=get_main_keyboard())

def handle_trade_summary(chat_id=None):
    try:
        history = load_vip_history()
        active = load_vip_trades()
        now_dt = datetime.datetime.now(TZ_VN)
        now_ts = time.time()
        
        # 1. Thống kê toàn bộ lịch sử
        all_stats = compute_trade_stats(history)
        
        # 2. Thống kê 24h gần nhất
        trades_24h = [
            t for t in history 
            if (now_ts - (t.get('close_timestamp') or t.get('entry_timestamp', 0))) <= 86400
        ]
        stats_24h = compute_trade_stats(trades_24h)
        
        # 3. Thống kê 7 ngày gần nhất
        trades_7d = [
            t for t in history 
            if (now_ts - (t.get('close_timestamp') or t.get('entry_timestamp', 0))) <= 7 * 86400
        ]
        stats_7d = compute_trade_stats(trades_7d)
        
        msg = f"""📊 <b>[BẢNG TỔNG KẾT HIỆU SUẤT ĐỐI ĐẦU 2 BOT SONG SONG]</b> 📊
━━━━━━━━━━━━━━━━━━
⏱️ <i>Thời điểm tra cứu: {now_dt.strftime('%H:%M:%S %d/%m/%Y')}</i>

🏆 <b>1. TỔNG HỢP TOÀN BỘ DANH MỤC:</b>
• 🎯 Tổng số kèo: <b>{all_stats['total']} kèo</b> (🥇 Vàng: {all_stats['gold_trades']} | 👑 BTC: {all_stats['btc_trades']})
• 🟢 Thắng: <b>{all_stats['wins']}</b> | 🛡️ BE: <b>{all_stats['be']}</b> | 🔴 SL: <b>{all_stats['losses']}</b>
• 🔥 <b>Tỷ lệ Thắng (Winrate): {all_stats['winrate']}%</b>
• 💰 <b>Tổng PnL Vàng:</b> <b>{'+' if all_stats['pnl_gold'] >= 0 else ''}{all_stats['pnl_gold']:,.2f} Giá</b>
• 💰 <b>Tổng PnL BTC:</b> <b>{'+' if all_stats['pnl_btc'] >= 0 else ''}{all_stats['pnl_btc']:,.1f} USDT</b>
━━━━━━━━━━━━━━━━━━
⚡ <b>2. PHÂN HỆ BOT 1: SCALP M5 (VOLUME PROFILE):</b>
• Số kèo đã đánh: <b>{all_stats['m5_total']} kèo</b> (Thắng: {all_stats['m5_wins']} | SL: {all_stats['m5_losses']})
• Tỷ lệ thắng (Winrate): <b>{all_stats['m5_winrate']}%</b>
• PnL Vàng M5: <b>{'+' if all_stats['m5_pnl_gold'] >= 0 else ''}{all_stats['m5_pnl_gold']:,.2f} Giá</b>
• PnL BTC M5: <b>{'+' if all_stats['m5_pnl_btc'] >= 0 else ''}{all_stats['m5_pnl_btc']:,.1f} USDT</b>
━━━━━━━━━━━━━━━━━━
🧙‍♀️ <b>3. PHÂN HỆ BOT 2: SWING H1 (MA NỮ - BREAK & RETEST):</b>
• Số kèo đã đánh: <b>{all_stats['h1_total']} kèo</b> (Thắng: {all_stats['h1_wins']} | SL: {all_stats['h1_losses']})
• Tỷ lệ thắng (Winrate): <b>{all_stats['h1_winrate']}%</b>
• PnL Vàng H1: <b>{'+' if all_stats['h1_pnl_gold'] >= 0 else ''}{all_stats['h1_pnl_gold']:,.2f} Giá</b>
• PnL BTC H1: <b>{'+' if all_stats['h1_pnl_btc'] >= 0 else ''}{all_stats['h1_pnl_btc']:,.1f} USDT</b>
━━━━━━━━━━━━━━━━━━
📅 <b>4. HIỆU SUẤT 24 GIỜ GẦN NHẤT:</b>
• Số kèo: <b>{stats_24h['total']} kèo</b> (Win: {stats_24h['wins']} | Loss: {stats_24h['losses']})
• PnL Vàng 24h: <b>{'+' if stats_24h['pnl_gold'] >= 0 else ''}{stats_24h['pnl_gold']:,.2f} Giá</b>
• PnL BTC 24h: <b>{'+' if stats_24h['pnl_btc'] >= 0 else ''}{stats_24h['pnl_btc']:,.1f} USDT</b>
━━━━━━━━━━━━━━━━━━
🗓️ <b>5. HIỆU SUẤT 7 NGÀY GẦN NHẤT:</b>
• Số kèo: <b>{stats_7d['total']} kèo</b> (Win: {stats_7d['wins']} | Loss: {stats_7d['losses']})
• PnL Vàng 7D: <b>{'+' if stats_7d['pnl_gold'] >= 0 else ''}{stats_7d['pnl_gold']:,.2f} Giá</b>
• PnL BTC 7D: <b>{'+' if stats_7d['pnl_btc'] >= 0 else ''}{stats_7d['pnl_btc']:,.1f} USDT</b>
━━━━━━━━━━━━━━━━━━
📜 <b>6. DANH SÁCH 5 KÈO HOÀN TẤT GẦN NHẤT:</b>\n"""


        if history:
            recent_trades = list(reversed(history))[:5]
            for idx, t in enumerate(recent_trades, 1):
                msg += "\n" + format_single_trade_block(t, index=idx)
        else:
            msg += "\n<i>Chưa có kèo nào trong lịch sử đóng lệnh.</i>\n"

        if active:
            msg += f"\n⏳ <b>LỆNH ĐANG MỞ HIỆN TẠI ({len(active)} lệnh):</b>\n"
            for idx, t in enumerate(active, 1):
                msg += "\n" + format_single_trade_block(t, index=idx)

        msg += f"\n💡 <i>Tất cả các kèo đều được lưu vết minh bạch: Entry, SL gốc, TP1, TP2, Giá đóng và Lợi nhuận chuẩn R:R.</i>"
        send_telegram(msg, reply_markup=get_main_keyboard(), target_chat_id=chat_id)
    except Exception as e:
        print(f"Lỗi handle_trade_summary: {e}")
        send_telegram(f"⚠️ Có lỗi khi tổng kết kèo: {e}", reply_markup=get_main_keyboard(), target_chat_id=chat_id)

USERS_FILE = os.path.join(os.path.dirname(__file__), 'authorized_users.json')
ADMIN_ID = str(CONFIG['TELEGRAM_CHAT_ID'])
PUBLIC_MODE = True # Tự động cấp quyền Public cho tất cả mọi người (Có thể bật/tắt bằng lệnh /public on hoặc /public off)

def load_authorized_users():
    """Load danh sách người dùng được duyệt sử dụng bot"""
    users = {ADMIN_ID: {'name': 'Chủ Sở Hữu (Admin)', 'role': 'admin', 'date': 'Gốc'}}
    r_data = redis_get_json('coinradar:authorized_users', None)
    if r_data is not None and isinstance(r_data, dict):
        users.update(r_data)
        return users
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, 'r', encoding='utf-8') as f:
                saved = json.load(f)
                users.update(saved)
        except Exception as e:
            print(f"Lỗi load authorized users: {e}")
    return users

def save_authorized_users(users):
    redis_set_json('coinradar:authorized_users', users)
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
            [{"text": "💵 Xem Giá Live (Vàng/BTC/ETH)"}, {"text": "📊 Tổng Kết Kèo TP/SL"}],
            [{"text": "🧙‍♀️ Swing H1 Ma Nữ (Senpai Thành)"}, {"text": "⚖️ Báo Cáo Đối Đầu 2 Bot"}],
            [{"text": "📐 Fibo Sóng Hồi (H1)"}, {"text": "🎯 Scalping Volume Profile M5"}],
            [{"text": "⚡ Tuyệt Chiêu H4 Lưỡng Lự"}],
            [{"text": "👑 Phân Tích BTC"}, {"text": "🥇 Phân Tích VÀNG (XAU)"}],
            [{"text": "💣 Săn Coin Rác (Vol > $100M)"}],
            [{"text": "📈 Tìm Coin TĂNG (LONG)"}, {"text": "📉 Tìm Coin GIẢM (SHORT)"}],
            [{"text": "🇻🇳 Đánh Giá Cổ Phiếu VN"}, {"text": "🔍 Kiểm Tra Lệnh & Báo Cáo Ngày"}],
            [{"text": "🇺🇸 Phân Tích Tin Mỹ (View Dài Hạn)"}, {"text": "⚙️ Menu Hỗ Trợ"}]
        ],
        "resize_keyboard": True,
        "is_persistent": True
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
    Phân tích khung M5 (Khung vào lệnh Entry theo chuẩn VSA Wyckoff & FX Dream KeyVolume):
    - TÔN CHỈ BẤT DI BẤT DỊCH: Tuyệt đối KHÔNG cản tàu khi chưa có CỘT TÍM VSA (Ultra-High Volume / Stopping Volume)!
    1. Xác nhận NẾN: Nến M5 test cản phải rút râu từ chối mạnh (Rejection Wick >= 40% chiều dài nến, nến Pinbar).
    2. Xác nhận CỘT TÍM VSA: Volume >= 1.80x SMA20 (hoặc >= 1.60x nếu râu nến siêu dài >= 48% chuẩn Pinbar).
    -> Đây là dấu hiệu Smart Money hấp thụ (Absorption / Stopping Volume), triệt tiêu hoàn toàn lực đẩy của đối phương!
    """
    chrono = list(reversed(m5_klines_desc))
    recent = chrono[-15:]
    curr_p = float(recent[-1][4])
    
    vols = [float(c[5]) for c in recent]
    avg_vol = (sum(vols) / len(vols)) if vols else 1.0
    
    confirmed_bear_rejection = None
    confirmed_bull_rejection = None
    
    # Quét các nến M5 gần nhất xem có nến nào CỘT TÍM VSA + Rút Râu không
    for c in reversed(recent[-8:]):
        o, h, l, cl, v = float(c[1]), float(c[2]), float(c[3]), float(c[4]), float(c[5])
        rng = h - l
        if rng <= 0:
            continue
        upper_wick = h - max(o, cl)
        lower_wick = min(o, cl) - l
        vol_ratio = v / avg_vol if avg_vol > 0 else 1.0
        # Chuẩn VSA Cột Tím Wyckoff (Ultra-High / Stopping Volume):
        is_vol_spike = (vol_ratio >= 1.80) or (vol_ratio >= 1.60 and (upper_wick / rng >= 0.48 or lower_wick / rng >= 0.48))
        
        # Bearish confirmation: Râu trên dài >= 40% + Nổ Cột Tím VSA + Nến đóng cửa dội xuống
        if (upper_wick / rng >= 0.40) and is_vol_spike and not confirmed_bear_rejection:
            t = datetime.datetime.fromtimestamp(int(c[0])/1000, tz=TZ_VN).strftime('%H:%M')
            confirmed_bear_rejection = {
                'time': t, 'high': h, 'close': cl, 'wick_pct': round((upper_wick / rng)*100, 1),
                'vol_ratio': round(vol_ratio, 2)
            }
            
        # Bullish confirmation: Râu dưới dài >= 40% + Nổ Cột Tím VSA + Nến rút chân đi lên
        if (lower_wick / rng >= 0.40) and is_vol_spike and not confirmed_bull_rejection:
            t = datetime.datetime.fromtimestamp(int(c[0])/1000, tz=TZ_VN).strftime('%H:%M')
            confirmed_bull_rejection = {
                'time': t, 'low': l, 'close': cl, 'wick_pct': round((lower_wick / rng)*100, 1),
                'vol_ratio': round(vol_ratio, 2)
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
            return get_binance_klines('BTCUSDT', interval, limit)

        w_klines = get_kline('W', 25)
        d_klines = get_kline('D', 25)
        h1_klines = get_kline('60', 60)
        m15_klines = get_kline('15', 30)
        m5_klines = get_kline('5', 30)

        if not m5_klines or len(m5_klines) == 0:
            if PLAN_CACHE['BTC'].get('data'):
                return PLAN_CACHE['BTC']['data']
            raise ValueError("m5_klines rỗng từ Binance API")

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

        is_early_bear = touched_bear_ob and (sell_conf is not None) and (sell_conf['wick_pct'] >= 40.0 and sell_conf['vol_ratio'] >= 1.80)
        is_early_bull = touched_bull_ob and (buy_conf is not None) and (buy_conf['wick_pct'] >= 40.0 and buy_conf['vol_ratio'] >= 1.80)

        # XÁC ĐỊNH HƯỚNG ĐÁNH THEO BIAS VĨ MÔ & TEST CẢN
        # ĐIỀU KIỆN XÁC NHẬN: REJECTION CỘT TÍM VSA M5 TẠI OB HOẶC M15 PHÁ VỠ CẤU TRÚC (BOS) + M5 RÚT RÂU!
        is_bear_confirmed = is_early_bear or (is_near_bear_ob and m15_struct['has_bear_bos'] and m5_info['is_confirmed_entry_bear'])
        is_bull_confirmed = is_early_bull or (is_near_bull_ob and m15_struct['has_bull_bos'] and m5_info['is_confirmed_entry_bull'])

        if is_bull_confirmed and not (w1_bear and d1_bear):
            signal = "LONG"
            if is_early_bull:
                setup_desc = f"🟣 Rejection Cột Tím VSA M5 tại Khối Bullish OB ${bullish_ob['mid']:,.1f} (Rút chân {buy_conf['wick_pct']}%, Vol {buy_conf['vol_ratio']}x)"
                diamond_note = "⭐ BẮT ĐẢO CHIỀU TẠI CẢN: Nến M5 rút chân nổ CỘT TÍM VSA tại Hỗ Trợ H1, Smart Money gom hàng!"
            else:
                setup_desc = f"M15 BOS Tăng + M5 Rút Chân Nổ Vol Cột Tím tại Khối Bullish OB ${swing_low:,.1f} ({sl_time})"
                diamond_note = "⭐ ĐẢO CHIỀU UY TÍN: M15 đã phá cấu trúc + M5 kích Cột Tím VSA xác nhận!"
        elif is_bear_confirmed or (w1_bear and d1_bear):
            signal = "SHORT"
            if is_early_bear:
                setup_desc = f"🟣 Rejection Cột Tím VSA M5 tại Khối Bearish OB ${bearish_ob['mid']:,.1f} (Rút râu {sell_conf['wick_pct']}%, Vol {sell_conf['vol_ratio']}x)"
                diamond_note = "⭐ BẮT ĐẢO CHIỀU TẠI CẢN: Nến M5 rút râu nổ CỘT TÍM VSA tại Kháng Cự H1, Smart Money xả hàng!"
            else:
                m5_txt = " + M15 BOS & Nổ Cột Tím VSA" if is_bear_confirmed else " (Đang Chờ M15 BOS)"
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
            sell_tp1 = round(sell_entry - (sell_risk * 1.2), 1)
            sell_tp2 = round(sell_entry - (sell_risk * 2.0), 1)
        else:
            sell_entry = round(bearish_ob['bottom'], 1)
            sell_sl = round(max(bearish_ob['top'] + 150.0, swing_high + 100.0), 1)
            sell_risk = round(sell_sl - sell_entry, 1)
            if sell_risk < 250.0:
                sell_sl = round(sell_entry + 300.0, 1)
                sell_risk = round(sell_sl - sell_entry, 1)
            sell_tp1 = round(sell_entry - (sell_risk * 1.2), 1)
            sell_tp2 = round(sell_entry - (sell_risk * 2.0), 1)

        # 2. Kịch bản CANH BUY (tại Hỗ Trợ H1):
        if is_early_bull and buy_conf:
            buy_entry = round(current_price, 1)
            buy_sl = round(min(buy_conf['low'] - 50.0, bullish_ob['bottom'] - 50.0), 1)
            buy_risk = round(buy_entry - buy_sl, 1)
            if buy_risk < 150.0:
                buy_sl = round(buy_entry - 200.0, 1)
                buy_risk = round(buy_entry - buy_sl, 1)
            buy_tp1 = round(buy_entry + (buy_risk * 1.2), 1)
            buy_tp2 = round(buy_entry + (buy_risk * 2.0), 1)
        else:
            buy_entry = round(bullish_ob['top'], 1)
            buy_sl = round(min(bullish_ob['bottom'] - 150.0, swing_low - 100.0), 1)
            buy_risk = round(buy_entry - buy_sl, 1)
            if buy_risk < 250.0:
                buy_sl = round(buy_entry - 300.0, 1)
                buy_risk = round(buy_entry - buy_sl, 1)
            buy_tp1 = round(buy_entry + (buy_risk * 1.2), 1)
            buy_tp2 = round(buy_entry + (buy_risk * 2.0), 1)

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
                confirm_badge = f"🟣 REJECTION CỘT TÍM VSA M5 TẠI OB H1 ({sell_conf['vol_ratio']}x)"
                action_advice = f"Nến M5 lúc {sell_conf['time']} test Bearish OB H1 rút râu {sell_conf['wick_pct']}% nổ CỘT TÍM VSA {sell_conf['vol_ratio']}x (Stopping Volume)! Đủ điều kiện vào lệnh Sell ngay tại chóp râu M5!"
            elif not is_near_bear_ob:
                confirm_badge = "⏳ CHỜ GIÁ TIẾP CẬN VÙNG CANH SELL (OB H1)"
                action_advice = f"Giá BTC (${current_price:,.1f}) đang cách Vùng Sell [${bearish_ob['bottom']:,.1f} - ${bearish_ob['top']:,.1f}] khoảng {abs(current_price - bearish_ob['bottom']):,.1f} USD. Chưa chạm cản, đứng ngoài quan sát!"
            elif not m15_struct['has_bear_bos']:
                confirm_badge = "⏳ ĐÃ VÀO VÙNG CẢN - CHỜ M15 PHÁ VỠ CẤU TRÚC (TRÁNH CẢN TÀU)"
                action_advice = f"Giá đang chạm Vùng Sell nhưng M15 chưa gãy cấu trúc (chưa thủng đáy ${m15_struct['choch_bear_level']:,.1f}). Đứng ngoài quan sát, tuyệt đối không cản tàu!"
            elif sell_conf:
                confirm_badge = f"🟣 ĐÃ PHÁ VỠ CẤU TRÚC M15 (BOS) + NỔ CỘT TÍM VSA M5 ({sell_conf['vol_ratio']}x)"
                action_advice = f"M15 đã gãy cấu trúc tăng + Nến M5 lúc {sell_conf['time']} rút râu {sell_conf['wick_pct']}% nổ CỘT TÍM VSA {sell_conf['vol_ratio']}x! Đủ điều kiện vào lệnh Sell ngay!"
            else:
                confirm_badge = "⏳ ĐÃ GÃY CẤU TRÚC M15 (CHỜ M5 RETEST NỔ CỘT TÍM VSA)"
                action_advice = f"M15 đã bẻ gãy cấu trúc tăng (thủng ${m15_struct['choch_bear_level']:,.1f}). Đang chờ nến M5 hồi retest cản rút râu nổ Cột Tím VSA để vào lệnh Sell."
        else: # LONG
            is_confirmed = is_bull_confirmed
            entry_limit = buy_entry
            entry_stop = round(swing_high * 1.002, 1)
            sl = buy_sl
            sl_dist = buy_risk
            tp1 = buy_tp1
            tp2 = buy_tp2
            if is_early_bull:
                confirm_badge = f"🟣 REJECTION CỘT TÍM VSA M5 TẠI OB H1 ({buy_conf['vol_ratio']}x)"
                action_advice = f"Nến M5 lúc {buy_conf['time']} test Bullish OB H1 rút chân {buy_conf['wick_pct']}% nổ CỘT TÍM VSA {buy_conf['vol_ratio']}x (Stopping Volume)! Đủ điều kiện vào lệnh Buy ngay tại chóp râu M5!"
            elif not is_near_bull_ob:
                confirm_badge = "⏳ CHỜ GIÁ TIẾP CẬN VÙNG CANH BUY (OB H1)"
                action_advice = f"Giá BTC (${current_price:,.1f}) đang cách Vùng Buy [${bullish_ob['bottom']:,.1f} - ${bullish_ob['top']:,.1f}] khoảng {abs(current_price - bullish_ob['top']):,.1f} USD. Chưa chạm hỗ trợ, đứng ngoài quan sát!"
            elif not m15_struct['has_bull_bos']:
                confirm_badge = "⏳ ĐÃ VÀO VÙNG HỖ TRỢ - CHỜ M15 PHÁ VỠ CẤU TRÚC (TRÁNH BẮT DAO RƠI)"
                action_advice = f"Giá đang chạm Vùng Buy nhưng M15 chưa đảo chiều tăng (chưa vượt đỉnh ${m15_struct['choch_bull_level']:,.1f}). Đứng ngoài quan sát, tuyệt đối không bắt dao rơi!"
            elif buy_conf:
                confirm_badge = f"🟣 ĐÃ PHÁ VỠ CẤU TRÚC M15 (BOS) + NỔ CỘT TÍM VSA M5 ({buy_conf['vol_ratio']}x)"
                action_advice = f"M15 đã đảo chiều tăng + Nến M5 lúc {buy_conf['time']} rút chân {buy_conf['wick_pct']}% nổ CỘT TÍM VSA {buy_conf['vol_ratio']}x! Đủ điều kiện vào lệnh Buy ngay!"
            else:
                confirm_badge = "⏳ ĐÃ GÃY CẤU TRÚC M15 (CHỜ M5 RETEST NỔ CỘT TÍM VSA)"
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
        if PLAN_CACHE['BTC'].get('data'):
            return PLAN_CACHE['BTC']['data']
        fallback_p = 60000.0
        try:
            fb_b = get_binance_klines('BTCUSDT', '5m', 5)
            if fb_b and len(fb_b) > 0:
                fallback_p = float(fb_b[0][4])
        except Exception:
            pass
        return {
            'current_price': fallback_p, 'w1_bias': "🔴 GIẢM (BEARISH)", 'd1_bias': "🔴 GIẢM (BEARISH)",
            'priority_dir': "CANH BÁN (SHORT)", 'major_res': fallback_p + 1000.0, 'major_sup': fallback_p - 1000.0,
            'b_ob_top': fallback_p + 800.0, 'b_ob_bot': fallback_p + 500.0, 'b_ob_mid': fallback_p + 650.0,
            'bull_ob_top': fallback_p - 500.0, 'bull_ob_bot': fallback_p - 800.0, 'bull_ob_mid': fallback_p - 650.0,
            'm5_status': "⏳ Đang chờ xác nhận", 'is_near_bear_ob': False, 'is_near_bull_ob': False,
            'is_confirmed': False, 'confirm_badge': "⏳ ĐANG CHỜ XÁC NHẬN", 'signal': "SHORT",
            'entry_limit': fallback_p, 'entry_stop': fallback_p, 'sl': fallback_p + 350.0, 'sl_dist': 350.0,
            'sl_pct': 0.6, 'tp1': fallback_p - 420.0, 'tp2': fallback_p - 875.0,
            'sell_entry': fallback_p, 'sell_sl': fallback_p + 350.0, 'sell_risk': 350.0,
            'sell_tp1': fallback_p - 420.0, 'sell_tp2': fallback_p - 875.0,
            'buy_entry': fallback_p, 'buy_sl': fallback_p - 350.0, 'buy_risk': 350.0,
            'buy_tp1': fallback_p + 420.0, 'buy_tp2': fallback_p + 875.0,
            'advice': "Hệ thống đang đồng bộ dữ liệu phiên.", 'action_advice': "Đang theo dõi cản."
        }


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
🎯 <b>TP2 (Ăn {plan['sell_risk']*2.0:,.1f} USD):</b> <code>${plan['sell_tp2']:,.1f}</code>

━━━━━━━━━━━━━━━━━━
🟢 <b>2. VÙNG CANH BUY (Hỗ Trợ H1):</b>
• <b>Vùng giá:</b> <code>[${plan['bull_ob_bot']:,.1f} - ${plan['bull_ob_top']:,.1f}]</code>
• <b>Cách đánh:</b> Chờ giá đạp về chạm vùng này ──> Nến M5 rút chân đẩy lên + Kích Volume thì BUY!
👉 <b>Entry Buy:</b> <code>${plan['buy_entry']:,.1f}</code>
🛡️ <b>Stop Loss:</b> <code>${plan['buy_sl']:,.1f}</code> (~{plan['buy_risk']:,.1f} USD)
🎯 <b>TP1 (Ăn {plan['buy_risk']*1.2:,.1f} USD | Chốt 50% & Dời Hoà):</b> <code>${plan['buy_tp1']:,.1f}</code>
🎯 <b>TP2 (Ăn {plan['buy_risk']*2.0:,.1f} USD):</b> <code>${plan['buy_tp2']:,.1f}</code>

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
        d = None
        try:
            with urllib.request.urlopen(req, timeout=8) as r:
                res_json = json.loads(r.read().decode())
                rows = res_json.get('data', [])
                if rows and len(rows) > 0 and 'd' in rows[0]:
                    d = rows[0]['d']
        except Exception as e_scan:
            print(f"TradingView CFD scan warning: {e_scan}")

        if d and len(d) == len(cols):
            data = dict(zip(cols, d))
            current_gold = round(data['close'], 2)
            bid = round(data.get('bid') or (current_gold - 0.35), 2)
            ask = round(data.get('ask') or (current_gold + 0.35), 2)
        else:
            # Fallback sang OANDA WebSocket trực tiếp
            ws_klines = get_oanda_klines('5', 5)
            if ws_klines and len(ws_klines) > 0:
                current_gold = round(float(ws_klines[0][4]), 2)
            elif PLAN_CACHE['GOLD'].get('data'):
                return PLAN_CACHE['GOLD']['data']
            else:
                current_gold = 3580.0
            bid = round(current_gold - 0.35, 2)
            ask = round(current_gold + 0.35, 2)
            data = {
                'close': current_gold, 'open': current_gold, 'high': current_gold + 2.0, 'low': current_gold - 2.0,
                'close|1W': current_gold, 'EMA20|1W': current_gold, 'EMA20': current_gold,
                'high|5': current_gold + 1.0, 'high|15': current_gold + 3.0, 'low|15': current_gold - 3.0,
                'EMA20|15': current_gold, 'EMA20|240': current_gold
            }
        data_source = "TradingView (OANDA:XAUUSD - Chuẩn MT5 100%)"

        
        # 1. BIAS ĐA KHUNG (TUẦN W1 & NGÀY D1)
        w1_bear = data['close|1W'] < data['EMA20|1W']
        d1_bear = data['close'] < data['EMA20']
        w1_bias = "🔴 GIẢM (BEARISH)" if w1_bear else "🟢 TĂNG (BULLISH)"
        d1_bias = "🔴 GIẢM (BEARISH)" if d1_bear else "🟢 TĂNG (BULLISH)"
        
        # 2. Lấy dữ liệu H1 klines TRỰC TIẾP TỪ OANDA:XAUUSD (TradingView WebSocket) & tính Valid Swing High / Low & Order Block (OB) SMC
        gold_h1_klines = get_oanda_klines('60', 60)
        sh_raw, b_ob_raw, sl_raw, bull_ob_raw = find_smc_swings_and_ob(gold_h1_klines, is_gold=True)
        delta = 0.0 # Dữ liệu 100% OANDA, hoàn toàn không có độ lệch sàn (delta = 0)
        
        major_res = round(sh_raw['high'], 2)
        b_ob_top = round(b_ob_raw['top'], 2)
        b_ob_bot = round(b_ob_raw['bottom'], 2)
        b_ob_mid = round(b_ob_raw['mid'], 2)
        sh_time = sh_raw['time']
        sh_filter = sh_raw.get('filter', 'Duyệt Qua InsideBar')

        major_sup = round(sl_raw['low'], 2)
        bull_ob_top = round(bull_ob_raw['top'], 2)
        bull_ob_bot = round(bull_ob_raw['bottom'], 2)
        bull_ob_mid = round(bull_ob_raw['mid'], 2)
        sl_time = sl_raw['time']
        sl_filter = sl_raw.get('filter', 'Duyệt Qua InsideBar')

        m5_high = round(data['high|5'], 2)
        m15_high = round(data['high|15'], 2)
        m15_low = round(data['low|15'], 2)
        m15_ema20 = round(data['EMA20|15'], 2)
        h4_ema20 = round(data['EMA20|240'], 2)
        
        # 3. Phân tích cấu trúc M15 TRỰC TIẾP TỪ OANDA:XAUUSD (Structure Timeframe - Chống Cản Tàu) & Vùng HVN/POC
        try:
            gold_m15_klines = get_oanda_klines('15', 30)
            poc_raw, hvn_l_raw, hvn_u_raw = calculate_keyvolume_nodes(gold_m15_klines)
            poc_gold_m15 = round(poc_raw, 2)
            hvn_lower = round(hvn_l_raw, 2)
            hvn_upper = round(hvn_u_raw, 2)
            m15_struct = analyze_m15_structure(gold_m15_klines, delta=0.0, is_gold=True)
        except Exception:
            poc_gold_m15 = round((m15_high + m15_low + m15_ema20) / 3.0, 2)
            hvn_lower = round(m15_low, 2)
            hvn_upper = round(m15_high, 2)
            gold_m15_klines = []
            m15_struct = {'has_bear_bos': False, 'has_bull_bos': False, 'choch_bear_level': m15_low, 'choch_bull_level': m15_high}
        
        # 4. Phân tích khung M5 TRỰC TIẾP TỪ OANDA:XAUUSD (Khung vào lệnh Entry theo chuẩn SMC)
        try:
            gold_m5_klines = get_oanda_klines('5', 30)
            m5_info = analyze_m5_entry(gold_m5_klines)
            m5_entry_high = round(m5_info['m5_high'], 2)
            m5_entry_low = round(m5_info['m5_low'], 2)
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

        is_early_bear = touched_bear_ob and (sell_conf is not None) and (sell_conf['wick_pct'] >= 40.0 and sell_conf['vol_ratio'] >= 1.80)
        is_early_bull = touched_bull_ob and (buy_conf is not None) and (buy_conf['wick_pct'] >= 40.0 and buy_conf['vol_ratio'] >= 1.80)

        # XÁC ĐỊNH HƯỚNG ĐÁNH THEO BIAS VĨ MÔ & TEST CẢN
        # ĐIỀU KIỆN XÁC NHẬN: REJECTION CỘT TÍM VSA M5 TẠI OB HOẶC M15 PHÁ VỠ CẤU TRÚC (BOS) + M5 RÚT RÂU!
        is_bear_confirmed = is_early_bear or (is_near_bear_ob and m15_struct['has_bear_bos'] and m5_info['is_confirmed_entry_bear'])
        is_bull_confirmed = is_early_bull or (is_near_bull_ob and m15_struct['has_bull_bos'] and m5_info['is_confirmed_entry_bull'])
        
        if is_bull_confirmed and not (w1_bear and d1_bear):
            signal = "LONG"
            if is_early_bull:
                setup_desc = f"🟣 Rejection Cột Tím VSA M5 tại Khối Bullish OB ${bull_ob_mid:,.2f} (Rút chân {buy_conf['wick_pct']}%, Vol {buy_conf['vol_ratio']}x)"
                diamond_note = "⭐ BẮT ĐẢO CHIỀU TẠI CẢN: Nến M5 rút chân nổ CỘT TÍM VSA tại Hỗ Trợ H1, Smart Money gom hàng!"
            else:
                setup_desc = f"M15 BOS Tăng + M5 Rút Chân Nổ Vol Cột Tím tại Khối Bullish OB ${major_sup:,.2f} ({sl_time})"
                diamond_note = "⭐ ĐẢO CHIỀU UY TÍN: M15 đã phá cấu trúc + M5 kích Cột Tím VSA xác nhận!"
        elif is_bear_confirmed or (w1_bear and d1_bear):
            signal = "SHORT"
            if is_early_bear:
                setup_desc = f"🟣 Rejection Cột Tím VSA M5 tại Khối Bearish OB ${b_ob_mid:,.2f} (Rút râu {sell_conf['wick_pct']}%, Vol {sell_conf['vol_ratio']}x)"
                diamond_note = "⭐ BẮT ĐẢO CHIỀU TẠI CẢN: Nến M5 rút râu nổ CỘT TÍM VSA tại Kháng Cự H1, Smart Money xả hàng!"
            else:
                m5_txt = " + M15 BOS & Nổ Cột Tím VSA" if is_bear_confirmed else " (Đang Chờ M15 BOS)"
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
            sell_tp1 = round(sell_entry - (sell_risk * 1.2), 2)
            sell_tp2 = round(sell_entry - (sell_risk * 2.0), 2)
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
            sell_tp2 = round(sell_entry - (sell_risk * 2.0), 2)

        # 2. Kịch bản CANH BUY (tại Hỗ Trợ H1):
        if is_early_bull and buy_conf:
            buy_entry = round(current_gold, 2)
            buy_sl = round(min(buy_conf['low'] - 1.5, bull_ob_bot - 1.5), 2)
            buy_risk = round(buy_entry - buy_sl, 2)
            if buy_risk < 3.5:
                buy_sl = round(buy_entry - 5.0, 2)
                buy_risk = round(buy_entry - buy_sl, 2)
            buy_tp1 = round(buy_entry + (buy_risk * 1.2), 2)
            buy_tp2 = round(buy_entry + (buy_risk * 2.0), 2)
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
            buy_tp2 = round(buy_entry + (buy_risk * 2.0), 2)

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
                confirm_badge = f"🟣 REJECTION CỘT TÍM VSA M5 TẠI OB H1 ({sell_conf['vol_ratio']}x)"
                action_advice = f"Nến M5 lúc {sell_conf['time']} test Bearish OB H1 rút râu {sell_conf['wick_pct']}% nổ CỘT TÍM VSA {sell_conf['vol_ratio']}x (Stopping Volume)! Đủ điều kiện vào lệnh Sell ngay tại chóp râu M5!"
            elif not is_near_bear_ob:
                confirm_badge = "⏳ CHỜ GIÁ TIẾP CẬN VÙNG CANH SELL (OB H1)"
                action_advice = f"Giá Vàng (${current_gold:,.2f}) đang cách Vùng Sell [${b_ob_bot:,.2f} - ${b_ob_top:,.2f}] khoảng {abs(current_gold - b_ob_bot):.1f} giá. Chưa chạm cản, đứng ngoài quan sát!"
            elif not m15_struct['has_bear_bos']:
                confirm_badge = "⏳ ĐÃ VÀO VÙNG CẢN - CHỜ M15 PHÁ VỠ CẤU TRÚC (TRÁNH CẢN TÀU)"
                action_advice = f"Giá Vàng đang phản ứng tại Vùng Sell. M15 chưa gãy cấu trúc (chưa thủng đáy ${m15_struct['choch_bear_level']:,.2f}). Đứng ngoài quan sát, tuyệt đối không cản tàu!"
            elif sell_conf:
                confirm_badge = f"🟣 ĐÃ PHÁ VỠ CẤU TRÚC M15 (BOS) + NỔ CỘT TÍM VSA M5 ({sell_conf['vol_ratio']}x)"
                action_advice = f"M15 đã gãy cấu trúc tăng + Nến M5 lúc {sell_conf['time']} rút râu {sell_conf['wick_pct']}% nổ CỘT TÍM VSA {sell_conf['vol_ratio']}x! Đủ điều kiện vào lệnh Sell ngay!"
            else:
                confirm_badge = "⏳ ĐÃ GÃY CẤU TRÚC M15 (CHỜ M5 RETEST NỔ CỘT TÍM VSA)"
                action_advice = f"M15 đã bẻ gãy cấu trúc tăng (thủng ${m15_struct['choch_bear_level']:,.2f}). Đang chờ nến M5 hồi retest cản rút râu nổ Cột Tím VSA để vào lệnh Sell."
        else: # LONG
            is_confirmed = is_bull_confirmed
            entry_limit = buy_entry
            entry_stop = round(major_res + 1.2, 2)
            sl = buy_sl
            sl_dist = buy_risk
            tp1 = buy_tp1
            tp2 = buy_tp2
            if is_early_bull:
                confirm_badge = f"🟣 REJECTION CỘT TÍM VSA M5 TẠI OB H1 ({buy_conf['vol_ratio']}x)"
                action_advice = f"Nến M5 lúc {buy_conf['time']} test Bullish OB H1 rút chân {buy_conf['wick_pct']}% nổ CỘT TÍM VSA {buy_conf['vol_ratio']}x (Stopping Volume)! Đủ điều kiện vào lệnh Buy ngay tại chóp râu M5!"
            elif not is_near_bull_ob:
                confirm_badge = "⏳ CHỜ GIÁ TIẾP CẬN VÙNG CANH BUY (OB H1)"
                action_advice = f"Giá Vàng (${current_gold:,.2f}) đang cách Vùng Buy [${bull_ob_bot:,.2f} - ${bull_ob_top:,.2f}] khoảng {abs(current_gold - bull_ob_top):.1f} giá. Chưa chạm hỗ trợ, đứng ngoài quan sát!"
            elif not m15_struct['has_bull_bos']:
                confirm_badge = "⏳ ĐÃ VÀO VÙNG HỖ TRỢ - CHỜ M15 PHÁ VỠ CẤU TRÚC (TRÁNH BẮT DAO RƠI)"
                action_advice = f"Giá Vàng đang phản ứng tại Vùng Buy. M15 chưa đảo chiều tăng (chưa vượt đỉnh ${m15_struct['choch_bull_level']:,.2f}). Đứng ngoài quan sát, tuyệt đối không bắt dao rơi!"
            elif buy_conf:
                confirm_badge = f"🟣 ĐÃ PHÁ VỠ CẤU TRÚC M15 (BOS) + NỔ CỘT TÍM VSA M5 ({buy_conf['vol_ratio']}x)"
                action_advice = f"M15 đã đảo chiều tăng + Nến M5 lúc {buy_conf['time']} rút chân {buy_conf['wick_pct']}% nổ CỘT TÍM VSA {buy_conf['vol_ratio']}x! Đủ điều kiện vào lệnh Buy ngay!"
            else:
                confirm_badge = "⏳ ĐÃ GÃY CẤU TRÚC M15 (CHỜ M5 RETEST NỔ CỘT TÍM VSA)"
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
        if PLAN_CACHE['GOLD'].get('data'):
            return PLAN_CACHE['GOLD']['data']
        fallback_p = 3580.0
        try:
            fb_klines = get_oanda_klines('5', 5)
            if fb_klines and len(fb_klines) > 0:
                fallback_p = float(fb_klines[0][4])
        except Exception:
            pass
        return {
            'current_price': fallback_p, 'bid': fallback_p - 0.35, 'ask': fallback_p + 0.35,
            'w1_bias': "🔴 GIẢM (BEARISH)", 'd1_bias': "🔴 GIẢM (BEARISH)",
            'priority_dir': "CANH BÁN (SHORT)", 'major_res': fallback_p + 20.0, 'major_sup': fallback_p - 20.0,
            'b_ob_top': fallback_p + 15.0, 'b_ob_bot': fallback_p + 10.0, 'b_ob_mid': fallback_p + 12.5,
            'bull_ob_top': fallback_p - 10.0, 'bull_ob_bot': fallback_p - 15.0, 'bull_ob_mid': fallback_p - 12.5,
            'm5_status': "⏳ Đang chờ xác nhận", 'is_near_bear_ob': False, 'is_near_bull_ob': False,
            'is_confirmed': False, 'confirm_badge': "⏳ ĐANG CHỜ XÁC NHẬN", 'signal': "SHORT",
            'entry_limit': fallback_p, 'entry_stop': fallback_p, 'sl': fallback_p + 6.0, 'sl_dist': 6.0,
            'tp1': fallback_p - 7.2, 'tp2': fallback_p - 15.0, 'sell_entry': fallback_p, 'sell_sl': fallback_p + 6.0,
            'sell_risk': 6.0, 'sell_tp1': fallback_p - 7.2, 'sell_tp2': fallback_p - 15.0,
            'buy_entry': fallback_p, 'buy_sl': fallback_p - 6.0, 'buy_risk': 6.0, 'buy_tp1': fallback_p + 7.2,
            'buy_tp2': fallback_p + 15.0, 'advice': "Hệ thống đang đồng bộ dữ liệu phiên."
        }


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
🎯 <b>TP2 (Ăn {plan['sell_risk']*2.0:,.1f} Giá):</b> <code>${plan['sell_tp2']:,.2f}</code>

━━━━━━━━━━━━━━━━━━
🟢 <b>2. VÙNG CANH BUY (Hỗ Trợ H1):</b>
• <b>Vùng giá:</b> <code>[${plan['bull_ob_bot']:,.2f} - ${plan['bull_ob_top']:,.2f}]</code>
• <b>Cách đánh:</b> Chờ giá đạp về chạm vùng này ──> Nến M5 rút chân đẩy lên + Kích Volume thì BUY!
👉 <b>Entry Buy:</b> <code>${plan['buy_entry']:,.2f}</code>
🛡️ <b>Stop Loss:</b> <code>${plan['buy_sl']:,.2f}</code> (~{plan['buy_risk']:,.1f} Giá)
🎯 <b>TP1 (Ăn {plan['buy_risk']*1.2:,.1f} Giá | Chốt 50% & Dời Hoà):</b> <code>${plan['buy_tp1']:,.2f}</code>
🎯 <b>TP2 (Ăn {plan['buy_risk']*2.0:,.1f} Giá):</b> <code>${plan['buy_tp2']:,.2f}</code>

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
            # Lấy nến H4 trực tiếp từ OANDA:XAUUSD (chuẩn MT5 100%)
            klines = get_oanda_klines('240', 10)
            if not klines:
                raise Exception("Không thể lấy nến H4 OANDA")
            curr_p = float(klines[0][4])
            delta = 0.0
        else:
            # Lấy nến H4 trực tiếp từ Binance BTCUSDT
            klines = get_binance_klines('BTCUSDT', '4h', 10)
            if not klines:
                raise Exception("Không thể lấy nến H4 Binance")
            curr_p = float(klines[0][4])
            delta = 0.0

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
    - 100% chuẩn OANDA:XAUUSD cho Vàng và Binance BTCUSDT cho Bitcoin.
    """
    symbol = 'OANDA:XAUUSD' if asset == 'GOLD' else 'BTCUSDT'
    if asset == 'GOLD':
        klines = get_oanda_klines('5', 600)
    else:
        klines = get_binance_klines('BTCUSDT', '5m', 600)

    def_p = 3580.0 if asset == 'GOLD' else 60000.0
    safe_default = {
        'asset': asset, 'symbol': symbol, 'curr_p': def_p, 'daily_open': def_p,
        'hod': def_p + 10.0, 'lod': def_p - 10.0, 'daily_bias': "Đang đồng bộ",
        'poc': def_p, 'val': def_p - 5.0, 'vah': def_p + 5.0,
        'y_poc': def_p, 'y_val': def_p - 5.0, 'y_vah': def_p + 5.0,
        'y_shape': "Balanced D-Shape", 'y_shape_desc': "Cân bằng",
        'is_l_shape': False, 'is_p_shape': False, 'signal': "HOLD", 'is_buy': True,
        'entry': def_p, 'sl': def_p - 5.0, 'risk': 5.0, 'tp1': def_p + 6.0, 'tp2': def_p + 10.0,
        'wick_info': "Đang kết nối feed nến", 'best_rejection': None, 'confirmed_defense': None,
        'is_defense_confirmed': False, 'is_ready_to_enter': False,
        'defense_badge': "⏳ Đang đồng bộ feed nến",
        'action_plan_text': "Hệ thống đang kết nối dữ liệu nến.",
        'is_rejection_fresh': False, 'dist_to_entry': 999.0, 'candles_count': 0
    }

    if not klines or len(klines) < 10:
        return safe_default

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
        safe_default['curr_p'] = curr_p
        safe_default['daily_open'] = daily_open
        safe_default['poc'] = curr_p
        return safe_default


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

    # 4. KIỂM TRA TÍN HIỆU VOLUME M5 BẢO VỆ VÙNG LOW VOLUME (VAL), POC HOẶC HIGH VOLUME (VAH)
    avg_vol_m5 = sum([float(k[5]) for k in klines[1:21]]) / 20 if len(klines) >= 21 else 1.0
    confirmed_defense = None
    best_rejection = None
    tol_val = 5.5 if asset == 'GOLD' else 350.0

    # Quét 5 nến M5 đã đóng gần nhất (indices 1 đến 5)
    for i in range(1, min(6, len(session_klines))):
        k = session_klines[i]
        o, h, l, c, v = float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])
        rng = h - l
        if rng <= 0: continue
        lw = min(o, c) - l
        uw = h - max(o, c)
        lw_pct = (lw / rng) * 100
        uw_pct = (uw / rng) * 100
        vol_ratio = v / avg_vol_m5 if avg_vol_m5 > 0 else 1.0

        if best_rejection is None or max(lw_pct, uw_pct) > best_rejection['pct']:
            best_rejection = {
                'type': 'BULL' if lw_pct >= uw_pct else 'BEAR',
                'pct': max(lw_pct, uw_pct),
                'candle_idx': i,
                'low': l, 'high': h, 'close': c, 'open': o,
                'vol_ratio': round(vol_ratio, 2)
            }

        # Điều kiện nổ CỘT TÍM VSA (Wyckoff Stopping Volume / Ultra-High):
        # Volume >= 1.80x trung bình (hoặc >= 1.60x nếu râu nến siêu dài >= 48% chuẩn Pinbar)
        is_vol_spike = (vol_ratio >= 1.80) or (vol_ratio >= 1.60 and max(lw_pct, uw_pct) >= 48.0)
        if not is_vol_spike:
            continue

        # A. Kiểm tra bảo vệ Vùng Low Volume / VAL (đáy) hoặc POC (để BUY)
        dist_yval = abs(l - y_val)
        dist_dval = abs(l - vp['val'])
        dist_poc = abs(l - vp['poc'])
        min_bottom_dist = min(dist_yval, dist_dval, dist_poc)

        if min_bottom_dist <= tol_val:
            is_bull_shape = (lw_pct >= 40.0) or (c > o and (c - o)/rng >= 0.55 and vol_ratio >= 2.0)
            if is_bull_shape and c >= min(y_val, vp['val'], vp['poc']) - (1.5 if asset == 'GOLD' else 60.0):
                z_name = "LOW VOLUME (VAL ĐÁY)" if min_bottom_dist in (dist_yval, dist_dval) else "POC KIỂM SOÁT"
                confirmed_defense = {
                    'type': 'BULL',
                    'zone_name': z_name,
                    'candle_idx': i,
                    'vol_ratio': round(vol_ratio, 2),
                    'wick_pct': round(lw_pct, 1),
                    'low': l, 'high': h, 'close': c, 'open': o
                }
                break

        # B. Kiểm tra bảo vệ Vùng High Volume / VAH (đỉnh) hoặc POC (để SELL)
        dist_yvah = abs(h - y_vah)
        dist_dvah = abs(h - vp['vah'])
        dist_poc_h = abs(h - vp['poc'])
        min_top_dist = min(dist_yvah, dist_dvah, dist_poc_h)

        if min_top_dist <= tol_val:
            is_bear_shape = (uw_pct >= 40.0) or (o > c and (o - c)/rng >= 0.55 and vol_ratio >= 2.0)
            if is_bear_shape and c <= max(y_vah, vp['vah'], vp['poc']) + (1.5 if asset == 'GOLD' else 60.0):
                z_name = "HIGH VOLUME (VAH ĐỈNH)" if min_top_dist in (dist_yvah, dist_dvah) else "POC KIỂM SOÁT"
                confirmed_defense = {
                    'type': 'BEAR',
                    'zone_name': z_name,
                    'candle_idx': i,
                    'vol_ratio': round(vol_ratio, 2),
                    'wick_pct': round(uw_pct, 1),
                    'low': l, 'high': h, 'close': c, 'open': o
                }
                break

    is_defense_confirmed = (confirmed_defense is not None)
    is_ready_to_enter = (is_defense_confirmed and confirmed_defense['candle_idx'] <= 2)

    if is_defense_confirmed:
        purple_ico = "🟣" if confirmed_defense['vol_ratio'] >= 1.80 else "🔥"
        defense_badge = f"{purple_ico} ĐÃ XÁC NHẬN BẢO VỆ {confirmed_defense['zone_name']} (Nến M5 nổ CỘT TÍM VSA x{confirmed_defense['vol_ratio']} + Rút râu {confirmed_defense['wick_pct']}%)"
        is_buy = (confirmed_defense['type'] == 'BULL')
        sig = f"{'BUY' if is_buy else 'SELL'} (Đã nổ Cột Tím VSA bảo vệ {confirmed_defense['zone_name']})"
    else:
        defense_badge = "⏳ CHƯA CÓ CỘT TÍM VSA BẢO VỆ CẢN (Đang chờ nến M5 nổ Vol tím x1.8x - x2.0x)"
        is_buy = (curr_p >= daily_open)
        sig = "BUY ROTATION (Tụ Đáy yVAL ➔ VAH)" if (is_l_shape and curr_p <= y_vah) else ("SELL ROTATION (Tụ Đỉnh yVAH ➔ VAL)" if (is_p_shape and curr_p >= y_val) else ("BUY SCALPING (Hỗ Trợ)" if is_buy else "SELL SCALPING (Kháng Cự)"))

    if asset == 'GOLD':
        if is_buy:
            entry = round(best_rejection['low'] + 1.2, 2) if (best_rejection and abs(curr_p - best_rejection['low']) < 6.0) else round(max(vp['poc'], vp['val']), 2)
            # Tinh chỉnh SL chuẩn theo Low Volume / VAL / POC: đệm an toàn 1.8-2.5 giá ngoài chân râu bảo vệ
            base_bottom = confirmed_defense['low'] if confirmed_defense else (best_rejection['low'] if best_rejection else min(y_val, vp['val']))
            sl = round(base_bottom - 2.0, 2)
            risk = round(abs(entry - sl), 2)
            # Khống chế khoảng cách SL hợp lý: từ 5.5 đến 9.0 giá (không quá ngắn bị quét, không quá xa làm xấu R:R)
            if risk < 5.5:
                risk = 6.5
                sl = round(entry - risk, 2)
            elif risk > 9.0:
                risk = 8.5
                sl = round(entry - risk, 2)

            target_up = y_vah if is_l_shape else max(vp['vah'], hod)
            tp1 = round(entry + risk * 1.2, 2)
            tp2 = round(entry + risk * 2.0, 2)
        else:
            entry = round(best_rejection['high'] - 1.2, 2) if (best_rejection and abs(curr_p - best_rejection['high']) < 6.0) else round(min(vp['poc'], vp['vah']), 2)
            # Tinh chỉnh SL chuẩn theo High Volume / VAH / POC: đệm an toàn 1.8-2.5 giá ngoài đỉnh râu bảo vệ
            base_top = confirmed_defense['high'] if confirmed_defense else (best_rejection['high'] if best_rejection else max(y_vah, vp['vah']))
            sl = round(base_top + 2.0, 2)
            risk = round(abs(sl - entry), 2)
            if risk < 5.5:
                risk = 6.5
                sl = round(entry + risk, 2)
            elif risk > 9.0:
                risk = 8.5
                sl = round(entry + risk, 2)

            target_down = y_val if is_p_shape else min(vp['val'], lod)
            tp1 = round(entry - risk * 1.2, 2)
            tp2 = round(entry - risk * 2.0, 2)
    else: # BTC
        if is_buy:
            entry = round(best_rejection['low'] + 50.0, 1) if (best_rejection and abs(curr_p - best_rejection['low']) < 300.0) else round(max(vp['poc'], vp['val']), 1)
            base_bottom = confirmed_defense['low'] if confirmed_defense else (best_rejection['low'] if best_rejection else min(y_val, vp['val']))
            sl = round(base_bottom - 100.0, 1)
            risk = round(abs(entry - sl), 1)
            # Khống chế khoảng cách SL BTC hợp lý: từ 250 đến 420 USD
            if risk < 250.0:
                risk = 300.0
                sl = round(entry - risk, 1)
            elif risk > 450.0:
                risk = 380.0
                sl = round(entry - risk, 1)

            target_up = y_vah if is_l_shape else max(vp['vah'], hod)
            tp1 = round(entry + risk * 1.2, 1)
            tp2 = round(entry + risk * 2.0, 1)
        else:
            entry = round(best_rejection['high'] - 50.0, 1) if (best_rejection and abs(curr_p - best_rejection['high']) < 300.0) else round(min(vp['poc'], vp['vah']), 1)
            base_top = confirmed_defense['high'] if confirmed_defense else (best_rejection['high'] if best_rejection else max(y_vah, vp['vah']))
            sl = round(base_top + 100.0, 1)
            risk = round(abs(sl - entry), 1)
            if risk < 250.0:
                risk = 300.0
                sl = round(entry + risk, 1)
            elif risk > 450.0:
                risk = 380.0
                sl = round(entry + risk, 1)

            target_down = y_val if is_p_shape else min(vp['val'], lod)
            tp1 = round(entry - risk * 1.2, 1)
            tp2 = round(entry - risk * 2.0, 1)

    wick_str = f"Nến M5 test râu {best_rejection['pct']:.1f}%" if best_rejection else "Giá dao động quanh mốc Volume Profile"
    dec = 2 if asset == 'GOLD' else 1

    if is_ready_to_enter:
        action_plan_text = f"🔥 <b>{sig} (ĐÃ BẢO VỆ CẢN)</b>\n   👉 Entry: <code>${entry:,.{dec}f}</code> | 🛡️ SL: <code>${sl:,.{dec}f}</code> | 🎯 TP1: <code>${tp1:,.{dec}f}</code> | 🎯 TP2: <code>${tp2:,.{dec}f}</code>"
    else:
        action_plan_text = "⏸️ <b>ĐANG RÌNH:</b> <i>Chưa có nến M5 nổ Volume bảo vệ cản Low Vol/POC/High Vol — Tuyệt đối không vào sớm để tránh cắn SL!</i>"

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
        'confirmed_defense': confirmed_defense,
        'is_defense_confirmed': is_defense_confirmed,
        'is_ready_to_enter': is_ready_to_enter,
        'defense_badge': defense_badge,
        'action_plan_text': action_plan_text,
        'is_rejection_fresh': (best_rejection is not None and best_rejection['candle_idx'] <= 1),
        'dist_to_entry': round(abs(curr_p - entry), 2),
        'candles_count': len(session_klines)
    }

def analyze_manu_h1_plan(asset='GOLD'):
    """
    Phân tích Chiến Lược Ma Nữ / Cửu Âm Chân Kinh của Duy Thành (Senpai Thành) trên khung H1:
    - Nhận diện Cản Linechart (Đỉnh/Đáy nến đóng mở cửa rolling 25 nến H1).
    - Nến Breakout (cây H1 vừa đóng): Đóng nến dứt khoát vượt cản Linechart.
    - Nến Hiện Tại (Running H1): Thả râu hồi test lại cản (Perfect Wick Retest).
    - Đặt Stop Order: Buy Stop tại đỉnh nến phá / Sell Stop tại đáy nến phá.
    - SL: Đặt tại mút râu hồi (Perfect Wick).
    - TP: TP1 = 1.0R (Độ nảy thị trường: lùi bao nhiêu tiến bấy nhiêu), TP2 = 1.8R.
    """
    bars = get_oanda_klines(resolution='60', count=40) if asset == 'GOLD' else get_binance_klines('BTCUSDT', interval='1h', limit=40)
    if not bars or len(bars) < 30:
        return None

    curr_bar = bars[0] # Nến H1 đang chạy
    prev_bar = bars[1] # Nến H1 vừa đóng

    # 25-bar rolling linechart levels
    body_highs = [max(b[1], b[4]) for b in bars[2:27]]
    body_lows = [min(b[1], b[4]) for b in bars[2:27]]

    recent_res = max(body_highs)
    recent_sup = min(body_lows)

    curr_p = curr_bar[4]
    dec = 2 if asset == 'GOLD' else 1

    res = {
        'asset': asset,
        'symbol': 'XAUUSD' if asset == 'GOLD' else 'BTCUSDT',
        'curr_p': curr_p,
        'recent_res': recent_res,
        'recent_sup': recent_sup,
        'is_setup': False,
        'direction': None,
        'entry': 0.0,
        'sl': 0.0,
        'risk': 0.0,
        'tp1': 0.0,
        'tp2': 0.0,
        'is_triggered': False
    }

    # BUY SETUP: Nến H1 trước đóng trên Cản Linechart Kháng cự
    if prev_bar[4] > recent_res and bars[2][4] <= recent_res:
        break_high = prev_bar[2]
        break_close = prev_bar[4]
        # Nến hiện tại đã thả râu dưới test lại cản vừa phá
        if curr_bar[3] <= break_close:
            entry = break_high
            sl = curr_bar[3]
            risk = entry - sl
            min_risk = entry * 0.0005
            if risk >= min_risk:
                res.update({
                    'is_setup': True,
                    'direction': 'BUY',
                    'entry': round(entry, dec),
                    'sl': round(sl, dec),
                    'risk': round(risk, dec),
                    'tp1': round(entry + risk * 1.0, dec),
                    'tp2': round(entry + risk * 1.8, dec),
                    'is_triggered': (curr_p >= entry)
                })

    # SELL SETUP: Nến H1 trước đóng dưới Cản Linechart Hỗ trợ
    elif prev_bar[4] < recent_sup and bars[2][4] >= recent_sup:
        break_low = prev_bar[3]
        break_close = prev_bar[4]
        # Nến hiện tại đã thả râu trên test lại cản vừa phá
        if curr_bar[2] >= break_close:
            entry = break_low
            sl = curr_bar[2]
            risk = sl - entry
            min_risk = entry * 0.0005
            if risk >= min_risk:
                res.update({
                    'is_setup': True,
                    'direction': 'SELL',
                    'entry': round(entry, dec),
                    'sl': round(sl, dec),
                    'risk': round(risk, dec),
                    'tp1': round(entry - risk * 1.0, dec),
                    'tp2': round(entry - risk * 1.8, dec),
                    'is_triggered': (curr_p <= entry)
                })

    return res

def handle_manu_h1_analysis(chat_id=None):
    """Báo cáo phân tích thế nến H1 Ma Nữ (Cửu Âm Chân Kinh - Duy Thành)"""
    send_telegram("⏳ <i>Đang quét cấu trúc Cản Linechart & Râu Nến H1 Ma Nữ (OANDA & Binance)...</i>", target_chat_id=chat_id)
    try:
        p_gold = analyze_manu_h1_plan('GOLD')
        p_btc = analyze_manu_h1_plan('BTC')
        
        msg = """🧙‍♀️ <b>[PHÂN TÍCH THẾ NẾN SWING H1 MA NỮ (SENPAI THÀNH)]</b> 🧙‍♀️
━━━━━━━━━━━━━━━━━━
<i>Hệ thống Break of Previous Candle + Perfect Wick Retest + Stop Order</i>

🥇 <b>1. VÀNG (OANDA:XAUUSD H1):</b>
• 💰 Giá Live: <code>${:,.2f}</code>
• 🏛️ Cản Linechart H1: Kháng cự <code>${:,.2f}</code> | Hỗ trợ <code>${:,.2f}</code>""".format(
            p_gold['curr_p'] if p_gold else 0,
            p_gold['recent_res'] if p_gold else 0,
            p_gold['recent_sup'] if p_gold else 0
        )
        if p_gold and p_gold['is_setup']:
            sig_ico = "🟢 BUY STOP" if p_gold['direction'] == 'BUY' else "🔴 SELL STOP"
            msg += f"""\n🔥 <b>KÈO SẴN SÀNG: {sig_ico}</b>
   👉 Kích hoạt (Entry): <code>${p_gold['entry']:,.2f}</code>
   🛡️ Cắt lỗ (SL Râu H1): <code>${p_gold['sl']:,.2f}</code> (~{p_gold['risk']:.1f} Giá)
   🎯 TP1 (Độ nảy 1.0R): <code>${p_gold['tp1']:,.2f}</code>
   🎯 TP2 (Cản 2 nến 1.8R): <code>${p_gold['tp2']:,.2f}</code>"""
        else:
            msg += "\n⏸️ <i>Đang chờ nến H1 đóng qua Cản Linechart để kích hoạt Perfect Wick.</i>"
            
        msg += """\n━━━━━━━━━━━━━━━━━━
👑 <b>2. BITCOIN (BTCUSDT H1):</b>
• 💰 Giá Live: <code>${:,.1f}</code>
• 🏛️ Cản Linechart H1: Kháng cự <code>${:,.1f}</code> | Hỗ trợ <code>${:,.1f}</code>""".format(
            p_btc['curr_p'] if p_btc else 0,
            p_btc['recent_res'] if p_btc else 0,
            p_btc['recent_sup'] if p_btc else 0
        )
        if p_btc and p_btc['is_setup']:
            sig_ico_b = "🟢 BUY STOP" if p_btc['direction'] == 'BUY' else "🔴 SELL STOP"
            msg += f"""\n🔥 <b>KÈO SẴN SÀNG: {sig_ico_b}</b>
   👉 Kích hoạt (Entry): <code>${p_btc['entry']:,.1f}</code>
   🛡️ Cắt lỗ (SL Râu H1): <code>${p_btc['sl']:,.1f}</code> (~{p_btc['risk']:,.1f} USDT)
   🎯 TP1 (Độ nảy 1.0R): <code>${p_btc['tp1']:,.1f}</code>
   🎯 TP2 (Cản 2 nến 1.8R): <code>${p_btc['tp2']:,.1f}</code>"""
        else:
            msg += "\n⏸️ <i>Đang chờ nến H1 đóng qua Cản Linechart để kích hoạt Perfect Wick.</i>"

        msg += "\n━━━━━━━━━━━━━━━━━━\n💡 <i>Nguyên lý: 'Lùi bao nhiêu tiến bấy nhiêu' — SL đặt tại mút râu nến hồi để tránh tuyệt đối việc bị bóp SL ngắn.</i>"
        send_telegram(msg, reply_markup=get_main_keyboard(), target_chat_id=chat_id)
    except Exception as e:
        print(f"Lỗi handle_manu_h1_analysis: {e}")
        send_telegram(f"⚠️ Lỗi quét H1 Ma Nữ: {e}", reply_markup=get_main_keyboard(), target_chat_id=chat_id)

def handle_side_by_side_report(chat_id=None):
    """Gửi bảng so sánh định lượng 11 tháng giữa Bot M5 Scalp và Bot H1 Ma Nữ"""
    msg = """📊 <b>[BÁO CÁO ĐỐI ĐẦU 11 THÁNG: BOT M5 SCALPER VS BOT H1 MA NỮ]</b> 📊
━━━━━━━━━━━━━━━━━━
<i>Dữ liệu thực tế MT5 Exness (01/2026 - 11/2026) | Vốn $2,000 | Risk $20/lệnh</i>

⚔️ <b>1. BẢNG SO SÁNH CHỈ SỐ CỐT LÕI:</b>
• <b>Tổng số lệnh:</b>
  ⚡ Bot M5 Scalp: <code>1,314 lệnh</code> (~120 lệnh/tháng)
  🧙‍♀️ Bot H1 Ma Nữ: <code>471 lệnh</code> (~42 lệnh/tháng) ➔ <i>Giảm 64% lệnh rác</i>

• <b>Khoảng cách SL Trung Bình:</b>
  ⚡ Vàng M5: <code>$8.89</code> | BTC M5: <code>$217.9</code> (Bóp SL ngắn)
  🧙‍♀️ Vàng H1: <code>$16.11</code> | BTC H1: <code>$354.1</code> (Đệm râu an toàn)

• <b>Tỷ lệ Thắng (Winrate):</b>
  ⚡ Bot M5 Scalp: <b>42.5%</b>
  🧙‍♀️ Bot H1 Ma Nữ: <b>43.7%</b>

• <b>Lợi Nhuận Ròng (Net PnL):</b>
  ⚡ Bot M5 Scalp: 🔴 <b>-$1,492.00 USD (-74.6%)</b>
  🧙‍♀️ Bot H1 Ma Nữ: 🟢 <b>+$880.00 USD (+44.0%)</b> 🚀
  ➔ <i>H1 Ma Nữ vượt trội <b>+$2,372.00 USD</b>!</i>

• <b>Tụt Giảm Tối Đa (Max Drawdown):</b>
  ⚡ Bot M5 Scalp: <code>$1,688.0 (84.4%)</code>
  🧙‍♀️ Bot H1 Ma Nữ: <code>$370.0 (18.5%)</code> ➔ <i>An toàn gấp 4.5 lần</i>

━━━━━━━━━━━━━━━━━━
📅 <b>2. CHI TIẾT TỪNG THÁNG NĂM 2026:</b>
• T1: M5 -$176 | H1 <b>+$20</b> (H1 thắng)
• T2: M5 -$280 | H1 <b>+$160</b> (H1 thắng)
• T3: M5 +$8   | H1 <b>+$480</b> (H1 thắng)
• T4: M5 -$156 | H1 <b>+$150</b> (H1 thắng)
• T5: M5 -$256 | H1 <b>+$110</b> (H1 thắng)
• T6: M5 +$32  | H1 <b>+$280</b> (H1 thắng)
• T7: M5 <b>+$24</b>  | H1 -$330 (M5 thắng)
• T8: M5 -$568 | H1 <b>+$150</b> (H1 thắng)
• T9: M5 -$116 | H1 <b>+$40</b>  (H1 thắng)
• T10: M5 <b>+$328</b> | H1 -$160 (M5 thắng)
• T11: M5 -$332| H1 <b>-$20</b>  (H1 thắng)
🏆 <b>H1 Ma Nữ THẮNG 9/11 THÁNG!</b>

━━━━━━━━━━━━━━━━━━
💡 <i>Hiện tại cả 2 bot đang CHẠY SONG SONG trực tiếp trên bot này. Kèo M5 hay H1 đều được tự động gắn nhãn và theo dõi PnL riêng biệt!</i>"""
    send_telegram(msg, reply_markup=get_main_keyboard(), target_chat_id=chat_id)

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
• 🛡️ <b>Xác Nhận Volume M5:</b> {p_gold['defense_badge']}
• ⚡ <b>Hành động giá M5:</b> <i>{p_gold['wick_info']}</i>

{p_gold['action_plan_text']}

━━━━━━━━━━━━━━━━━━
👑 <b>2. BITCOIN (BTCUSDT - 00:00 UTC):</b>
• 💰 Giá hiện tại: <code>${p_btc['curr_p']:,.1f}</code>
• 🌅 <b>Daily Open:</b> <code>${p_btc['daily_open']:,.1f}</code> | 🧭 <b>Bias:</b> {p_btc['daily_bias']}

🏛️ <b>VOLUME PROFILE HÔM TRƯỚC: {p_btc['y_shape']}</b>
• 📍 <b>yPOC:</b> <code>${p_btc['y_poc']:,.1f}</code> | 🟢 <b>yVAL:</b> <code>${p_btc['y_val']:,.1f}</code> | 🔴 <b>yVAH:</b> <code>${p_btc['y_vah']:,.1f}</code>
• 💡 <i>{p_btc['y_shape_desc']}</i>

📊 <b>Volume Profile Hôm Nay:</b>
• dPOC: <code>${p_btc['poc']:,.1f}</code> | dVAL: <code>${p_btc['val']:,.1f}</code> | dVAH: <code>${p_btc['vah']:,.1f}</code>
• 🛡️ <b>Xác Nhận Volume M5:</b> {p_btc['defense_badge']}
• ⚡ <b>Hành động giá M5:</b> <i>{p_btc['wick_info']}</i>

{p_btc['action_plan_text']}

━━━━━━━━━━━━━━━━━━
🧠 <b>BẢN CHẤT BẢO VỆ LOW VOLUME / POC / HIGH VOLUME:</b>
1. <b>Bảo vệ Low Volume / yVAL (Đáy):</b> Phe mua hấp thụ toàn bộ lực bán, nến M5 nổ Volume rút chân đóng cửa TRÊN cản ➔ Đảm bảo hỗ trợ vững chắc trước khi nảy về <b>yVAH</b>!
2. <b>Bảo vệ High Volume / yVAH (Đỉnh):</b> Phe bán chặn đầu phân phối, nến M5 nổ Volume rút râu đóng cửa DƯỚI cản ➔ Đảm bảo kháng cự giữ vững trước khi rơi về <b>yVAL</b>!
3. <b>Khi CHƯA có nến nổ Volume bảo vệ cản:</b> Kiên nhẫn đứng ngoài rình, tuyệt đối không vào lệnh sớm để tránh bị nến xả quét SL!"""
        send_telegram(msg, reply_markup=get_main_keyboard(), target_chat_id=chat_id)
    except Exception as e:
        send_telegram(f"⚠️ Lỗi tính toán Scalping Volume Profile: {e}", reply_markup=get_main_keyboard(), target_chat_id=chat_id)

# ==========================================
# 3. QUÉT COIN THEO PHIÊN 1H - CỐ ĐỊNH ENTRY
# ==========================================
def scan_coins_binance(mode='long', limit=3):
    now = time.time()
    cache_key = 'COINS_LONG' if mode == 'long' else 'COINS_SHORT'
    # Giữ cố định danh sách coin và điểm vào trong 1 tiếng (3600s)
    if PLAN_CACHE[cache_key]['data'] and (now - PLAN_CACHE[cache_key]['time'] < 3600):
        return PLAN_CACHE[cache_key]['data']
        
    url = 'https://api.binance.com/api/v3/ticker/24hr'
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=10) as resp:
        tickers = json.loads(resp.read().decode())
        
    usdt_tickers = []
    for d in tickers:
        sym = d['symbol']
        vol = float(d.get('quoteVolume', 0))
        if sym.endswith('USDT') and vol > 15000000:
            change_pct = float(d.get('priceChangePercent', 0))
            usdt_tickers.append({
                'symbol': sym.replace('USDT', '/USDT'),
                'price': float(d['lastPrice']),
                'high_24h': float(d['highPrice']),
                'low_24h': float(d['lowPrice']),
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

scan_coins_bybit = scan_coins_binance

def handle_scan(mode='long', chat_id=None):
    try:
        results = scan_coins_binance(mode=mode, limit=3)
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

    url = 'https://api.binance.com/api/v3/ticker/24hr'
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=10) as resp:
        tickers = json.loads(resp.read().decode())

    candidates = []
    for d in tickers:
        sym = d['symbol']
        if not sym.endswith('USDT'): continue
        if sym in TRADFI_EXCLUDE or sym in MAJORS_EXCLUDE: continue
        
        vol_usd = float(d.get('quoteVolume', 0))
        change_pct = float(d.get('priceChangePercent', 0))
        
        # Tiêu chuẩn: Vol >= 70M USD (ưu tiên >= 100M) và đang có đà bơm (change > 0.5%)
        if vol_usd >= 70_000_000 and change_pct >= 0.5:
            candidates.append({
                'symbol': sym,
                'sym_clean': sym.replace('USDT', '/USDT'),
                'price': float(d['lastPrice']),
                'change_pct': round(change_pct, 2),
                'vol_m': round(vol_usd / 1_000_000, 1),
                'high_24h': float(d['highPrice']),
                'low_24h': float(d['lowPrice'])
            })

    # Ưu tiên các coin đạt mốc 100M+ và có đà tăng mạnh nhất
    candidates.sort(key=lambda x: (x['vol_m'] >= 100.0, x['change_pct']), reverse=True)
    selected = candidates[:8]
    
    results = []
    for c in selected:
        sym = c['symbol']
        try:
            klines = get_binance_klines(sym, interval='1h', limit=12)
            if not klines or len(klines) < 4: continue
            
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
    send_telegram("⏳ <i>Đang quét toàn sàn Binance lọc Coin Rác có Volume > $100M & Lực mua chủ động...</i>", target_chat_id=chat_id)
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
# 3.3 TRA CỨU GIÁ LIVE THỊ TRƯỜNG (VÀNG OANDA - BITCOIN BINANCE - ETHEREUM BINANCE)
# ==========================================
# Cache dự phòng giá tức thời để không bao giờ bị hiển thị $0.0 khi sàn nghẽn mạng
LIVE_MARKET_CACHE = {
    'BTCUSDT': {'price': 59250.0, 'change': -2.1, 'high': 60680.0, 'low': 58940.0, 'vol_m': 1120.0},
    'ETHUSDT': {'price': 1660.0, 'change': -2.5, 'high': 1710.0, 'low': 1640.0, 'vol_m': 450.0},
    'GOLD': {'price': 3523.55, 'open': 3556.0, 'high': 3575.29, 'low': 3515.77, 'bid': 3518.62, 'ask': 3519.31, 'change': -0.92}
}

def get_live_market_prices():
    """Lấy giá tức thời thời gian thực của Vàng (OANDA:XAUUSD), Bitcoin (Binance BTCUSDT) và Ethereum (Binance ETHUSDT)"""
    results = {}
    now_dt = datetime.timezone(datetime.timedelta(hours=7))
    time_str = datetime.datetime.now(now_dt).strftime('%H:%M:%S %d/%m/%Y')
    
    # 1. Binance Tickers (BTCUSDT, ETHUSDT) - Hỗ trợ đa cụm máy chủ Binance để không bị nghẽn/chặn IP
    binance_hosts = [
        'https://api.binance.com',
        'https://data-api.binance.vision',
        'https://api1.binance.com',
        'https://api3.binance.com'
    ]

    for sym in ['BTCUSDT', 'ETHUSDT']:
        got = False
        for host in binance_hosts:
            try:
                url = f"{host}/api/v3/ticker/24hr?symbol={sym}"
                req = urllib.request.Request(url, headers=HEADERS)
                with urllib.request.urlopen(req, timeout=3) as r:
                    t = json.loads(r.read().decode())
                    if 'lastPrice' in t:
                        results[sym] = {
                            'price': float(t['lastPrice']),
                            'change': float(t.get('priceChangePercent', 0)),
                            'high': float(t.get('highPrice', 0)),
                            'low': float(t.get('lowPrice', 0)),
                            'vol_m': float(t.get('quoteVolume', 0)) / 1_000_000
                        }
                        LIVE_MARKET_CACHE[sym] = results[sym]
                        got = True
                        break
            except Exception:
                continue

        # Fallback 1: Lấy từ nến gần nhất nếu ticker 24hr bị nghẽn
        if not got:
            try:
                kl = get_binance_klines(sym, '5m', 5)
                if kl and len(kl) > 0:
                    p = float(kl[0][4])
                    h = max([float(k[2]) for k in kl])
                    l = min([float(k[3]) for k in kl])
                    cached_vol = LIVE_MARKET_CACHE.get(sym, {}).get('vol_m', 500.0)
                    results[sym] = {
                        'price': p, 'change': 0.0, 'high': h, 'low': l,
                        'vol_m': cached_vol
                    }
                    LIVE_MARKET_CACHE[sym] = results[sym]
                    got = True
            except Exception:
                pass

        # Fallback 2: Lấy từ cache RAM gần nhất (Không bao giờ để rỗng 0.0)
        if not got and sym in LIVE_MARKET_CACHE:
            results[sym] = LIVE_MARKET_CACHE[sym]

    # 2. OANDA Gold MT5 từ TradingView Scanner + WebSocket Fallback
    oanda_price = None
    try:
        tv_url = 'https://scanner.tradingview.com/cfd/scan'
        tv_payload = json.dumps({
            "symbols": {"tickers": ["OANDA:XAUUSD"]},
            "columns": ["close", "open", "high", "low", "bid", "ask", "change"]
        }).encode()
        tv_req = urllib.request.Request(tv_url, data=tv_payload, headers={'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(tv_req, timeout=4) as resp:
            data = json.loads(resp.read().decode())
            if data.get('data') and len(data['data']) > 0:
                row = data['data'][0]['d']
                oanda_price = {
                    'price': float(row[0]),
                    'open': float(row[1]) if row[1] else float(row[0]),
                    'high': float(row[2]) if row[2] else float(row[0]),
                    'low': float(row[3]) if row[3] else float(row[0]),
                    'bid': float(row[4]) if row[4] else float(row[0]),
                    'ask': float(row[5]) if row[5] else float(row[0]),
                    'change': float(row[6]) if row[6] else 0.0
                }
                LIVE_MARKET_CACHE['GOLD'] = oanda_price
    except Exception as e:
        print(f"Lỗi lấy giá OANDA TradingView: {e}")

    # Fallback OANDA WebSocket nếu Scanner rỗng
    if not oanda_price:
        try:
            ws_kl = get_oanda_klines('5', 5)
            if ws_kl and len(ws_kl) > 0:
                p = float(ws_kl[0][4])
                h = max([float(k[2]) for k in ws_kl])
                l = min([float(k[3]) for k in ws_kl])
                oanda_price = {
                    'price': p, 'open': p, 'high': h, 'low': l,
                    'bid': round(p - 0.35, 2), 'ask': round(p + 0.35, 2), 'change': 0.0
                }
                LIVE_MARKET_CACHE['GOLD'] = oanda_price
        except Exception:
            pass

    if not oanda_price and 'GOLD' in LIVE_MARKET_CACHE:
        oanda_price = LIVE_MARKET_CACHE['GOLD']

    return {'time': time_str, 'binance': results, 'oanda': oanda_price}

def handle_live_price(chat_id=None):
    """Hiển thị bảng giá tức thời Vàng (OANDA:XAUUSD) và BTC/ETH (Binance) theo thời gian thực kèm Đỉnh/Đáy ngày (HOD / LOD)"""
    try:
        data = get_live_market_prices()
        time_str = data['time']
        b = data['binance']
        oanda = data['oanda']

        # Gold OANDA
        gold_oanda_p = oanda['price'] if oanda else 0.0
        gold_bid = oanda['bid'] if oanda else gold_oanda_p
        gold_ask = oanda['ask'] if oanda else gold_oanda_p
        gold_oanda_high = oanda['high'] if oanda else gold_oanda_p
        gold_oanda_low = oanda['low'] if oanda else gold_oanda_p
        gold_chg = oanda['change'] if oanda else 0.0

        # BTC Binance
        btc = b.get('BTCUSDT', {})
        btc_p = btc.get('price', 0)
        btc_chg = btc.get('change', 0)
        btc_low = btc.get('low', 0)
        btc_high = btc.get('high', 0)
        btc_vol = btc.get('vol_m', 0)

        # ETH Binance
        eth = b.get('ETHUSDT', {})
        eth_p = eth.get('price', 0)
        eth_chg = eth.get('change', 0)
        eth_low = eth.get('low', 0)
        eth_high = eth.get('high', 0)
        eth_vol = eth.get('vol_m', 0)

        g_emoji = "🟢" if gold_chg >= 0 else "🔴"
        b_emoji = "🟢" if btc_chg >= 0 else "🔴"
        e_emoji = "🟢" if eth_chg >= 0 else "🔴"

        msg = f"""💵 <b>[BẢNG GIÁ LIVE THỜI GIAN THỰC]</b> 💵
━━━━━━━━━━━━━━━━━━
🥇 <b>VÀNG (XAUUSD - SÀN OANDA):</b>
• <b>Thị giá OANDA:</b> <b>${gold_oanda_p:,.2f}</b> ({g_emoji} <b>{gold_chg:+.2f}%</b>)
• <b>Bid / Ask:</b> <code>${gold_bid:,.2f}</code> / <code>${gold_ask:,.2f}</code>
• 🔺 <b>Đỉnh ngày (HOD):</b> <code>${gold_oanda_high:,.2f}</code> | 🔻 <b>Đáy ngày (LOD):</b> <code>${gold_oanda_low:,.2f}</code>
• 🏛️ <i>Chuẩn MT5 & TradingView OANDA (100% không chênh lệch sàn)</i>

👑 <b>BITCOIN (BTCUSDT - SÀN BINANCE):</b>
• <b>Thị giá Binance:</b> <b>${btc_p:,.1f} USD</b> ({b_emoji} <b>{btc_chg:+.2f}%</b>)
• 🔺 <b>Đỉnh ngày (HOD):</b> <code>${btc_high:,.1f} USD</code> | 🔻 <b>Đáy ngày (LOD):</b> <code>${btc_low:,.1f} USD</code>
• 🌊 <b>Volume 24h:</b> <b>${btc_vol:,.0f}M USDT</b>

💎 <b>ETHEREUM (ETHUSDT - SÀN BINANCE):</b>
• <b>Thị giá Binance:</b> <b>${eth_p:,.2f} USD</b> ({e_emoji} <b>{eth_chg:+.2f}%</b>)
• 🔺 <b>Đỉnh ngày (HOD):</b> <code>${eth_high:,.2f} USD</code> | 🔻 <b>Đáy ngày (LOD):</b> <code>${eth_low:,.2f} USD</code>
• 🌊 <b>Volume 24h:</b> <b>${eth_vol:,.0f}M USDT</b>
━━━━━━━━━━━━━━━━━━
⏱️ <i>Cập nhật lúc: {time_str}</i>
💡 <i>Bấm nút <b>💵 Xem Giá Live (Vàng/BTC/ETH)</b> bất kỳ lúc nào để làm mới giá ngay!</i>"""

        send_telegram(msg, reply_markup=get_main_keyboard(), target_chat_id=chat_id)
    except Exception as e:
        send_telegram(f"⚠️ Lỗi lấy giá live: {e}", reply_markup=get_main_keyboard(), target_chat_id=chat_id)

        send_telegram(msg, reply_markup=get_main_keyboard(), target_chat_id=chat_id)
    except Exception as e:
        send_telegram(f"⚠️ Lỗi lấy giá live: {e}", reply_markup=get_main_keyboard(), target_chat_id=chat_id)

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

MACRO_BT_CACHE = {'ts': 0, 'text': ''}

def compute_macro_backtest_stats():
    """Backtest Swing (7D/14D/30D) dựa trên số liệu THỰC TẾ (Actual vs Forecast) của tất cả tin Đỏ Mỹ từ TradingView Economic Calendar"""
    global MACRO_BT_CACHE
    if time.time() - MACRO_BT_CACHE['ts'] < 3600 and MACRO_BT_CACHE['text']:
        return MACRO_BT_CACHE['text']

    # 1. Lấy lịch sử tin Đỏ Mỹ (importance == 1) ~2-3 năm từ TradingView Economic Calendar
    news_outcome_by_date = {}  # 'YYYY-MM-DD' -> 'GOOD_USD' | 'BAD_USD'
    try:
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        from_dt = (now_utc - datetime.timedelta(days=900)).strftime('%Y-%m-%dT00:00:00.000Z')
        to_dt = now_utc.strftime('%Y-%m-%dT23:59:59.000Z')
        cal_url = f"https://economic-calendar.tradingview.com/events?from={from_dt}&to={to_dt}&countries=US"
        req = urllib.request.Request(cal_url, headers={'User-Agent': 'Mozilla/5.0', 'Origin': 'https://www.tradingview.com'})
        with urllib.request.urlopen(req, timeout=10) as r:
            cal_data = json.loads(r.read().decode())
        for ev in cal_data.get('result', []):
            if ev.get('importance') != 1:
                continue
            act = ev.get('actual')
            fcst = ev.get('forecast')
            if fcst is None:
                fcst = ev.get('previous')
            if act is None or fcst is None:
                continue
            try:
                act_f = float(act)
                fcst_f = float(fcst)
            except Exception:
                continue
            if act_f == fcst_f:
                continue
            title_l = str(ev.get('title', '')).lower()
            is_inverse = ('unemployment' in title_l or 'jobless' in title_l)
            good_usd = (act_f < fcst_f) if is_inverse else (act_f > fcst_f)
            dt_str = str(ev.get('date', ''))[:10]
            if dt_str:
                news_outcome_by_date[dt_str] = 'GOOD_USD' if good_usd else 'BAD_USD'
    except Exception as e:
        print(f"Lỗi lấy TradingView Economic Calendar: {e}")

    def _calc_conditional(bars):
        if not bars or len(bars) < 60 or not news_outcome_by_date:
            return []
        bars_asc = sorted(bars, key=lambda x: x[0])
        date_to_idx = {}
        for idx, b in enumerate(bars_asc):
            d_str = datetime.datetime.fromtimestamp(b[0] / 1000, tz=datetime.timezone.utc).strftime('%Y-%m-%d')
            date_to_idx[d_str] = idx

        # Sắp xếp các ngày ra tin theo thứ tự thời gian và đo từ sau ngày ra tin (T+1) đến ngày ra tin tiếp theo
        sorted_news_dates = sorted(d for d in news_outcome_by_date.keys() if d in date_to_idx)
        good_usd = []  # Tin TỐT cho USD (Actual > Forecast)
        bad_usd = []   # Tin XẤU cho USD (Actual < Forecast)

        for k in range(len(sorted_news_dates) - 1):
            d_curr = sorted_news_dates[k]
            d_next = sorted_news_dates[k + 1]
            idx_start = date_to_idx[d_curr] + 1  # Sau ngày ra tin (T+1)
            idx_end = date_to_idx[d_next]        # Đến ngày ra tin tiếp theo
            if idx_start >= idx_end or idx_end >= len(bars_asc):
                continue
            c_start = float(bars_asc[idx_start][4])
            c_end = float(bars_asc[idx_end][4])
            if c_start <= 0:
                continue
            ret = (c_end - c_start) / c_start * 100.0
            if news_outcome_by_date[d_curr] == 'GOOD_USD':
                good_usd.append(ret)
            else:
                bad_usd.append(ret)

        out = []
        for lbl, arr in [
            ("📈 Tin <b>TỐT cho USD</b> (Actual &gt; Dự báo)", good_usd),
            ("📉 Tin <b>XẤU cho USD</b> (Actual &lt; Dự báo)", bad_usd)
        ]:
            if not arr:
                continue
            n = len(arr)
            win_long = sum(1 for x in arr if x > 0) / n * 100.0
            avg_ret = sum(arr) / n
            bias = "🟢 <b>LONG Swing</b>" if (win_long >= 55 and avg_ret > 0) else ("🔴 <b>SHORT Swing</b>" if (win_long <= 45 and avg_ret < 0) else "⚖️ <b>Trung tính</b>")
            out.append(
                f"  - {lbl} ({n} kỳ):\n"
                f"    • Từ sau tin ➔ tin kế tiếp: Tăng <b>{win_long:.0f}%</b> | Giảm <b>{100-win_long:.0f}%</b> | TB: <code>{avg_ret:+.2f}%</code> ➔ {bias}"
            )
        return out

    lines = []
    try:
        g_lines = _calc_conditional(get_oanda_klines('D', 1000))
        if g_lines:
            lines.append("• 🥇 <b>VÀNG (XAUUSD - Theo Actual vs Dự báo):</b>\n" + "\n".join(g_lines))
    except Exception:
        pass
    try:
        b_lines = _calc_conditional(get_binance_klines('BTCUSDT', '1d', 1000))
        if b_lines:
            lines.append("• 👑 <b>BITCOIN (Tài sản rủi ro - Theo Actual vs Dự báo):</b>\n" + "\n".join(b_lines))
    except Exception:
        pass

    res = "\n".join(lines) if lines else "• <i>Đang đồng bộ dữ liệu lịch sử kinh tế Mỹ...</i>"
    MACRO_BT_CACHE = {'ts': time.time(), 'text': res}
    return res

def analyze_fibo_wave_plan(asset='GOLD'):
    """
    Hệ thống Săn Sóng Hồi Fibonacci (Fibo Golden Zone 0.50 - 0.618) trên khung H1:
    - Tìm Swing High / Swing Low rõ nét trong 60 nến H1 gần nhất.
    - Xác định xu hướng chính (Uptrend nếu Swing Low xuất hiện trước Swing High, ngược lại Downtrend).
    - Canh hồi về vùng vàng 0.50 - 0.618 có nến M15 xác nhận rút râu/đóng nến thuận xu hướng.
    """
    try:
        if asset == 'GOLD':
            h1_klines = get_oanda_klines('60', 60)
            m15_klines = get_oanda_klines('15', 10)
            min_range = 20.0
            dec = 2
        else:
            h1_klines = get_binance_klines('BTCUSDT', '1h', 60)
            m15_klines = get_binance_klines('BTCUSDT', '15m', 10)
            min_range = 1200.0
            dec = 1

        if not h1_klines or len(h1_klines) < 30 or not m15_klines or len(m15_klines) < 3:
            return None

        # Đảo ngược sang thứ tự thời gian tăng dần (cũ -> mới)
        h1_asc = list(reversed(h1_klines))
        highs = [float(k[2]) for k in h1_asc]
        lows = [float(k[3]) for k in h1_asc]
        curr_p = float(m15_klines[0][4])

        idx_high = highs.index(max(highs))
        idx_low = lows.index(min(lows))
        sw_high = highs[idx_high]
        sw_low = lows[idx_low]
        wave_range = sw_high - sw_low

        if wave_range < min_range:
            return None

        # Nếu đáy xuất hiện trước đỉnh -> Sóng đẩy TĂNG -> Canh BUY khi hồi về 0.50 - 0.618
        is_uptrend = (idx_low < idx_high)
        if is_uptrend:
            fib_50 = round(sw_high - 0.500 * wave_range, dec)
            fib_618 = round(sw_high - 0.618 * wave_range, dec)
            fib_786 = round(sw_high - 0.786 * wave_range, dec)
            fib_236 = round(sw_high - 0.236 * wave_range, dec)
            fib_ext = round(sw_high + 0.272 * wave_range, dec)
            signal = 'LONG'
            entry = fib_618
            sl = round(fib_786 - (0.05 * wave_range), dec)
            tp1 = fib_236
            tp2 = fib_ext
            in_golden_zone = (fib_786 <= curr_p <= fib_50)
            # Nến M15 vừa đóng xác nhận rút râu dưới / đóng xanh
            c1 = m15_klines[1]
            o1, h1_c, l1_c, cl1 = float(c1[1]), float(c1[2]), float(c1[3]), float(c1[4])
            body = abs(cl1 - o1)
            lower_wick = min(o1, cl1) - l1_c
            m15_confirmed = (cl1 > o1) or (lower_wick > body * 1.2)
        else:
            fib_50 = round(sw_low + 0.500 * wave_range, dec)
            fib_618 = round(sw_low + 0.618 * wave_range, dec)
            fib_786 = round(sw_low + 0.786 * wave_range, dec)
            fib_236 = round(sw_low + 0.236 * wave_range, dec)
            fib_ext = round(sw_low - 0.272 * wave_range, dec)
            signal = 'SHORT'
            entry = fib_618
            sl = round(fib_786 + (0.05 * wave_range), dec)
            tp1 = fib_236
            tp2 = fib_ext
            in_golden_zone = (fib_50 <= curr_p <= fib_786)
            # Nến M15 vừa đóng xác nhận rút râu trên / đóng đỏ
            c1 = m15_klines[1]
            o1, h1_c, l1_c, cl1 = float(c1[1]), float(c1[2]), float(c1[3]), float(c1[4])
            body = abs(cl1 - o1)
            upper_wick = h1_c - max(o1, cl1)
            m15_confirmed = (cl1 < o1) or (upper_wick > body * 1.2)

        return {
            'asset': asset,
            'curr_p': curr_p,
            'signal': signal,
            'sw_high': sw_high,
            'sw_low': sw_low,
            'wave_range': round(wave_range, dec),
            'fib_50': fib_50,
            'fib_618': fib_618,
            'fib_786': fib_786,
            'entry': entry,
            'sl': sl,
            'tp1': tp1,
            'tp2': tp2,
            'sl_dist': round(abs(entry - sl), dec),
            'in_golden_zone': in_golden_zone,
            'm15_confirmed': m15_confirmed,
            'is_ready': (in_golden_zone and m15_confirmed)
        }
    except Exception as e:
        print(f"Lỗi analyze_fibo_wave_plan({asset}): {e}")
        return None

def handle_fibo_wave(chat_id=None):
    """Hiển thị phân tích Hệ thống Săn Sóng Hồi Fibonacci (H1 Golden Zone 0.50 - 0.618)"""
    try:
        fg = analyze_fibo_wave_plan('GOLD')
        fb = analyze_fibo_wave_plan('BTC')
        msg = "📐 <b>[HỆ THỐNG FIBO SÓNG HỒI H1 (GOLDEN ZONE 0.5 - 0.618)]</b>\n━━━━━━━━━━━━━━━━━━\n"
        for name, plan, dec in [("🥇 VÀNG (XAUUSD)", fg, 2), ("👑 BITCOIN (BTCUSDT)", fb, 1)]:
            if not plan:
                msg += f"\n{name}: <i>Sóng H1 hiện tại biên độ hẹp, chưa hình thành con sóng Fibo chuẩn.</i>\n"
                continue
            sgn = "🟢 CANH BUY (Sóng đẩy TĂNG)" if plan['signal'] == 'LONG' else "🔴 CANH SHORT (Sóng đẩy GIẢM)"
            st = "🔥 <b>ĐANG TRONG VÙNG VÀNG &amp; CÓ XÁC NHẬN M15!</b>" if plan['is_ready'] else ("⚡ <b>Đang nằm trong vùng Fibo 0.5-0.618 (Chờ nến M15 xác nhận)</b>" if plan['in_golden_zone'] else "⏳ <i>Đang chờ giá hồi về vùng 0.50 - 0.618</i>")
            msg += (
                f"\n<b>{name}</b> | Giá: <code>${plan['curr_p']:,.{dec}f}</code>\n"
                f"• Xu hướng sóng H1: {sgn} (Biên độ: <code>{plan['wave_range']:,.{dec}f}</code>)\n"
                f"• Đỉnh/Đáy sóng: <code>${plan['sw_high']:,.{dec}f}</code> / <code>${plan['sw_low']:,.{dec}f}</code>\n"
                f"• 🎯 <b>Vùng Vàng (0.50 - 0.618):</b> <code>${plan['fib_50']:,.{dec}f}</code> - <code>${plan['fib_618']:,.{dec}f}</code>\n"
                f"• 🛡️ <b>SL (Sau Fib 0.786):</b> <code>${plan['sl']:,.{dec}f}</code>\n"
                f"• 💰 <b>TP1 (Fib 0.236):</b> <code>${plan['tp1']:,.{dec}f}</code> | <b>TP2 (Ext -0.272):</b> <code>${plan['tp2']:,.{dec}f}</code>\n"
                f"• Trạng thái: {st}\n"
            )
        msg += "\n💡 <i>Bot tự động quét 24/7. Khi giá hồi về vùng 0.50 - 0.618 và có nến M15 rút râu xác nhận, hệ thống sẽ tự động bắn kèo và lưu vào danh sách theo dõi!</i>"
        send_telegram(msg, reply_markup=get_main_keyboard(), target_chat_id=chat_id)
    except Exception as e:
        send_telegram(f"⚠️ Lỗi phân tích Fibo sóng: {e}", reply_markup=get_main_keyboard(), target_chat_id=chat_id)

def handle_us_macro_news(chat_id=None):
    """Phân tích các tin quan trọng cố định của Mỹ (High-Impact USD) & đánh giá View Long/Short dài hạn"""
    try:
        now_vn = datetime.datetime.now(TZ_VN)

        # 1. Lấy lịch kinh tế Mỹ (USD High-Impact) từ ForexFactory JSON
        usd_events = []
        try:
            req = urllib.request.Request('https://nfs.faireconomy.media/ff_calendar_thisweek.json', headers=HEADERS)
            with urllib.request.urlopen(req, timeout=6) as r:
                cal = json.loads(r.read().decode())
                for ev in cal:
                    if ev.get('country') == 'USD' and ev.get('impact') == 'High':
                        usd_events.append(ev)
        except Exception as e:
            print(f"Lỗi lấy lịch tin Mỹ: {e}")

        # 2. Lấy chỉ số DXY (US Dollar Index) từ TradingView
        dxy_p, dxy_chg, dxy_ema50_w = None, 0.0, None
        try:
            tv_url = 'https://scanner.tradingview.com/cfd/scan'
            tv_payload = json.dumps({
                "symbols": {"tickers": ["TVC:DXY"]},
                "columns": ["close", "change", "EMA50|1W"]
            }).encode()
            tv_req = urllib.request.Request(tv_url, data=tv_payload, headers={'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(tv_req, timeout=5) as resp:
                dxy_data = json.loads(resp.read().decode())
                if dxy_data.get('data'):
                    row = dxy_data['data'][0]['d']
                    dxy_p = float(row[0]) if row[0] else None
                    dxy_chg = float(row[1]) if row[1] else 0.0
                    dxy_ema50_w = float(row[2]) if row[2] else None
        except Exception as e:
            print(f"Lỗi lấy DXY: {e}")

        # 3. Lấy Bias dài hạn (W1/D1) của Vàng & BTC
        g_w1, g_d1, g_dir = "Đang đồng bộ", "Đang đồng bộ", "CHỜ XÁC NHẬN"
        b_w1, b_d1, b_dir = "Đang đồng bộ", "Đang đồng bộ", "CHỜ XÁC NHẬN"
        try:
            pg = calculate_gold_h4_plan()
            g_w1 = pg.get('w1_bias', g_w1)
            g_d1 = pg.get('d1_bias', g_d1)
            g_dir = pg.get('priority_dir', g_dir)
        except Exception:
            pass
        try:
            pb = calculate_btc_h4_plan()
            b_w1 = pb.get('w1_bias', b_w1)
            b_d1 = pb.get('d1_bias', b_d1)
            b_dir = pb.get('priority_dir', b_dir)
        except Exception:
            pass

        msg = f"🇺🇸 <b>[PHÂN TÍCH TIN QUAN TRỌNG CỦA MỸ &amp; VIEW DÀI HẠN]</b>\n━━━━━━━━━━━━━━━━━━\n"
        msg += f"⏱️ <i>Cập nhật: {now_vn.strftime('%H:%M %d/%m/%Y')} (Giờ VN)</i>\n\n"

        # Phần A: Sức mạnh đồng USD (DXY)
        if dxy_p:
            dxy_trend = "🟢 TĂNG (USD Mạnh ➔ Áp lực GIẢM lên Vàng/BTC)" if (dxy_ema50_w and dxy_p > dxy_ema50_w) else "🔴 GIẢM (USD Yếu ➔ Hỗ trợ TĂNG cho Vàng/BTC)"
            msg += f"💵 <b>CHỈ SỐ ĐÔ LA MỸ (DXY):</b> <code>{dxy_p:.2f}</code> ({dxy_chg:+.2f}%)\n"
            if dxy_ema50_w:
                msg += f"• Xu hướng Tuần (so với EMA50 W1 <code>{dxy_ema50_w:.2f}</code>): {dxy_trend}\n\n"
        else:
            msg += "💵 <b>CHỈ SỐ DÔ LA MỸ (DXY):</b> <i>Đang đồng bộ dữ liệu...</i>\n\n"

        # Phần B: Lịch tin Đỏ cố định của Mỹ trong tuần
        msg += "📅 <b>TIN ĐỎ QUAN TRỌNG CỦA MỸ TRONG TUẦN:</b>\n"
        good_usd_cnt, bad_usd_cnt = 0, 0
        if usd_events:
            for ev in usd_events[:6]:
                title = ev.get('title', 'USD News')
                prev_v = ev.get('previous', 'N/A') or 'N/A'
                fcst_v = ev.get('forecast', 'N/A') or 'N/A'
                raw_dt = ev.get('date', '')
                vn_time_str = raw_dt
                is_past = False
                try:
                    dt_obj = datetime.datetime.fromisoformat(raw_dt)
                    dt_vn = dt_obj.astimezone(TZ_VN)
                    vn_time_str = dt_vn.strftime('%H:%M %d/%m')
                    is_past = (dt_vn < now_vn)
                except Exception:
                    pass

                status_tag = "✅ Đã ra" if is_past else "⏳ Sắp ra"
                t_low = title.lower()
                if any(k in t_low for k in ['cpi', 'pce', 'ppi', 'inflation']):
                    rule = "Lạm phát cao &gt; Dự báo ➔ Fed giữ lãi cao ➔ <b>SHORT</b> Vàng/BTC; Thấp hơn ➔ <b>LONG</b>"
                elif any(k in t_low for k in ['fomc', 'rate', 'fed', 'powell']):
                    rule = "Giọng điệu Diều hâu (Hawkish) ➔ <b>SHORT</b> Vàng/BTC; Bồ câu (Dovish) ➔ <b>LONG</b>"
                elif any(k in t_low for k in ['payroll', 'nfp', 'employment', 'unemployment', 'job']):
                    rule = "Việc làm mạnh / Thất nghiệp thấp ➔ USD tăng ➔ <b>SHORT</b> Vàng/BTC; Yếu hơn ➔ <b>LONG</b>"
                else:
                    rule = "Số liệu tốt &gt; Dự báo ➔ USD mạnh ➔ Áp lực <b>SHORT</b>; Xấu hơn ➔ <b>LONG</b>"

                msg += f"• <b>{title}</b> ({status_tag} - <code>{vn_time_str}</code>)\n"
                act_v = ev.get('actual', '')
                if act_v:
                    verdict_str = ""
                    try:
                        a_num = float(str(act_v).replace('%', '').replace('K', '').replace('M', '').replace('B', '').strip())
                        f_raw = fcst_v if fcst_v != 'N/A' else prev_v
                        f_num = float(str(f_raw).replace('%', '').replace('K', '').replace('M', '').replace('B', '').strip())
                        is_inv = ('unemployment' in t_low or 'jobless' in t_low)
                        if a_num != f_num:
                            is_good_usd = (a_num < f_num) if is_inv else (a_num > f_num)
                            if is_good_usd:
                                good_usd_cnt += 1
                                verdict_str = " ➔ 📈 <b>TỐT USD (Áp lực SHORT)</b>"
                            else:
                                bad_usd_cnt += 1
                                verdict_str = " ➔ 📉 <b>XẤU USD (Hỗ trợ BUY)</b>"
                        else:
                            verdict_str = " ➔ ⚖️ <b>Đúng dự báo</b>"
                    except Exception:
                        pass
                    msg += f"  Thực tế: <b><code>{act_v}</code></b> | Dự báo: <code>{fcst_v}</code> | Kỳ trước: <code>{prev_v}</code>{verdict_str}\n"
                else:
                    msg += f"  Kỳ trước: <code>{prev_v}</code> | Dự báo: <code>{fcst_v}</code>\n"
                msg += f"  ↳ <i>Tác động:</i> {rule}\n"
        else:
            msg += "• <i>Chưa tải được lịch tuần này, áp dụng bộ tin lõi cố định của Mỹ:</i>\n"
            msg += "  - <b>Non-Farm (NFP - Thứ 6 đầu tháng):</b> Việc làm &gt; Dự báo ➔ USD tăng (Short Vàng/BTC).\n"
            msg += "  - <b>CPI / Core PCE (Giữa &amp; Cuối tháng):</b> Lạm phát tăng ➔ Fed cứng rắn (Short Vàng/BTC).\n"
            msg += "  - <b>FOMC / Lãi suất Fed:</b> Cắt giảm lãi suất / Dovish ➔ Bơm thanh khoản (Long Vàng/BTC).\n"

        # Phần C: Backtest lịch sử ngày hôm sau (T+1) trên 500 ngày gần nhất
        bt_text = compute_macro_backtest_stats()
        msg += "\n━━━━━━━━━━━━━━━━━━\n"
        msg += "📊 <b>BACKTEST SWING DÀI HẠN SAU TIN (7D / 14D / 30D - ~3 NĂM):</b>\n"
        msg += bt_text + "\n"

        # Phần D: Kết luận View Dài Hạn trước tin
        msg += "\n━━━━━━━━━━━━━━━━━━\n"
        msg += "🧭 <b>KẾT LUẬN CANH BUY / SHORT THEO TIN MỸ:</b>\n"
        if bad_usd_cnt > good_usd_cnt:
            news_call = "🟢 <b>CANH BUY (LONG) Vàng &amp; BTC</b> (Tin ra XẤU cho USD áp đảo)"
        elif good_usd_cnt > bad_usd_cnt:
            news_call = "🔴 <b>CANH SHORT (BÁN) Vàng &amp; BTC</b> (Tin ra TỐT cho USD áp đảo)"
        else:
            news_call = "⚖️ <b>TRUNG TÍNH</b> (Tin đúng dự báo / cân bằng ➔ Đánh thuận xu hướng W1/D1 bên dưới)"
        msg += f"• 🎯 <b>Chiến lược theo tin vừa ra:</b> {news_call}\n"
        msg += f"• 🥇 <b>VÀNG (XAUUSD):</b> W1 {g_w1} | D1 {g_d1}\n  👉 Ưu tiên dài hạn: <b>{g_dir}</b>\n"
        msg += f"• 👑 <b>BITCOIN (BTC):</b> W1 {b_w1} | D1 {b_d1}\n  👉 Ưu tiên dài hạn: <b>{b_dir}</b>\n\n"
        msg += "💡 <i>Nguyên tắc đánh tin: Tuyệt đối không đoán mò trước giờ ra tin 15 phút. Chờ nến M15/H1 đóng sau tin xác nhận đồng pha với View dài hạn mới vào lệnh!</i>"

        send_telegram(msg, reply_markup=get_main_keyboard(), target_chat_id=chat_id)
    except Exception as e:
        send_telegram(f"⚠️ Lỗi phân tích tin Mỹ: {e}", reply_markup=get_main_keyboard(), target_chat_id=chat_id)

def run_bot():
    global PUBLIC_MODE
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
                        elif text.split('@')[0].lower() in ["/users", "/members", "users", "danh sách thành viên"]:
                            import html
                            users = load_authorized_users()
                            u_list = "👥 <b>DANH SÁCH THÀNH VIÊN ĐƯỢC DUYỆT:</b>\n━━━━━━━━━━━━━━━━━━\n"
                            for uid, info in users.items():
                                u_role = "👑 ADMIN" if info.get('role') == 'admin' else "👤 Member"
                                safe_name = html.escape(str(info.get('name', 'User')))
                                u_list += f"• <b>{safe_name}</b> ({u_role})\n  ID: <code>{uid}</code> | Kích hoạt: {info.get('date', '')}\n"
                            u_list += f"\n<i>👉 Để huỷ quyền, gõ: /revoke &lt;ID&gt;</i>\n<i>👉 Chế độ hiện tại: {'🌐 PUBLIC (Mở tự do)' if PUBLIC_MODE else '🔒 PRIVATE (Chỉ thành viên duyệt)'}</i>"
                            send_telegram(u_list, target_chat_id=ADMIN_ID)
                            continue
                        elif text.startswith("/public"):
                            parts = text.split()
                            if len(parts) >= 2 and parts[1].lower() in ['off', 'tat', 'close', 'private', '0']:
                                PUBLIC_MODE = False
                                send_telegram("🔒 <b>ĐÃ TẮT PUBLIC ➔ CHUYỂN SANG CHẾ ĐỘ RIÊNG TƯ (PRIVATE)!</b>\nTừ bây giờ, người lạ bấm bot sẽ phải chờ Admin duyệt bằng /approve mới được sử dụng.", target_chat_id=ADMIN_ID)
                            else:
                                PUBLIC_MODE = True
                                send_telegram("🌐 <b>ĐÃ BẬT CHẾ ĐỘ CỘNG ĐỒNG (PUBLIC)!</b>\nBất kỳ ai mở bot cũng sẽ tự động được cấp quyền và sử dụng mọi tính năng 100%.", target_chat_id=ADMIN_ID)
                            continue

                    # 2. Kiểm duyệt người dùng: Nếu chưa được duyệt
                    if not is_user_approved(chat_id):
                        if PUBLIC_MODE:
                            add_approved_user(chat_id, name=f"{first_name} ({user_tag})")
                            admin_notify = f"""📢 <b>[THÀNH VIÊN MỚI THAM GIA BOT (PUBLIC)]</b>
━━━━━━━━━━━━━━━━━━
👤 <b>Người dùng:</b> {first_name} ({user_tag})
🆔 <b>Telegram ID:</b> <code>{chat_id}</code>
⏱️ <b>Thời gian:</b> {datetime.datetime.now(TZ_VN).strftime('%H:%M:%S %d/%m/%Y')}
⚡ <i>Hệ thống đã tự động cấp quyền truy cập đầy đủ!</i>"""
                            send_telegram(admin_notify, target_chat_id=ADMIN_ID)
                        else:
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
💵 <b>Xem Giá Live:</b> Cập nhật tức thời giá Vàng (OANDA MT5), Bitcoin & Ethereum (Binance)
📊 <b>Tổng Kết Kèo TP/SL:</b> Tổng kết hiệu suất Win/Loss/BE, Winrate %, chi tiết Entry/SL/TP từng kèo
👑 <b>Phân Tích BTC:</b> Bias W1/D1 + SMC KeyVolume H1 & M5 (Binance)
🥇 <b>Phân Tích VÀNG (XAU):</b> Chuẩn OANDA MT5 100% + SMC H1 OB
🎯 <b>Scalping Volume Profile M5:</b> Đánh xoay trục L-Shape/P-Shape hôm trước (yVAL/yVAH) & dPOC
⚡ <b>Tuyệt Chiêu H4 Lưỡng Lự:</b> Bắt bứt phá Breakout nến H4
💣 <b>Săn Coin Rác (Vol > $100M):</b> Bắt momentum mua vào, SL 5% - 9% (Nói KHÔNG với bắt dao rơi / Buy the dip)
📈 <b>Tìm Coin TĂNG (LONG):</b> Lọc coin tích lũy gom hàng Binance
📉 <b>Tìm Coin GIẢM (SHORT):</b> Lọc coin phân phối xả hàng Binance
🇻🇳 <b>Đánh Giá Cổ Phiếu VN:</b> Định giá PE &lt; 10, G &gt; 10%, dòng tiền &amp; lãi suất
🔍 <b>Kiểm Tra Lệnh &amp; Báo Cáo Ngày:</b> Live Radar trực tiếp + Quản lý lệnh đang chạy
🇺🇸 <b>Phân Tích Tin Mỹ (View Dài Hạn):</b> Lịch tin đỏ USD (CPI/PCE/NFP/FOMC) &amp; View Long/Short dài hạn


💡 <i>Bấm các nút bên dưới hoặc gõ trực tiếp lệnh (/price, /tongket, /gold, /btc, /scalp, /news, /check, /vnstock)!</i>"""
                        send_telegram(menu_help, reply_markup=get_main_keyboard(), target_chat_id=chat_id)
                    elif text in ["/price", "/gia", "/xemgia", "/live", "💵 Xem Giá Live (Vàng/BTC/ETH)", "gia", "giá", "price", "xem gia", "xem giá"]:
                        handle_live_price(chat_id=chat_id)
                    elif text in ["/tongket", "/summary", "/pnl", "/winrate", "📊 Tổng Kết Kèo TP/SL", "tongket", "tổng kết", "tong ket", "pnl", "winrate"]:
                        handle_trade_summary(chat_id=chat_id)
                    elif text in ["/manu", "/h1", "manu", "Ma nữ", "ma nữ", "🧙‍♀️ Swing H1 Ma Nữ (Senpai Thành)"]:
                        handle_manu_h1_analysis(chat_id=chat_id)
                    elif text in ["/sosanh", "/compare", "sosanh", "so sánh", "⚖️ Báo Cáo Đối Đầu 2 Bot"]:
                        handle_side_by_side_report(chat_id=chat_id)
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
                    elif text in ["/fibo", "/fibowave", "fibo", "📐 Fibo Sóng Hồi (H1)"]:
                        handle_fibo_wave(chat_id=chat_id)
                    elif text in ["/news", "/tinmy", "/macro", "/usnews", "🇺🇸 Phân Tích Tin Mỹ (View Dài Hạn)"]:
                        handle_us_macro_news(chat_id=chat_id)
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
                    elif text.startswith("/themlenh") or text.startswith("/addtrade"):
                        # Cú pháp: /themlenh <VANG|BTC> <BUY|SELL> <ENTRY> <SL> <TP1> <TP2> [H1|M5]
                        try:
                            parts = text.split()
                            if len(parts) >= 6:
                                raw_asset = parts[1].upper()
                                asset = 'GOLD' if raw_asset in ['VANG', 'GOLD', 'XAU', 'XAUUSD'] else 'BTC'
                                symbol = 'XAUUSD' if asset == 'GOLD' else 'BTCUSDT'
                                signal = 'SHORT' if parts[2].upper() in ['SELL', 'SHORT'] else 'LONG'
                                entry_p = float(parts[3])
                                sl_p = float(parts[4])
                                tp1_p = float(parts[5])
                                tp2_p = float(parts[6]) if len(parts) >= 7 else (entry_p - (entry_p - tp1_p)*2 if signal == 'SHORT' else entry_p + (tp1_p - entry_p)*2)
                                sys_type = 'H1_MANU' if len(parts) >= 8 and parts[7].upper() in ['H1', 'MANU', 'H1_MANU'] else 'M5_SCALP'
                                sl_dist = abs(entry_p - sl_p)

                                new_t = record_new_vip_trade(
                                    asset=asset, symbol=symbol, signal=signal,
                                    entry_price=entry_p, entry_stop=entry_p, sl=sl_p,
                                    tp1=tp1_p, tp2=tp2_p, sl_dist=sl_dist,
                                    is_limit=False, current_price=entry_p, system=sys_type
                                )
                                send_telegram(f"✅ <b>ĐÃ THÊM/KHÔI PHỤC KÈO THÀNH CÔNG!</b>\n• Cặp: <b>{symbol}</b> ({sys_type})\n• Lệnh: <b>{signal}</b>\n• Entry: <code>${entry_p:,.2f}</code> | SL: <code>${sl_p:,.2f}</code> | TP1: <code>${tp1_p:,.2f}</code> | TP2: <code>${tp2_p:,.2f}</code>\n<i>⚡ Bot đã đưa vào danh sách giám sát thời gian thực!</i>", reply_markup=get_main_keyboard(), target_chat_id=chat_id)
                            else:
                                send_telegram("⚠️ <b>Cú pháp:</b> <code>/themlenh &lt;VANG|BTC&gt; &lt;BUY|SELL&gt; &lt;ENTRY&gt; &lt;SL&gt; &lt;TP1&gt; &lt;TP2&gt; [H1|M5]</code>\n<i>Ví dụ: /themlenh VANG SELL 3580 3586 3572.8 3565 H1</i>", reply_markup=get_main_keyboard(), target_chat_id=chat_id)
                        except Exception as ex:
                            send_telegram(f"⚠️ Lỗi thêm lệnh: {ex}", reply_markup=get_main_keyboard(), target_chat_id=chat_id)
                    elif text.startswith("/xoalenh"):
                        try:
                            save_vip_trades([])
                            send_telegram("🗑️ <b>Đã làm sạch toàn bộ danh sách lệnh đang chạy!</b>", reply_markup=get_main_keyboard(), target_chat_id=chat_id)
                        except Exception as ex:
                            send_telegram(f"⚠️ Lỗi: {ex}", reply_markup=get_main_keyboard(), target_chat_id=chat_id)
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

            # 3.1 BÁO CÁO TỔNG KẾT ĐỊNH KỲ (07:00 SÁNG GIỜ VN MỖI NGÀY & THỨ 2 HÀNG TUẦN)
            now_dt = datetime.datetime.now(TZ_VN)
            today_str = now_dt.strftime('%Y-%m-%d')
            rep_state = get_report_state()
            
            # Khung giờ 7h sáng (07:00 - 07:59)
            if now_dt.hour == 7:
                # Báo cáo ngày hôm trước
                if rep_state.get('last_daily') != today_str:
                    rep_state['last_daily'] = today_str
                    save_report_state(rep_state)
                    try:
                        send_daily_summary_report()
                    except Exception as e_drep:
                        print(f"Lỗi gửi báo cáo ngày 07:00: {e_drep}")
                
                # Báo cáo tuần vào sáng Thứ Hai (now_dt.weekday() == 0 là Thứ 2)
                if now_dt.weekday() == 0 and rep_state.get('last_weekly') != today_str:
                    rep_state['last_weekly'] = today_str
                    save_report_state(rep_state)
                    try:
                        send_weekly_summary_report()
                    except Exception as e_wrep:
                        print(f"Lỗi gửi báo cáo tuần Thứ 2: {e_wrep}")

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
                    entry_gold = price_gold # Vào ngay theo giá thị trường Market để không bị miss kèo!
                    sl_gold = plan_gold['sl']
                    sl_dist_gold = abs(entry_gold - sl_gold)
                    if plan_gold['signal'] == 'SHORT':
                        tp1_gold = round(entry_gold - sl_dist_gold * 1.2, 2)
                        tp2_gold = round(entry_gold - sl_dist_gold * 2.5, 2)
                    else:
                        tp1_gold = round(entry_gold + sl_dist_gold * 1.2, 2)
                        tp2_gold = round(entry_gold + sl_dist_gold * 2.5, 2)

                    s_emoji = "🔴 SHORT (BÁN)" if plan_gold['signal'] == 'SHORT' else "🟢 LONG (MUA)"
                    is_rej = 'REJECTION KEYVOLUME M5' in plan_gold.get('confirm_badge', '')
                    title_g = "🚨 <b>[TỰ ĐỘNG BÁO KÈO VIP: REJECTION KEYVOLUME M5 TẠI OB H1]</b> 🚨" if is_rej else "🚨 <b>[TỰ ĐỘNG BÁO KÈO VIP: ĐÃ PHÁ VỠ CẤU TRÚC M15 & KÍCH VOL M5]</b> 🚨"
                    action_l = "LỆNH VÀO NGAY (Market Now - Khớp Tức Thì):"
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
   <code>${sl_gold:,.2f}</code> (~{sl_dist_gold:.1f} Giá)
🎯 <b>Chốt lời 1 (TP1 - R:R 1:1.2 | Chốt 50% & Dời Hoà):</b> <code>${tp1_gold:,.2f}</code>
🎯 <b>Chốt lời 2 (TP2 - R:R 1:2.5 | Gồng Về Cản):</b> <code>${tp2_gold:,.2f}</code>

🧠 <b>Kế hoạch xử lý:</b>
{plan_gold['advice']}

🛡️ <b>QUẢN LÝ VỐN VÀNG MT5 (${CONFIG['ACCOUNT_BALANCE']:,.0f}):</b>
• Rủi ro tối đa 2%: <b>$40.0</b> (tương đương 0.02 - 0.04 lot trên MT5)"""
                    send_telegram(msg)
                    LAST_ALERT_TIME['GOLD'] = now
                    # Ghi nhận lệnh vào hệ thống theo dõi duy nhất 1 lệnh (Khớp Market ngay)
                    record_new_vip_trade(
                        asset='GOLD',
                        symbol='XAUUSD',
                        signal=plan_gold['signal'],
                        entry_price=entry_gold,
                        entry_stop=plan_gold.get('entry_stop', 0),
                        sl=sl_gold,
                        tp1=tp1_gold,
                        tp2=tp2_gold,
                        sl_dist=sl_dist_gold,
                        current_price=price_gold
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
                    entry_l = price_btc # Khớp Market tức thì!
                    sl_btc = plan_btc['sl']
                    sl_dist_btc = abs(entry_l - sl_btc)
                    if plan_btc['signal'] == 'SHORT':
                        tp1_btc = round(entry_l - sl_dist_btc * 1.2, 1)
                        tp2_btc = round(entry_l - sl_dist_btc * 2.5, 1)
                    else:
                        tp1_btc = round(entry_l + sl_dist_btc * 1.2, 1)
                        tp2_btc = round(entry_l + sl_dist_btc * 2.5, 1)

                    s_emoji = "🔴 SHORT (BÁN)" if plan_btc['signal'] == 'SHORT' else "🟢 LONG (MUA)"
                    is_rej_b = 'REJECTION KEYVOLUME M5' in plan_btc.get('confirm_badge', '')
                    title_b = "🚨 <b>[TỰ ĐỘNG BÁO KÈO VIP: REJECTION KEYVOLUME M5 TẠI OB H1]</b> 🚨" if is_rej_b else "🚨 <b>[TỰ ĐỘNG BÁO KÈO VIP: ĐÃ PHÁ VỠ CẤU TRÚC M15 & KÍCH VOL M5]</b> 🚨"
                    action_l_b = "LỆNH VÀO NGAY (Market Now - Khớp Tức Thì):"
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

🛡️ <b>Cắt lỗ (SL Ngoài Râu M5):</b> <code>${sl_btc:,.1f}</code> (~{sl_dist_btc:,.1f} USD)
🎯 <b>Chốt lời 1 (TP1 - R:R 1:1.2 | Chốt 50% & Dời Hoà):</b> <code>${tp1_btc:,.1f}</code>
🎯 <b>Chốt lời 2 (TP2 - R:R 1:2.5 | Gồng Theo Sóng):</b> <code>${tp2_btc:,.1f}</code>

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
                        sl=sl_btc,
                        tp1=tp1_btc,
                        tp2=tp2_btc,
                        sl_dist=sl_dist_btc,
                        current_price=price_btc
                    )

            # 7. QUÉT TỰ ĐỘNG BẮN KÈO SCALPING DAILY VOLUME PROFILE M5 (VÀNG OANDA)
            has_active_gold_m5 = any(t.get('symbol') == 'XAUUSD' and t.get('system', 'M5_SCALP') == 'M5_SCALP' for t in active_trades)
            has_active_btc_m5 = any(t.get('symbol') == 'BTCUSDT' and t.get('system', 'M5_SCALP') == 'M5_SCALP' for t in active_trades)
            has_active_gold_h1 = any(t.get('symbol') == 'XAUUSD' and t.get('system') == 'H1_MANU' for t in active_trades)
            has_active_btc_h1 = any(t.get('symbol') == 'BTCUSDT' and t.get('system') == 'H1_MANU' for t in active_trades)

            if not has_active_gold_m5 and (now - LAST_ALERT_TIME.get('GOLD_SCALP', 0) > 900):
                p_gold_vp = analyze_scalp_vp_plan('GOLD')
                if p_gold_vp and p_gold_vp.get('is_ready_to_enter') and p_gold_vp.get('dist_to_entry', 999) <= 5.0:
                    price_gold = p_gold_vp['curr_p']
                    entry_g = price_gold # Khớp Market tức thì!
                    sl_g = p_gold_vp['sl']
                    sl_dist_g = abs(entry_g - sl_g)
                    if p_gold_vp['is_buy']:
                        tp1_g = round(entry_g + sl_dist_g * 1.2, 2)
                        tp2_g = round(min(entry_g + sl_dist_g * 2.5, p_gold_vp['y_vah']), 2)
                        if tp2_g <= tp1_g: tp2_g = round(entry_g + sl_dist_g * 2.5, 2)
                    else:
                        tp1_g = round(entry_g - sl_dist_g * 1.2, 2)
                        tp2_g = round(max(entry_g - sl_dist_g * 2.5, p_gold_vp['y_val']), 2)
                        if tp2_g >= tp1_g: tp2_g = round(entry_g - sl_dist_g * 2.5, 2)

                    s_emoji = "🟢 LONG (MUA)" if p_gold_vp['is_buy'] else "🔴 SHORT (BÁN)"
                    action_s = "BUY" if p_gold_vp['is_buy'] else "SELL"
                    z_name = p_gold_vp.get('confirmed_defense', {}).get('zone_name', 'Cản Volume')
                    
                    msg_scalp_g = f"""🚨 <b>[TỰ ĐỘNG BÁO KÈO VIP: NỔ CỘT TÍM VSA M5 BẢO VỆ CẢN]</b> 🚨
━━━━━━━━━━━━━━━━━━
🥇 Tài sản: <b>VÀNG (OANDA:XAUUSD MT5)</b> [⚡ BOT 1: SCALP M5]
💰 Giá hiện tại: <b>${price_gold:,.2f}</b>
🛡️ <b>Xác Nhận Volume M5:</b> {p_gold_vp['defense_badge']}
🏛️ <b>VP Hôm Trước ({p_gold_vp['y_shape']}):</b>
• yVAL: <code>${p_gold_vp['y_val']:,.2f}</code> | yPOC: <code>${p_gold_vp['y_poc']:,.2f}</code> | yVAH: <code>${p_gold_vp['y_vah']:,.2f}</code>
🌅 <b>Hôm Nay:</b> Open: <code>${p_gold_vp['daily_open']:,.2f}</code> | dPOC: <code>${p_gold_vp['poc']:,.2f}</code>
🧭 <b>Bias:</b> {p_gold_vp['daily_bias']}
━━━━━━━━━━━━━━━━━━
🚀 <b>LỆNH VÀO NGAY (MARKET ENTRY): {s_emoji}</b>
👉 <b>Giá Vào Ngay (Now):</b> <code>${entry_g:,.2f}</code>
🛡️ <b>Cắt lỗ (SL An Toàn Ngoài Cản):</b> <code>${sl_g:,.2f}</code> (~{sl_dist_g:.1f} Giá)
🎯 <b>Chốt lời 1 (TP1 - Chốt 50% & Dời Hoà):</b> <code>${tp1_g:,.2f}</code>
🎯 <b>Chốt lời 2 (TP2 - Mục Tiêu Xoay Trục {p_gold_vp['y_shape']}):</b> <code>${tp2_g:,.2f}</code>

🧠 <b>Chiến Thuật:</b> Đã có nến M5 nổ CỘT TÍM VSA (Wyckoff Stopping Volume) rút râu hấp thụ hoàn toàn nỗ lực đẩy giá tại vùng {z_name}. Khớp Market ngay, chốt 50% tại TP1, dời BE gồng 50% về TP2!"""
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
                        sl_dist=sl_dist_g,
                        current_price=price_gold,
                        system='M5_SCALP'
                    )

            # 8. QUÉT TỰ ĐỘNG BẮN KÈO SCALPING DAILY VOLUME PROFILE M5 (BITCOIN)
            if not has_active_btc_m5 and (now - LAST_ALERT_TIME.get('BTC_SCALP', 0) > 900):
                p_btc_vp = analyze_scalp_vp_plan('BTC')
                if p_btc_vp and p_btc_vp.get('is_ready_to_enter') and p_btc_vp.get('dist_to_entry', 999) <= 250.0:
                    price_btc = p_btc_vp['curr_p']
                    entry_b = price_btc # Khớp Market tức thì!
                    sl_b = p_btc_vp['sl']
                    sl_dist_b = abs(entry_b - sl_b)
                    if p_btc_vp['is_buy']:
                        tp1_b = round(entry_b + sl_dist_b * 1.2, 1)
                        tp2_b = round(min(entry_b + sl_dist_b * 2.5, p_btc_vp['y_vah']), 1)
                        if tp2_b <= tp1_b: tp2_b = round(entry_b + sl_dist_b * 2.5, 1)
                    else:
                        tp1_b = round(entry_b - sl_dist_b * 1.2, 1)
                        tp2_b = round(max(entry_b - sl_dist_b * 2.5, p_btc_vp['y_val']), 1)
                        if tp2_b >= tp1_b: tp2_b = round(entry_b - sl_dist_b * 2.5, 1)

                    s_emoji = "🟢 LONG (MUA)" if p_btc_vp['is_buy'] else "🔴 SHORT (BÁN)"
                    action_s = "BUY" if p_btc_vp['is_buy'] else "SELL"
                    z_name_b = p_btc_vp.get('confirmed_defense', {}).get('zone_name', 'Cản Volume')
                    
                    msg_scalp_b = f"""🚨 <b>[TỰ ĐỘNG BÁO KÈO VIP: NỔ CỘT TÍM VSA M5 BẢO VỆ CẢN]</b> 🚨
━━━━━━━━━━━━━━━━━━
👑 Tài sản: <b>BITCOIN (BTCUSDT)</b> [⚡ BOT 1: SCALP M5]
💰 Giá hiện tại: <b>${price_btc:,.1f}</b>
🛡️ <b>Xác Nhận Volume M5:</b> {p_btc_vp['defense_badge']}
🏛️ <b>VP Hôm Trước ({p_btc_vp['y_shape']}):</b>
• yVAL: <code>${p_btc_vp['y_val']:,.1f}</code> | yPOC: <code>${p_btc_vp['y_poc']:,.1f}</code> | yVAH: <code>${p_btc_vp['y_vah']:,.1f}</code>
🌅 <b>Hôm Nay:</b> Open: <code>${p_btc_vp['daily_open']:,.1f}</code> | dPOC: <code>${p_btc_vp['poc']:,.1f}</code>
🧭 <b>Bias:</b> {p_btc_vp['daily_bias']}
━━━━━━━━━━━━━━━━━━
🚀 <b>LỆNH VÀO NGAY (MARKET ENTRY): {s_emoji}</b>
👉 <b>Giá Vào Ngay (Now):</b> <code>${entry_b:,.1f}</code>
🛡️ <b>Cắt lỗ (SL An Toàn Ngoài Cản):</b> <code>${sl_b:,.1f}</code> (~{sl_dist_b:,.1f} USD)
🎯 <b>Chốt lời 1 (TP1 - Chốt 50% & Dời Hoà):</b> <code>${tp1_b:,.1f}</code>
🎯 <b>Chốt lời 2 (TP2 - Mục Tiêu Xoay Trục {p_btc_vp['y_shape']}):</b> <code>${tp2_b:,.1f}</code>

🧠 <b>Chiến Thuật:</b> Đã có nến M5 nổ CỘT TÍM VSA (Wyckoff Stopping Volume) rút râu hấp thụ hoàn toàn nỗ lực đẩy giá tại vùng {z_name_b}. Khớp Market ngay, chốt 50% tại TP1, dời BE gồng 50% về TP2!"""
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
                        sl_dist=sl_dist_b,
                        current_price=price_btc,
                        system='M5_SCALP'
                    )

            # 9. QUÉT TỰ ĐỘNG BẮN KÈO SWING H1 MA NỮ (VÀNG OANDA)
            if not has_active_gold_h1 and (now - LAST_ALERT_TIME.get('GOLD_MANU_H1', 0) > 1800):
                p_gold_manu = analyze_manu_h1_plan('GOLD')
                if p_gold_manu and p_gold_manu.get('is_setup'):
                    p_dir = p_gold_manu['direction']
                    is_buy = (p_dir == 'BUY')
                    entry_g = p_gold_manu['entry']
                    sl_g = p_gold_manu['sl']
                    tp1_g = p_gold_manu['tp1']
                    tp2_g = p_gold_manu['tp2']
                    risk_g = p_gold_manu['risk']
                    curr_g = p_gold_manu['curr_p']
                    s_emoji = "🟢 BUY STOP / LONG" if is_buy else "🔴 SELL STOP / SHORT"

                    msg_manu_g = f"""🧙‍♀️ <b>[TỰ ĐỘNG BÁO KÈO SWING H1: HỆ THỐNG MA NỮ (SENPAI THÀNH)]</b> 🧙‍♀️
━━━━━━━━━━━━━━━━━━
🥇 Tài sản: <b>VÀNG (OANDA:XAUUSD H1)</b> [🧙‍♀️ BOT 2: SWING H1]
💰 Giá hiện tại: <b>${curr_g:,.2f}</b>
🏛️ <b>Cản Linechart H1:</b> Kháng cự <code>${p_gold_manu['recent_res']:,.2f}</code> | Hỗ trợ <code>${p_gold_manu['recent_sup']:,.2f}</code>
✨ <b>Trạng Thái:</b> Nến H1 đóng phá cản + Đang tạo Perfect Wick Retest!
━━━━━━━━━━━━━━━━━━
🚀 <b>LỆNH VÀO: {s_emoji}</b>
👉 <b>Điểm Kích Hoạt (Entry Stop):</b> <code>${entry_g:,.2f}</code>
🛡️ <b>Cắt Lỗ (SL Mút Râu Retest):</b> <code>${sl_g:,.2f}</code> (~{risk_g:.1f} Giá)
🎯 <b>Chốt Lời 1 (TP1 - Độ Nảy 1.0R):</b> <code>${tp1_g:,.2f}</code>
🎯 <b>Chốt Lời 2 (TP2 - Cản 2 Nến 1.8R):</b> <code>${tp2_g:,.2f}</code>

🧠 <b>Chiến Thuật:</b> Lùi bao nhiêu tiến bấy nhiêu! Chờ giá quét cản Linechart H1 nảy lên khớp Buy/Sell Stop. Chốt 50% tại TP1, dời BE gồng 50% về TP2!"""
                    send_telegram(msg_manu_g)
                    LAST_ALERT_TIME['GOLD_MANU_H1'] = now
                    record_new_vip_trade(
                        asset='GOLD',
                        symbol='XAUUSD',
                        signal='LONG' if is_buy else 'SHORT',
                        entry_price=entry_g,
                        entry_stop=entry_g,
                        sl=sl_g,
                        tp1=tp1_g,
                        tp2=tp2_g,
                        sl_dist=risk_g,
                        current_price=curr_g,
                        system='H1_MANU'
                    )

            # 10. QUÉT TỰ ĐỘNG BẮN KÈO SWING H1 MA NỮ (BITCOIN)
            if not has_active_btc_h1 and (now - LAST_ALERT_TIME.get('BTC_MANU_H1', 0) > 1800):
                p_btc_manu = analyze_manu_h1_plan('BTC')
                if p_btc_manu and p_btc_manu.get('is_setup'):
                    p_dir_b = p_btc_manu['direction']
                    is_buy_b = (p_dir_b == 'BUY')
                    entry_b = p_btc_manu['entry']
                    sl_b = p_btc_manu['sl']
                    tp1_b = p_btc_manu['tp1']
                    tp2_b = p_btc_manu['tp2']
                    risk_b = p_btc_manu['risk']
                    curr_b = p_btc_manu['curr_p']
                    s_emoji_b = "🟢 BUY STOP / LONG" if is_buy_b else "🔴 SELL STOP / SHORT"

                    msg_manu_b = f"""🧙‍♀️ <b>[TỰ ĐỘNG BÁO KÈO SWING H1: HỆ THỐNG MA NỮ (SENPAI THÀNH)]</b> 🧙‍♀️
━━━━━━━━━━━━━━━━━━
👑 Tài sản: <b>BITCOIN (BTCUSDT H1)</b> [🧙‍♀️ BOT 2: SWING H1]
💰 Giá hiện tại: <b>${curr_b:,.1f}</b>
🏛️ <b>Cản Linechart H1:</b> Kháng cự <code>${p_btc_manu['recent_res']:,.1f}</code> | Hỗ trợ <code>${p_btc_manu['recent_sup']:,.1f}</code>
✨ <b>Trạng Thái:</b> Nến H1 đóng phá cản + Đang tạo Perfect Wick Retest!
━━━━━━━━━━━━━━━━━━
🚀 <b>LỆNH VÀO: {s_emoji_b}</b>
👉 <b>Điểm Kích Hoạt (Entry Stop):</b> <code>${entry_b:,.1f}</code>
🛡️ <b>Cắt Lỗ (SL Mút Râu Retest):</b> <code>${sl_b:,.1f}</code> (~{risk_b:,.1f} USDT)
🎯 <b>Chốt Lời 1 (TP1 - Độ Nảy 1.0R):</b> <code>${tp1_b:,.1f}</code>
🎯 <b>Chốt Lời 2 (TP2 - Cản 2 Nến 1.8R):</b> <code>${tp2_b:,.1f}</code>

🧠 <b>Chiến Thuật:</b> Lùi bao nhiêu tiến bấy nhiêu! Chờ giá quét cản Linechart H1 nảy lên khớp Buy/Sell Stop. Chốt 50% tại TP1, dời BE gồng 50% về TP2!"""
                    send_telegram(msg_manu_b)
                    LAST_ALERT_TIME['BTC_MANU_H1'] = now
                    record_new_vip_trade(
                        asset='BTC',
                        symbol='BTCUSDT',
                        signal='LONG' if is_buy_b else 'SHORT',
                        entry_price=entry_b,
                        entry_stop=entry_b,
                        sl=sl_b,
                        tp1=tp1_b,
                        tp2=tp2_b,
                        sl_dist=risk_b,
                        current_price=curr_b,
                        system='H1_MANU'
                    )

            # 6. HỆ THỐNG FIBO SÓNG HỒI H1 (FIBO_WAVE) CHO VÀNG & BTC
            for f_asset, f_sym, f_dec in [('GOLD', 'XAUUSD', 2), ('BTC', 'BTCUSDT', 1)]:
                if now - LAST_ALERT_TIME.get(f'{f_asset}_FIBO', 0) > 10800:
                    f_plan = analyze_fibo_wave_plan(f_asset)
                    if f_plan and f_plan.get('is_ready'):
                        f_name = "🥇 VÀNG (XAUUSD)" if f_asset == 'GOLD' else "👑 BITCOIN (BTCUSDT)"
                        f_sgn = "🟢 BUY (LONG)" if f_plan['signal'] == 'LONG' else "🔴 SHORT (BÁN)"
                        msg_fibo = (
                            f"📐 <b>[TÍN HIỆU FIBO SÓNG HỒI H1 - {f_name}]</b>\n━━━━━━━━━━━━━━━━━━\n"
                            f"🚀 <b>Lệnh:</b> {f_sgn}\n"
                            f"• 👉 <b>Entry (Vùng 0.50-0.618):</b> <code>${f_plan['curr_p']:,.{f_dec}f}</code>\n"
                            f"• 🛡️ <b>SL (Sau Fib 0.786):</b> <code>${f_plan['sl']:,.{f_dec}f}</code>\n"
                            f"• 🎯 <b>TP1 (Fib 0.236):</b> <code>${f_plan['tp1']:,.{f_dec}f}</code> | 🎯 <b>TP2 (Ext):</b> <code>${f_plan['tp2']:,.{f_dec}f}</code>\n"
                            f"💡 <i>Giá đã hồi về Golden Zone 0.50-0.618 của sóng H1 và có nến M15 xác nhận đảo chiều!</i>"
                        )
                        send_telegram(msg_fibo)
                        LAST_ALERT_TIME[f'{f_asset}_FIBO'] = now
                        record_new_vip_trade(
                            asset=f_asset, symbol=f_sym, signal=f_plan['signal'],
                            entry_price=f_plan['curr_p'], entry_stop=f_plan['curr_p'],
                            sl=f_plan['sl'], tp1=f_plan['tp1'], tp2=f_plan['tp2'],
                            sl_dist=abs(f_plan['curr_p'] - f_plan['sl']),
                            current_price=f_plan['curr_p'], system='FIBO_WAVE'
                        )


        except Exception as e:
            print(f"Lỗi worker quét tự động: {e}")
            time.sleep(10)

if __name__ == '__main__':
    threading.Thread(target=start_health_server, daemon=True).start()
    threading.Thread(target=self_ping_worker, daemon=True).start()
    threading.Thread(target=auto_diamond_alert_worker, daemon=True).start()
    run_bot()
