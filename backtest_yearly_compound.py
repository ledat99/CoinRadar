"""
Engine Backtest Từng Tháng (Tháng 1 đến Tháng 11) - Đánh Lãi Kép Theo % Tài Khoản (Compounding)
Chiến lược: Scalping Volume Profile Ngày Hôm Trước M5 + Cột Tím VSA Wyckoff (Stopping Volume)
Nguồn dữ liệu: MetaTrader 5 (XAUUSDc & BTCUSDc)
"""

import MetaTrader5 as mt5
import numpy as np
import datetime
import time

STARTING_CAPITAL = 2000.0   # Vốn khởi điểm $2,000
RISK_PCT = 0.02            # Rủi ro 2.0% mỗi lệnh
RR_TP1 = 1.2               # TP1 R:R 1:1.2 (Chốt 50% & Dời Hoà BE)
RR_TP2 = 2.5               # TP2 R:R 1:2.5 (Chốt 50% còn lại)

def compute_volume_profile(rates, is_gold=True, n_bins=50):
    try:
        closes = np.array([r['close'] for r in rates])
        vols = np.array([r['tick_volume'] for r in rates])
        min_p = float(np.min([r['low'] for r in rates]))
        max_p = float(np.max([r['high'] for r in rates]))

        if max_p <= min_p:
            return None

        bin_size = (max_p - min_p) / n_bins
        if bin_size <= 0:
            return None

        bins_vol = np.zeros(n_bins)
        for cl, v in zip(closes, vols):
            idx = int((cl - min_p) / bin_size)
            idx = min(idx, n_bins - 1)
            bins_vol[idx] += v

        total_vol = np.sum(bins_vol)
        if total_vol <= 0:
            return None

        poc_idx = int(np.argmax(bins_vol))
        poc_price = min_p + (poc_idx + 0.5) * bin_size

        target_vol = total_vol * 0.70
        accum_vol = bins_vol[poc_idx]
        up_idx = poc_idx
        dn_idx = poc_idx

        while accum_vol < target_vol and (up_idx < n_bins - 1 or dn_idx > 0):
            next_up = bins_vol[up_idx + 1] if up_idx < n_bins - 1 else 0
            next_dn = bins_vol[dn_idx - 1] if dn_idx > 0 else 0

            if next_up >= next_dn and up_idx < n_bins - 1:
                up_idx += 1
                accum_vol += next_up
            elif dn_idx > 0:
                dn_idx -= 1
                accum_vol += next_dn
            else:
                break

        val_price = min_p + dn_idx * bin_size
        vah_price = min_p + (up_idx + 1) * bin_size

        mid_point = (max_p + min_p) / 2.0
        if poc_price > mid_point + (max_p - min_p) * 0.12:
            shape = "P-Shape"
        elif poc_price < mid_point - (max_p - min_p) * 0.12:
            shape = "L-Shape"
        else:
            shape = "D-Shape"

        return {
            'poc': poc_price,
            'val': val_price,
            'vah': vah_price,
            'shape': shape,
            'high': max_p,
            'low': min_p
        }
    except Exception:
        return None

def simulate_trade(rates, start_idx, signal, entry, sl, tp1, tp2):
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
                return 'TP2'

            if l <= curr_sl:
                return 'BE_PROFIT' if tp1_hit else 'SL'

        elif signal == 'SHORT':
            if not tp1_hit and l <= tp1:
                tp1_hit = True
                curr_sl = entry

            if tp1_hit and l <= tp2:
                return 'TP2'

            if h >= curr_sl:
                return 'BE_PROFIT' if tp1_hit else 'SL'

    last_cl = float(rates[-1]['close'])
    diff = (last_cl - entry) if signal == 'LONG' else (entry - last_cl)
    return 'TP2' if diff > 0 else 'SL'

def run_yearly_compound_backtest(asset='GOLD', symbol='XAUUSDc'):
    is_gold = (asset == 'GOLD')
    sym_name = "🥇 VÀNG (XAUUSD - Chuẩn MT5)" if is_gold else "👑 BITCOIN (BTCUSD - Chuẩn MT5)"
    min_sl_dist = 5.5 if is_gold else 250.0
    max_sl_dist = 9.5 if is_gold else 420.0
    sl_buf = 0.8 if is_gold else 35.0

    print(f"\n{'='*75}")
    print(f"🚀 CHẠY BACKTEST LÃI KÉP THEO THÁNG (TỪ THÁNG 1 ĐẾN THÁNG 11/2026)")
    print(f"📊 Tài sản: {sym_name} | Vốn khởi điểm: ${STARTING_CAPITAL:,.2f} | Rủi ro: {RISK_PCT*100:.1f}%/kèo")
    print(f"{'='*75}")

    if not mt5.initialize():
        print("❌ Không thể kết nối MT5 terminal!")
        return

    utc_from = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
    utc_to = datetime.datetime.now(datetime.timezone.utc)
    rates = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_M5, utc_from, utc_to)
    mt5.shutdown()

    if rates is None or len(rates) == 0:
        print(f"❌ Không tải được dữ liệu nến cho {symbol}")
        return

    print(f"📦 Đã nạp thành công {len(rates):,} nến M5 thực tế từ Broker MT5.")

    # Gom nến theo ngày
    daily_groups = {}
    for r in rates:
        dt = datetime.datetime.fromtimestamp(r['time'], datetime.timezone.utc)
        day_str = dt.strftime('%Y-%m-%d')
        if day_str not in daily_groups:
            daily_groups[day_str] = []
        daily_groups[day_str].append(r)

    days_sorted = sorted(daily_groups.keys())
    print(f"📅 Số ngày giao dịch ghi nhận: {len(days_sorted)} ngày")

    all_trades = []
    current_capital = STARTING_CAPITAL
    peak_capital = current_capital
    overall_max_dd = 0.0

    # Quét qua từng ngày
    for d_idx in range(1, len(days_sorted)):
        prev_day = days_sorted[d_idx - 1]
        curr_day = days_sorted[d_idx]

        prev_rates = daily_groups[prev_day]
        curr_rates = daily_groups[curr_day]

        vp = compute_volume_profile(prev_rates, is_gold)
        if not vp:
            continue

        ypoc = vp['poc']
        yval = vp['val']
        yvah = vp['vah']
        shape = vp['shape']

        # Xu hướng ngày hôm trước (Trend Filter)
        prev_open = float(prev_rates[0]['open'])
        prev_close = float(prev_rates[-1]['close'])
        daily_bull = (prev_close > prev_open) and (prev_close > ypoc)
        daily_bear = (prev_close < prev_open) and (prev_close < ypoc)

        day_traded = False

        for i in range(20, len(curr_rates)):
            if day_traded:
                break

            r = curr_rates[i]
            o = float(r['open'])
            h = float(r['high'])
            l = float(r['low'])
            cl = float(r['close'])
            v = float(r['tick_volume'])

            candle_rng = h - l
            if candle_rng == 0:
                continue

            past_vols = [float(curr_rates[k]['tick_volume']) for k in range(i - 20, i)]
            avg_vol = np.mean(past_vols) if past_vols else 1.0
            vol_ratio = v / avg_vol if avg_vol > 0 else 1.0

            lower_wick = min(o, cl) - l
            upper_wick = h - max(o, cl)

            # Chuẩn VSA Cột Tím Wyckoff (Ultra-High / Stopping Volume)
            is_purple_vol = (vol_ratio >= 1.80) or (vol_ratio >= 1.60 and max(lower_wick, upper_wick) >= 0.48 * candle_rng)

            # A. KÈO BUY XOAY TRỤC
            rejection_buy = (lower_wick >= 0.40 * candle_rng) and (l <= yval + (1.2 if is_gold else 70.0)) and (cl >= yval - (0.6 if is_gold else 30.0))
            if not daily_bear and (shape in ['L-Shape', 'D-Shape']) and rejection_buy and is_purple_vol:
                entry = cl
                sl_calc = l - sl_buf
                sl_dist = entry - sl_calc
                sl_dist = max(min_sl_dist, min(max_sl_dist, sl_dist))
                sl_calc = entry - sl_dist
                tp1 = entry + sl_dist * RR_TP1
                tp2 = min(entry + sl_dist * RR_TP2, yvah)
                if tp2 <= tp1:
                    tp2 = entry + sl_dist * RR_TP2

                st = simulate_trade(curr_rates, i + 1, 'LONG', entry, sl_calc, tp1, tp2)

                # Tính PnL theo Lãi Kép (% Tài khoản hiện tại)
                risk_usd = current_capital * RISK_PCT
                if st == 'TP2':
                    pnl_usd = risk_usd * (0.5 * RR_TP1 + 0.5 * RR_TP2) # +3.7% vốn
                elif st == 'BE_PROFIT':
                    pnl_usd = risk_usd * (0.5 * RR_TP1)                 # +1.2% vốn
                else:
                    pnl_usd = -risk_usd                                 # -2.0% vốn

                current_capital += pnl_usd
                if current_capital > peak_capital:
                    peak_capital = current_capital
                dd = (peak_capital - current_capital) / peak_capital * 100.0
                if dd > overall_max_dd:
                    overall_max_dd = dd

                all_trades.append({
                    'day': curr_day,
                    'month': curr_day[:7],
                    'signal': 'LONG',
                    'entry': entry,
                    'sl': sl_calc,
                    'tp1': tp1,
                    'tp2': tp2,
                    'vol_ratio': round(vol_ratio, 2),
                    'status': st,
                    'pnl_usd': pnl_usd,
                    'pnl_pct': (pnl_usd / (current_capital - pnl_usd)) * 100.0,
                    'balance': current_capital
                })
                day_traded = True
                continue

            # B. KÈO SELL XOAY TRỤC
            rejection_sell = (upper_wick >= 0.40 * candle_rng) and (h >= yvah - (1.2 if is_gold else 70.0)) and (cl <= yvah + (0.6 if is_gold else 30.0))
            if not daily_bull and (shape in ['P-Shape', 'D-Shape']) and rejection_sell and is_purple_vol:
                entry = cl
                sl_calc = h + sl_buf
                sl_dist = sl_calc - entry
                sl_dist = max(min_sl_dist, min(max_sl_dist, sl_dist))
                sl_calc = entry + sl_dist
                tp1 = entry - sl_dist * RR_TP1
                tp2 = max(entry - sl_dist * RR_TP2, yval)
                if tp2 >= tp1:
                    tp2 = entry - sl_dist * RR_TP2

                st = simulate_trade(curr_rates, i + 1, 'SHORT', entry, sl_calc, tp1, tp2)

                risk_usd = current_capital * RISK_PCT
                if st == 'TP2':
                    pnl_usd = risk_usd * (0.5 * RR_TP1 + 0.5 * RR_TP2)
                elif st == 'BE_PROFIT':
                    pnl_usd = risk_usd * (0.5 * RR_TP1)
                else:
                    pnl_usd = -risk_usd

                current_capital += pnl_usd
                if current_capital > peak_capital:
                    peak_capital = current_capital
                dd = (peak_capital - current_capital) / peak_capital * 100.0
                if dd > overall_max_dd:
                    overall_max_dd = dd

                all_trades.append({
                    'day': curr_day,
                    'month': curr_day[:7],
                    'signal': 'SHORT',
                    'entry': entry,
                    'sl': sl_calc,
                    'tp1': tp1,
                    'tp2': tp2,
                    'vol_ratio': round(vol_ratio, 2),
                    'status': st,
                    'pnl_usd': pnl_usd,
                    'pnl_pct': (pnl_usd / (current_capital - pnl_usd)) * 100.0,
                    'balance': current_capital
                })
                day_traded = True
                continue

    # Tổng hợp kết quả theo từng tháng
    all_months = [f"2026-{m:02d}" for m in range(1, 12)]
    month_stats = {}
    for m in all_months:
        month_stats[m] = {
            'trades': [],
            'wins_tp2': 0,
            'wins_be': 0,
            'losses': 0,
            'pnl_usd': 0.0,
            'start_cap': 0.0,
            'end_cap': 0.0
        }

    running_cap = STARTING_CAPITAL
    for m in all_months:
        m_trades = [t for t in all_trades if t['month'] == m]
        month_stats[m]['start_cap'] = running_cap
        month_stats[m]['trades'] = m_trades
        for t in m_trades:
            month_stats[m]['pnl_usd'] += t['pnl_usd']
            if t['status'] == 'TP2':
                month_stats[m]['wins_tp2'] += 1
            elif t['status'] == 'BE_PROFIT':
                month_stats[m]['wins_be'] += 1
            else:
                month_stats[m]['losses'] += 1
            running_cap = t['balance']
        month_stats[m]['end_cap'] = running_cap

    # IN BẢNG BÁO CÁO CHI TIẾT THEO TỪNG THÁNG
    print(f"\n📊 BẢNG TỔNG KẾT HIỆU QUẢ THEO TỪNG THÁNG (TỪ THÁNG 1 ĐẾN THÁNG 11):")
    print(f"{'-'*92}")
    print(f"{'Tháng':<10} | {'Số Kèo':<7} | {'Full TP2':<8} | {'TP1+BE':<7} | {'Dính SL':<7} | {'Winrate':<8} | {'PnL Tháng ($)':<14} | {'Vốn Cuối Tháng':<14} | {'Tăng Trưởng':<11}")
    print(f"{'-'*92}")

    for m in all_months:
        st = month_stats[m]
        tot = len(st['trades'])
        wr = ((st['wins_tp2'] + st['wins_be']) / tot * 100.0) if tot > 0 else 0.0
        growth_pct = ((st['end_cap'] - st['start_cap']) / st['start_cap'] * 100.0) if st['start_cap'] > 0 else 0.0
        pnl_str = f"{'+' if st['pnl_usd'] >= 0 else ''}${st['pnl_usd']:,.2f}"
        grow_str = f"{'+' if growth_pct >= 0 else ''}{growth_pct:.2f}%"

        print(f"{m:<10} | {tot:<7} | {st['wins_tp2']:<8} | {st['wins_be']:<7} | {st['losses']:<7} | {wr:<7.1f}% | {pnl_str:<14} | ${st['end_cap']:<13,.2f} | {grow_str:<11}")

    print(f"{'-'*92}")

    # TỔNG KẾT TOÀN KỲ 11 THÁNG
    total_trades_all = len(all_trades)
    tp2_all = len([t for t in all_trades if t['status'] == 'TP2'])
    be_all = len([t for t in all_trades if t['status'] == 'BE_PROFIT'])
    sl_all = len([t for t in all_trades if t['status'] == 'SL'])
    total_wins_all = tp2_all + be_all
    overall_wr = (total_wins_all / total_trades_all * 100.0) if total_trades_all > 0 else 0.0
    net_profit = current_capital - STARTING_CAPITAL
    roi_pct = (net_profit / STARTING_CAPITAL) * 100.0

    print(f"\n🏆 TỔNG KẾT TOÀN DIỆN 11 THÁNG (LÃI KÉP % VỐN TÀI KHOẢN):")
    print(f"💰 Vốn ban đầu (Tháng 1/2026):   ${STARTING_CAPITAL:,.2f}")
    print(f"💵 Vốn hiện tại (Tháng 11/2026):  ${current_capital:,.2f}")
    print(f"📈 Tổng lợi nhuận ròng (Net):     {'+' if net_profit >= 0 else ''}${net_profit:,.2f} ({'+' if roi_pct >= 0 else ''}{roi_pct:.2f}%)")
    print(f"🎯 Tổng số kèo giao dịch:         {total_trades_all} kèo (~{total_trades_all / 11:.1f} kèo/tháng)")
    print(f"🎉 Số kèo Full TP2:              {tp2_all} kèo ({tp2_all/total_trades_all*100:.1f}%)" if total_trades_all else "")
    print(f"🛡️ Số kèo chốt TP1 + Hoà Vốn:    {be_all} kèo ({be_all/total_trades_all*100:.1f}%)" if total_trades_all else "")
    print(f"🛑 Số kèo chạm Cắt Lỗ (SL):       {sl_all} kèo ({sl_all/total_trades_all*100:.1f}%)" if total_trades_all else "")
    print(f"🔥 Tỷ lệ Thắng Tổng Thể:          {overall_wr:.1f}%")
    print(f"📉 Tụt giảm vốn tối đa (Max DD):  {overall_max_dd:.2f}%")
    print(f"{'='*75}\n")

    return {
        'asset': asset,
        'start_cap': STARTING_CAPITAL,
        'end_cap': current_capital,
        'net_profit': net_profit,
        'roi_pct': roi_pct,
        'total_trades': total_trades_all,
        'winrate': overall_wr,
        'max_dd': overall_max_dd,
        'month_stats': month_stats
    }

if __name__ == '__main__':
    # Chạy Vàng
    run_yearly_compound_backtest('GOLD', 'XAUUSDc')
    # Chạy Bitcoin
    run_yearly_compound_backtest('BTC', 'BTCUSDc')

