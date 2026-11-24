"""
=============================================================================
FX DREAM TRADING - BACKTEST ENGINE 1 THÁNG (VOLUME PROFILE M5 SCALPING)
- Dữ liệu: 1 Tháng nến M5 trực tiếp từ MT5 (XAUUSDc & BTCUSDc)
- Chiến lược:
  1. Volume Profile Ngày Hôm Trước (yVAL, yPOC, yVAH - Value Area 70%)
  2. Phân loại L-Shape (dồn đáy -> Ưu tiên Buy) & P-Shape (dồn đỉnh -> Ưu tiên Sell)
  3. Xác nhận Nến M5 rút chân/rút râu tại cản + Kích Volume M5 >= 1.2x SMA(20)
  4. Quản lý vốn: SL ngoài râu M5 (Vàng 5.5-9.5 giá, BTC 250-420 USD)
     - TP1: R:R 1:1.2 (Chốt 50% khối lượng, dời SL về Hoà Vốn)
     - TP2: R:R 1:2.5 (Gồng 50% còn lại về cản đối diện hoặc hết sóng)
=============================================================================
"""

import os
import sys
import time
import datetime
import numpy as np
import MetaTrader5 as mt5

STARTING_CAPITAL = 2000.0  # USD
RISK_PER_TRADE = 40.0      # 2% mỗi lệnh trên tài khoản $2,000
RR_TP1 = 1.2
RR_TP2 = 2.5

def get_m5_rates_from_mt5(symbol, count=6000):
    """Lấy dữ liệu nến M5 trực tiếp từ MT5 terminal trong vòng 1 tháng"""
    if not mt5.initialize(path=r'C:\Program Files\MetaTrader 5\terminal64.exe'):
        print(f"❌ Lỗi khởi động MT5: {mt5.last_error()}")
        return None

    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M5, 0, count)
    mt5.shutdown()
    return rates

def compute_volume_profile(rates, bins_count=50):
    try:
        lows = [float(r['low']) for r in rates]
        highs = [float(r['high']) for r in rates]
        min_p = min(lows)
        max_p = max(highs)
        if max_p <= min_p:
            return None
        bin_size = (max_p - min_p) / bins_count
        bins = [0.0] * bins_count
        total_vol = 0.0
        for r in rates:
            l, h = float(r['low']), float(r['high'])
            v = float(r['tick_volume'])
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

        dist_val_poc = abs(poc_price - val_price)
        dist_vah_poc = abs(vah_price - poc_price)
        if dist_val_poc < dist_vah_poc * 0.75:
            shape = 'L-Shape'  # Volume tích tụ đáy -> Ưu tiên Buy
        elif dist_vah_poc < dist_val_poc * 0.75:
            shape = 'P-Shape'  # Volume phân phối đỉnh -> Ưu tiên Sell
        else:
            shape = 'D-Shape'  # Cân bằng

        return {
            'poc': poc_price,
            'val': val_price,
            'vah': vah_price,
            'shape': shape,
            'high': max_p,
            'low': min_p
        }
    except Exception as e:
        return None

def run_backtest_month(asset='GOLD', symbol='XAUUSDc', count=6000):
    is_gold = (asset == 'GOLD')
    sym_name = "🥇 VÀNG (XAUUSD - Chuẩn MT5)" if is_gold else "👑 BITCOIN (BTCUSD - Chuẩn MT5)"
    unit = "Giá" if is_gold else "USD"
    min_sl_dist = 5.5 if is_gold else 250.0
    max_sl_dist = 9.5 if is_gold else 420.0
    sl_buf = 0.8 if is_gold else 35.0

    rates = get_m5_rates_from_mt5(symbol, count=count)
    if rates is None or len(rates) == 0:
        print(f"⚠️ Không lấy được dữ liệu cho {symbol}")
        return

    # Gom nến theo ngày (UTC+0 / Broker time)
    daily_groups = {}
    for r in rates:
        dt = datetime.datetime.fromtimestamp(r['time'], datetime.timezone.utc)
        day_str = dt.strftime('%Y-%m-%d')
        if day_str not in daily_groups:
            daily_groups[day_str] = []
        daily_groups[day_str].append(r)

    days_sorted = sorted(daily_groups.keys())
    start_d = days_sorted[1]
    end_d = days_sorted[-1]
    print(f"\n{'='*60}")
    print(f"📊 BACKTEST 1 THÁNG: {sym_name}")
    print(f"⏱️ Khoảng thời gian: Từ {start_d} đến {end_d} (~{len(days_sorted)} ngày giao dịch)")
    print(f"📦 Tổng số nến M5 phân tích: {len(rates)} nến")
    print(f"{'='*60}")

    trades = []
    capital = STARTING_CAPITAL
    peak_capital = capital
    max_drawdown = 0.0

    for d_idx in range(1, len(days_sorted)):
        prev_day = days_sorted[d_idx - 1]
        curr_day = days_sorted[d_idx]

        prev_rates = daily_groups[prev_day]
        curr_rates = daily_groups[curr_day]
        if len(prev_rates) < 80 or len(curr_rates) < 15:
            continue

        # 1. Tính Volume Profile ngày hôm trước
        vp = compute_volume_profile(prev_rates)
        if not vp:
            continue

        ypoc = vp['poc']
        yval = vp['val']
        yvah = vp['vah']
        shape = vp['shape']

        # XÁC ĐỊNH BIAS NGÀY HÔM TRƯỚC (Trend Alignment)
        # Nếu nến ngày hôm trước đóng dưới Open hoặc dưới POC -> Ưu tiên Canh SELL
        # Nếu nến ngày hôm trước đóng trên Open hoặc trên POC -> Ưu tiên Canh BUY
        prev_open = float(prev_rates[0]['open'])
        prev_close = float(prev_rates[-1]['close'])
        daily_bull = (prev_close > prev_open) and (prev_close > ypoc)
        daily_bear = (prev_close < prev_open) and (prev_close < ypoc)

        day_traded = False

        # 2. Quét từng nến M5 trong ngày
        for i in range(20, len(curr_rates)):
            if day_traded:
                break

            r = curr_rates[i]
            o = float(r['open'])
            h = float(r['high'])
            l = float(r['low'])
            cl = float(r['close'])
            v = float(r['tick_volume'])

            # Volume SMA(20)
            past_vols = [float(curr_rates[k]['tick_volume']) for k in range(i - 20, i)]
            avg_vol = np.mean(past_vols) if past_vols else 1.0
            is_vol_spike = (v >= 1.2 * avg_vol)

            candle_rng = h - l
            if candle_rng == 0:
                continue

            # A. KÈO BUY XOAY TRỤC (Chỉ đánh khi KHÔNG bị ngược xu hướng ngày)
            lower_wick = min(o, cl) - l
            rejection_buy = (lower_wick >= 0.35 * candle_rng) and (l <= yval + (1.2 if is_gold else 70.0)) and (cl >= yval - (0.6 if is_gold else 30.0))

            if not daily_bear and (shape in ['L-Shape', 'D-Shape']) and rejection_buy and is_vol_spike:
                entry = cl
                sl_calc = l - sl_buf
                sl_dist = entry - sl_calc
                if sl_dist < min_sl_dist:
                    sl_calc = entry - min_sl_dist
                    sl_dist = min_sl_dist
                elif sl_dist > max_sl_dist:
                    sl_calc = entry - max_sl_dist
                    sl_dist = max_sl_dist

                tp1 = entry + sl_dist * RR_TP1
                tp2 = min(entry + sl_dist * RR_TP2, yvah)
                if tp2 <= tp1:
                    tp2 = entry + sl_dist * RR_TP2

                trade_res = simulate_trade(curr_rates, i + 1, 'LONG', entry, sl_calc, tp1, tp2, is_gold)
                trade_res['day'] = curr_day
                trade_res['asset'] = asset
                trades.append(trade_res)
                day_traded = True
                continue

            # B. KÈO SELL XOAY TRỤC (Chỉ đánh khi KHÔNG bị ngược xu hướng ngày)
            upper_wick = h - max(o, cl)
            rejection_sell = (upper_wick >= 0.35 * candle_rng) and (h >= yvah - (1.2 if is_gold else 70.0)) and (cl <= yvah + (0.6 if is_gold else 30.0))

            if not daily_bull and (shape in ['P-Shape', 'D-Shape']) and rejection_sell and is_vol_spike:
                entry = cl
                sl_calc = h + sl_buf
                sl_dist = sl_calc - entry
                if sl_dist < min_sl_dist:
                    sl_calc = entry + min_sl_dist
                    sl_dist = min_sl_dist
                elif sl_dist > max_sl_dist:
                    sl_calc = entry + max_sl_dist
                    sl_dist = max_sl_dist

                tp1 = entry - sl_dist * RR_TP1
                tp2 = max(entry - sl_dist * RR_TP2, yval)
                if tp2 >= tp1:
                    tp2 = entry - sl_dist * RR_TP2

                trade_res = simulate_trade(curr_rates, i + 1, 'SHORT', entry, sl_calc, tp1, tp2, is_gold)
                trade_res['day'] = curr_day
                trade_res['asset'] = asset
                trades.append(trade_res)
                day_traded = True
                continue

    total_trades = len(trades)
    if total_trades == 0:
        print("⚠️ Không có lệnh nào thỏa mãn bộ lọc trong 1 tháng qua.")
        return

    wins_tp2 = len([t for t in trades if t['status'] == 'TP2'])
    wins_tp1_be = len([t for t in trades if t['status'] == 'BE_PROFIT'])
    losses = len([t for t in trades if t['status'] == 'SL'])
    total_wins = wins_tp2 + wins_tp1_be
    winrate = (total_wins / total_trades) * 100.0
    total_profit_pts = sum(t['profit_pts'] for t in trades)

    # Tính PnL tiền USD
    pnl_usd = 0.0
    for t in trades:
        if t['status'] == 'TP2':
            # Chốt 50% ở TP1 (1.2R -> 0.6R = $24), 50% ở TP2 (2.5R -> 1.25R = $50) -> +$74
            pnl_usd += RISK_PER_TRADE * (0.5 * RR_TP1 + 0.5 * RR_TP2)
        elif t['status'] == 'BE_PROFIT':
            # Chốt 50% ở TP1 (+0.6R = +$24), 50% hoà vốn ($0) -> +$24
            pnl_usd += RISK_PER_TRADE * (0.5 * RR_TP1)
        elif t['status'] == 'SL':
            # Cắt lỗ 1R -> -$40
            pnl_usd -= RISK_PER_TRADE
        capital += pnl_usd
        if capital > peak_capital:
            peak_capital = capital
        dd = (peak_capital - capital) / peak_capital * 100.0
        if dd > max_drawdown:
            max_drawdown = dd

    print(f"🎯 Tổng số kèo vào lệnh: {total_trades} kèo (~{total_trades / len(days_sorted) * 5:.1f} kèo/tuần)")
    print(f"🎉 Kèo chốt lời Full TP2:   {wins_tp2} kèo ({wins_tp2/total_trades*100:.1f}%)")
    print(f"🛡️ Kèo chốt TP1 + Hoà Vốn: {wins_tp1_be} kèo (Ăn 50% TP1, 50% bảo toàn vốn)")
    print(f"🛑 Kèo chạm Cắt Lỗ (SL):    {losses} kèo ({losses/total_trades*100:.1f}%)")
    print(f"🔥 TỶ LỆ THẮNG (WINRATE):   {winrate:.1f}%")
    print(f"📈 Tổng Điểm Lời:           {'+' if total_profit_pts >= 0 else ''}{total_profit_pts:,.2f} {unit}")
    print(f"💰 LỢI NHUẬN RÒNG (1 THÁNG): {'+' if pnl_usd >= 0 else ''}${pnl_usd:,.2f} ({'+' if pnl_usd >= 0 else ''}{pnl_usd/STARTING_CAPITAL*100:.1f}% vốn $2,000)")
    print(f"📉 Tụt Giảm Vốn Tối Đa (DD): {max_drawdown:.1f}%")
    print(f"{'='*60}")

    print("\n📜 CHI TIẾT CÁC KÈO TRONG 1 THÁNG:")
    for idx, t in enumerate(trades, 1):
        if t['status'] == 'TP2':
            st_str = "🎯 FULL TP2"
        elif t['status'] == 'BE_PROFIT':
            st_str = "🛡️ TP1 + BE (Có lãi)"
        else:
            st_str = "🛑 CHẠM SL"
        pts_str = f"+{t['profit_pts']:,.2f}" if t['profit_pts'] >= 0 else f"{t['profit_pts']:,.2f}"
        print(f"{idx:02d}. [{t['day']}] {t['signal']:<5} Entry: ${t['entry']:<9,.2f} | SL: ${t['sl']:<9,.2f} | TP1: ${t['tp1']:<9,.2f} ➔ {st_str} ({pts_str} {unit})")

def simulate_trade(rates, start_idx, signal, entry, sl, tp1, tp2, is_gold):
    tp1_hit = False
    curr_sl = sl

    for k in range(start_idx, min(start_idx + 180, len(rates))):
        r = rates[k]
        h = float(r['high'])
        l = float(r['low'])

        if signal == 'LONG':
            if not tp1_hit and h >= tp1:
                tp1_hit = True
                curr_sl = entry

            if tp1_hit and h >= tp2:
                return {
                    'signal': signal, 'entry': entry, 'sl': sl, 'tp1': tp1, 'tp2': tp2,
                    'status': 'TP2', 'profit_pts': round(abs(entry - tp2), 2)
                }

            if l <= curr_sl:
                if tp1_hit:
                    return {
                        'signal': signal, 'entry': entry, 'sl': sl, 'tp1': tp1, 'tp2': tp2,
                        'status': 'BE_PROFIT', 'profit_pts': round(abs(tp1 - entry) * 0.5, 2)
                    }
                else:
                    return {
                        'signal': signal, 'entry': entry, 'sl': sl, 'tp1': tp1, 'tp2': tp2,
                        'status': 'SL', 'profit_pts': -round(abs(entry - sl), 2)
                    }

        elif signal == 'SHORT':
            if not tp1_hit and l <= tp1:
                tp1_hit = True
                curr_sl = entry

            if tp1_hit and l <= tp2:
                return {
                    'signal': signal, 'entry': entry, 'sl': sl, 'tp1': tp1, 'tp2': tp2,
                    'status': 'TP2', 'profit_pts': round(abs(entry - tp2), 2)
                }

            if h >= curr_sl:
                if tp1_hit:
                    return {
                        'signal': signal, 'entry': entry, 'sl': sl, 'tp1': tp1, 'tp2': tp2,
                        'status': 'BE_PROFIT', 'profit_pts': round(abs(entry - tp1) * 0.5, 2)
                    }
                else:
                    return {
                        'signal': signal, 'entry': entry, 'sl': sl, 'tp1': tp1, 'tp2': tp2,
                        'status': 'SL', 'profit_pts': -round(abs(sl - entry), 2)
                    }

    last_cl = float(rates[-1]['close'])
    diff = (last_cl - entry) if signal == 'LONG' else (entry - last_cl)
    st = 'TP2' if diff > 0 else 'SL'
    return {
        'signal': signal, 'entry': entry, 'sl': sl, 'tp1': tp1, 'tp2': tp2,
        'status': st, 'profit_pts': round(diff, 2)
    }

if __name__ == '__main__':
    # Backtest 1 tháng Vàng (6000 nến M5)
    run_backtest_month('GOLD', 'XAUUSDc', count=6000)

    # Backtest 1 tháng Bitcoin (6000 nến M5)
    run_backtest_month('BTC', 'BTCUSDc', count=6000)
