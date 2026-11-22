"""
=============================================================================
FX DREAM TRADING - BACKTEST ENGINE FOR XAUUSD (GOLD)
Chiến Lược: Khối Lệnh OB H1 + Phá Vỡ Cấu Trúc M15 (BOS) + Nến M5 Rút Râu Kích Vol
Sử dụng chính xác 100% thuật toán của Bot Telegram live
Quản Lý Lệnh: TP1 R:R 1:1.2 (Chốt 50% & Dời Hoà) | TP2 R:R 1:2.5 (Gồng Hết Sóng)
=============================================================================
"""

import os
import json
import time
import urllib.request
import numpy as np
import telegram_bot

CACHE_FILE = "xauusd_m5_data.json"
STARTING_CAPITAL = 2000.0  # USD
RISK_PCT = 2.0             # 2% mỗi lệnh = $40.0 trên tài khoản $2,000
RR_TP1 = 1.2               # TP1 ăn 1.2R
RR_TP2 = 2.5               # TP2 ăn 2.5R
PROXIMITY_OB = 4.0         # Giá tiếp cận vùng OB trong phạm vi 4.0 giá
MIN_RISK = 3.5             # Khoảng SL tối thiểu (3.5 giá)
MAX_RISK = 20.0            # Khoảng SL tối đa (20 giá)

def fetch_or_load_historical_m5(total_candles=5000):
    """Tải và lưu trữ dữ liệu nến M5 lịch sử để backtest"""
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r') as f:
                cached = json.load(f)
                if len(cached) >= total_candles:
                    print(f"📦 Đã load {len(cached)} nến M5 từ cache file '{CACHE_FILE}'!")
                    return cached[:total_candles]
        except Exception as e:
            print(f"Lỗi đọc cache: {e}")

    print(f"🌐 Đang tải {total_candles} nến M5 XAUUSD lịch sử từ sàn Bybit...")
    all_candles = []
    end_time = None
    
    while len(all_candles) < total_candles:
        url = f'https://api.bybit.com/v5/market/kline?category=linear&symbol=XAUUSDT&interval=5&limit=1000'
        if end_time:
            url += f'&end={end_time}'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        res = json.loads(urllib.request.urlopen(req, timeout=12).read().decode())['result']['list']
        if not res:
            break
        all_candles.extend(res)
        end_time = int(res[-1][0]) - 1
        print(f"   ➔ Đã tải {len(all_candles)}/{total_candles} nến M5...")
        time.sleep(0.3)

    candles = all_candles[:total_candles]
    try:
        with open(CACHE_FILE, 'w') as f:
            json.dump(candles, f)
        print(f"💾 Đã lưu cache {len(candles)} nến vào '{CACHE_FILE}'!")
    except Exception as e:
        print(f"Lỗi lưu cache: {e}")

    return candles

def format_time(ts_ms):
    return time.strftime('%Y-%m-%d %H:%M', time.gmtime(int(ts_ms) / 1000))

def build_multitimeframe_bars(m5_chronological):
    """
    Xây dựng nến M15 và H1 từ chuỗi nến M5 theo thứ tự thời gian.
    Chỉ nến nào đã hoàn thành 100% mới được tính (chống Lookahead Bias).
    """
    m15_bars = []
    h1_bars = []
    
    m15_current = None
    h1_current = None
    
    m5_to_m15_state = []
    m5_to_h1_state = []
    
    for k in m5_chronological:
        t = int(k[0])
        o, h, l, c, v = float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])
        
        # M15 block: 15 mins = 900,000 ms
        m15_period = (t // 900000) * 900000
        if m15_current is None or m15_current['period'] != m15_period:
            if m15_current is not None and m15_current['count'] == 3:
                m15_bars.append([str(m15_current['period']), str(m15_current['open']), str(m15_current['high']), str(m15_current['low']), str(m15_current['close']), str(m15_current['vol'])])
            m15_current = {'period': m15_period, 'open': o, 'high': h, 'low': l, 'close': c, 'vol': v, 'count': 1}
        else:
            m15_current['high'] = max(m15_current['high'], h)
            m15_current['low'] = min(m15_current['low'], l)
            m15_current['close'] = c
            m15_current['vol'] += v
            m15_current['count'] += 1

        # H1 block: 60 mins = 3,600,000 ms
        h1_period = (t // 3600000) * 3600000
        if h1_current is None or h1_current['period'] != h1_period:
            if h1_current is not None and h1_current['count'] == 12:
                h1_bars.append([str(h1_current['period']), str(h1_current['open']), str(h1_current['high']), str(h1_current['low']), str(h1_current['close']), str(h1_current['vol'])])
            h1_current = {'period': h1_period, 'open': o, 'high': h, 'low': l, 'close': c, 'vol': v, 'count': 1}
        else:
            h1_current['high'] = max(h1_current['high'], h)
            h1_current['low'] = min(h1_current['low'], l)
            h1_current['close'] = c
            h1_current['vol'] += v
            h1_current['count'] += 1

        m5_to_m15_state.append(len(m15_bars))
        m5_to_h1_state.append(len(h1_bars))
        
    return m15_bars, h1_bars, m5_to_m15_state, m5_to_h1_state

def run_backtest(candles_count=5000, use_trend_filter=True):
    raw_m5 = fetch_or_load_historical_m5(candles_count)
    m5_chronological = list(reversed(raw_m5))
    total_m5 = len(m5_chronological)
    
    filter_txt = "BẬT (Đồng Pha Xu Hướng H1 - Chống Cản Tàu/Bắt Dao Rơi)" if use_trend_filter else "TẮT"
    print(f"\n📊 BẮT ĐẦU BACKTEST CHI TIẾT TRÊN {total_m5} NẾN M5 XAUUSD")
    print(f"⏱️ Thời gian: từ {format_time(m5_chronological[0][0])} đến {format_time(m5_chronological[-1][0])}")
    print(f"💰 Vốn khởi điểm: ${STARTING_CAPITAL:,.2f} | Rủi ro mỗi lệnh: {RISK_PCT}% (${STARTING_CAPITAL * RISK_PCT / 100:.2f})")
    print(f"🛡️ Bộ lọc xu hướng H1: {filter_txt}\n")

    m15_bars, h1_bars, m5_to_m15, m5_to_h1 = build_multitimeframe_bars(m5_chronological)
    print(f"   ➔ Đã tái cấu trúc: {len(h1_bars)} nến H1 | {len(m15_bars)} nến M15 hoàn thành.")

    trades = []
    active_trade = None
    balance = STARTING_CAPITAL
    equity_curve = [balance]
    
    start_idx = 400
    
    for i in range(start_idx, total_m5):
        m5_bar = m5_chronological[i]
        t = int(m5_bar[0])
        o, h, l, c, v = float(m5_bar[1]), float(m5_bar[2]), float(m5_bar[3]), float(m5_bar[4]), float(m5_bar[5])
        
        # 1. CẬP NHẬT TRẠNG THÁI LỆNH ĐANG CHẠY (NẾU CÓ)
        if active_trade is not None:
            sig = active_trade['type']
            sl = active_trade['current_sl']
            tp1 = active_trade['tp1']
            tp2 = active_trade['tp2']
            entry_p = active_trade['entry_price']
            risk_usd = active_trade['risk_usd']
            
            # --- XỬ LÝ LỆNH SHORT ---
            if sig == 'SHORT':
                # Chạm TP1
                if not active_trade['tp1_hit'] and l <= tp1:
                    active_trade['tp1_hit'] = True
                    active_trade['tp1_time'] = format_time(t)
                    pnl_tp1 = 0.5 * risk_usd * RR_TP1
                    active_trade['realized_pnl'] += pnl_tp1
                    active_trade['current_sl'] = entry_p # Dời SL về Hoà Vốn

                # Chạm TP2
                if active_trade['tp1_hit'] and l <= tp2:
                    pnl_tp2 = 0.5 * risk_usd * RR_TP2
                    active_trade['realized_pnl'] += pnl_tp2
                    active_trade['exit_price'] = tp2
                    active_trade['exit_time'] = format_time(t)
                    active_trade['outcome'] = 'TP2_FULL (Ăn Cả 2 TP)'
                    active_trade['return_r'] = 0.5 * RR_TP1 + 0.5 * RR_TP2
                    balance += active_trade['realized_pnl']
                    active_trade['balance_after'] = balance
                    trades.append(active_trade)
                    active_trade = None

                # Chạm Stop Loss
                elif h >= sl:
                    if active_trade['tp1_hit']:
                        active_trade['exit_price'] = entry_p
                        active_trade['exit_time'] = format_time(t)
                        active_trade['outcome'] = 'TP1 + BREAKEVEN (Hoà Vốn SL)'
                        active_trade['return_r'] = 0.5 * RR_TP1
                        balance += active_trade['realized_pnl']
                        active_trade['balance_after'] = balance
                        trades.append(active_trade)
                    else:
                        active_trade['realized_pnl'] = -risk_usd
                        active_trade['exit_price'] = sl
                        active_trade['exit_time'] = format_time(t)
                        active_trade['outcome'] = 'STOP_LOSS (Cắn SL Ban Đầu)'
                        active_trade['return_r'] = -1.0
                        balance += active_trade['realized_pnl']
                        active_trade['balance_after'] = balance
                        trades.append(active_trade)
                    active_trade = None

            # --- XỬ LÝ LỆNH LONG ---
            elif sig == 'LONG':
                # Chạm TP1
                if not active_trade['tp1_hit'] and h >= tp1:
                    active_trade['tp1_hit'] = True
                    active_trade['tp1_time'] = format_time(t)
                    pnl_tp1 = 0.5 * risk_usd * RR_TP1
                    active_trade['realized_pnl'] += pnl_tp1
                    active_trade['current_sl'] = entry_p

                # Chạm TP2
                if active_trade['tp1_hit'] and h >= tp2:
                    pnl_tp2 = 0.5 * risk_usd * RR_TP2
                    active_trade['realized_pnl'] += pnl_tp2
                    active_trade['exit_price'] = tp2
                    active_trade['exit_time'] = format_time(t)
                    active_trade['outcome'] = 'TP2_FULL (Ăn Cả 2 TP)'
                    active_trade['return_r'] = 0.5 * RR_TP1 + 0.5 * RR_TP2
                    balance += active_trade['realized_pnl']
                    active_trade['balance_after'] = balance
                    trades.append(active_trade)
                    active_trade = None

                # Chạm Stop Loss
                elif l <= sl:
                    if active_trade['tp1_hit']:
                        active_trade['exit_price'] = entry_p
                        active_trade['exit_time'] = format_time(t)
                        active_trade['outcome'] = 'TP1 + BREAKEVEN (Hoà Vốn SL)'
                        active_trade['return_r'] = 0.5 * RR_TP1
                        balance += active_trade['realized_pnl']
                        active_trade['balance_after'] = balance
                        trades.append(active_trade)
                    else:
                        active_trade['realized_pnl'] = -risk_usd
                        active_trade['exit_price'] = sl
                        active_trade['exit_time'] = format_time(t)
                        active_trade['outcome'] = 'STOP_LOSS (Cắn SL Ban Đầu)'
                        active_trade['return_r'] = -1.0
                        balance += active_trade['realized_pnl']
                        active_trade['balance_after'] = balance
                        trades.append(active_trade)
                    active_trade = None

            equity_curve.append(balance)
            if active_trade is not None:
                continue

        # 2. TÌM TÍN HIỆU MỞ LỆNH MỚI (CHỈ KHI ĐANG TRỐNG LỆNH)
        n_h1 = m5_to_h1[i]
        n_m15 = m5_to_m15[i]
        
        if n_h1 < 25 or n_m15 < 20:
            continue
            
        h1_avail = h1_bars[:n_h1]
        m15_avail = m15_bars[:n_m15]
        
        # Gọi chính xác hàm phân tích từ telegram_bot (descending list)
        sw_h, b_ob, sw_l, bull_ob = telegram_bot.find_smc_swings_and_ob(list(reversed(h1_avail)), is_gold=True)
        m15_struct = telegram_bot.analyze_m15_structure(list(reversed(m15_avail)), delta=0.0, is_gold=True)
        
        # Trend H1 qua EMA 34
        h1_closes = [float(b[4]) for b in h1_avail]
        alpha = 2.0 / (34.0 + 1.0)
        h1_ema = h1_closes[0]
        for hp in h1_closes[1:]:
            h1_ema = alpha * hp + (1.0 - alpha) * h1_ema
        trend_h1 = "BULL" if h1_closes[-1] > h1_ema else "BEAR"

        # Phân tích Volume & Râu nến M5
        m5_prev_20_vol = [float(k[5]) for k in m5_chronological[i-20:i]]
        avg_vol = np.mean(m5_prev_20_vol) if m5_prev_20_vol else v
        vol_ratio = v / (avg_vol + 1e-5)
        
        rng = h - l
        if rng < 0.6:
            continue
            
        up_wick = h - max(o, c)
        low_wick = min(o, c) - l
        
        up_wick_pct = up_wick / rng
        low_wick_pct = low_wick / rng
        
        # A. KỊCH BẢN SELL (Tại Bearish OB H1):
        pass_sell_trend = (not use_trend_filter) or (trend_h1 == 'BEAR')
        is_near_sell_ob = (h >= b_ob['bottom'] - PROXIMITY_OB) and (l <= b_ob['top'] + 2.0)
        has_bear_wick = (up_wick_pct >= 0.35) and (vol_ratio >= 1.15) and (c <= o + 0.25 * rng)
        
        if pass_sell_trend and is_near_sell_ob and m15_struct['has_bear_bos'] and has_bear_wick:
            entry_p = c
            sl_p = round(max(h + 0.8, b_ob['top'] + 1.5), 2)
            risk = round(sl_p - entry_p, 2)
            
            if MIN_RISK <= risk <= MAX_RISK:
                tp1 = round(entry_p - (risk * RR_TP1), 2)
                tp2 = round(entry_p - (risk * RR_TP2), 2)
                risk_usd = balance * (RISK_PCT / 100.0)
                
                active_trade = {
                    'id': len(trades) + 1,
                    'type': 'SHORT',
                    'entry_time': format_time(t),
                    'entry_price': entry_p,
                    'initial_sl': sl_p,
                    'current_sl': sl_p,
                    'risk_price': risk,
                    'risk_usd': risk_usd,
                    'tp1': tp1,
                    'tp2': tp2,
                    'tp1_hit': False,
                    'realized_pnl': 0.0,
                    'status': 'OPEN',
                    'ob_zone': f"[{b_ob['bottom']:.1f} - {b_ob['top']:.1f}]",
                    'wick_pct': f"{up_wick_pct*100:.1f}%",
                    'vol_ratio': f"{vol_ratio:.2f}x"
                }
                continue

        # B. KỊCH BẢN BUY (Tại Bullish OB H1):
        pass_buy_trend = (not use_trend_filter) or (trend_h1 == 'BULL')
        is_near_buy_ob = (l <= bull_ob['top'] + PROXIMITY_OB) and (h >= bull_ob['bottom'] - 2.0)
        has_bull_wick = (low_wick_pct >= 0.35) and (vol_ratio >= 1.15) and (c >= o - 0.25 * rng)
        
        if pass_buy_trend and is_near_buy_ob and m15_struct['has_bull_bos'] and has_bull_wick:
            entry_p = c
            sl_p = round(min(l - 0.8, bull_ob['bottom'] - 1.5), 2)
            risk = round(entry_p - sl_p, 2)
            
            if MIN_RISK <= risk <= MAX_RISK:
                tp1 = round(entry_p + (risk * RR_TP1), 2)
                tp2 = round(entry_p + (risk * RR_TP2), 2)
                risk_usd = balance * (RISK_PCT / 100.0)
                
                active_trade = {
                    'id': len(trades) + 1,
                    'type': 'LONG',
                    'entry_time': format_time(t),
                    'entry_price': entry_p,
                    'initial_sl': sl_p,
                    'current_sl': sl_p,
                    'risk_price': risk,
                    'risk_usd': risk_usd,
                    'tp1': tp1,
                    'tp2': tp2,
                    'tp1_hit': False,
                    'realized_pnl': 0.0,
                    'status': 'OPEN',
                    'ob_zone': f"[{bull_ob['bottom']:.1f} - {bull_ob['top']:.1f}]",
                    'wick_pct': f"{low_wick_pct*100:.1f}%",
                    'vol_ratio': f"{vol_ratio:.2f}x"
                }
                continue

    # 3. TỔNG HỢP VÀ BÁO CÁO KẾT QUẢ BACKTEST
    total_trades = len(trades)
    if total_trades == 0:
        print("⚠️ Không có lệnh nào được kích hoạt trong giai đoạn này với bộ lọc hiện tại.")
        return

    full_tp2_trades = [tr for tr in trades if 'TP2_FULL' in tr['outcome']]
    tp1_be_trades = [tr for tr in trades if 'TP1 + BREAKEVEN' in tr['outcome']]
    sl_trades = [tr for tr in trades if 'STOP_LOSS' in tr['outcome']]
    
    winning_trades = full_tp2_trades + tp1_be_trades
    losing_trades = sl_trades
    
    winrate = (len(winning_trades) / total_trades) * 100.0
    
    total_gain_usd = sum(tr['realized_pnl'] for tr in winning_trades)
    total_loss_usd = abs(sum(tr['realized_pnl'] for tr in losing_trades))
    net_pnl_usd = total_gain_usd - total_loss_usd
    profit_factor = (total_gain_usd / total_loss_usd) if total_loss_usd > 0 else 999.0
    
    peak = STARTING_CAPITAL
    max_dd_usd = 0.0
    max_dd_pct = 0.0
    curr_bal = STARTING_CAPITAL
    for tr in trades:
        curr_bal += tr['realized_pnl']
        if curr_bal > peak:
            peak = curr_bal
        dd = peak - curr_bal
        dd_pct = (dd / peak) * 100.0 if peak > 0 else 0
        if dd > max_dd_usd:
            max_dd_usd = dd
        if dd_pct > max_dd_pct:
            max_dd_pct = dd_pct

    print("\n" + "="*70)
    print("🏆 BÁO CÁO KẾT QUẢ BACKTEST CHIẾN LƯỢC FX DREAM (XAUUSD)")
    print("="*70)
    print(f"💰 Vốn ban đầu:           ${STARTING_CAPITAL:,.2f}")
    print(f"💰 Vốn kết thúc:          ${balance:,.2f} ({((balance - STARTING_CAPITAL)/STARTING_CAPITAL)*100:+.2f}%)")
    print(f"📈 Lợi nhuận ròng:        {'+' if net_pnl_usd >= 0 else ''}${net_pnl_usd:,.2f}")
    print(f"📊 Tổng số lệnh kích hoạt: {total_trades} lệnh")
    print(f"🎯 TỶ LỆ THẮNG (WINRATE):  {winrate:.2f}% ({len(winning_trades)} Thắng / {len(losing_trades)} Thua)")
    print(f"   • Ăn trọn 2 TP (TP2 Full): {len(full_tp2_trades)} lệnh (+1.85R)")
    print(f"   • Ăn TP1 + Hoà Vốn SL:     {len(tp1_be_trades)} lệnh (+0.60R)")
    print(f"   • Dính Cắt Lỗ Ban Đầu:     {len(sl_trades)} lệnh (-1.00R)")
    print(f"⚖️ Hệ số Lợi Nhuận (Profit Factor): {profit_factor:.2f}")
    print(f"📉 Mức Sụt Giảm Tối Đa (Max DD):   ${max_dd_usd:,.2f} ({max_dd_pct:.2f}%)")
    print(f"🛡️ Quản lý rủi ro:       2% tài khoản / lệnh | TP1 Dời Hoà bảo toàn vốn")
    print("="*70)

    print("\n📋 CHI TIẾT TỪNG LỆNH GIAO DỊCH:")
    print(f"{'ID':<3} | {'VÀO LỆNH':<16} | {'LOẠI':<5} | {'ENTRY':<8} | {'SL':<8} | {'TP1':<8} | {'TP2':<8} | {'KẾT QUẢ':<28} | {'P/L ($)':<8} | {'VỐN ($)':<9}")
    print("-" * 115)
    for tr in trades:
        pnl_str = f"{tr['realized_pnl']:+,.1f}"
        print(f"{tr['id']:<3} | {tr['entry_time']:<16} | {tr['type']:<5} | {tr['entry_price']:<8.2f} | {tr['initial_sl']:<8.2f} | {tr['tp1']:<8.2f} | {tr['tp2']:<8.2f} | {tr['outcome']:<28} | {pnl_str:<8} | ${tr['balance_after']:<8.1f}")
    print("="*115 + "\n")

if __name__ == '__main__':
    run_backtest(candles_count=5000, use_trend_filter=True)
