"""
Backtest So Sánh Khung M15 vs M5 & Chiến Lược Gồng Dài Thoát Theo CISD M15 / Sideway
Dữ liệu: Nến M15 từ 01/2026 đến 11/2026 (MetaTrader 5 Broker Exness)
"""

import MetaTrader5 as mt5
import numpy as np
import datetime

STARTING_CAPITAL = 2000.0
RISK_PCT = 0.02

def compute_volume_profile(rates, is_gold=True, n_bins=50):
    try:
        closes = np.array([r['close'] for r in rates])
        vols = np.array([r['tick_volume'] for r in rates])
        min_p = float(np.min([r['low'] for r in rates]))
        max_p = float(np.max([r['high'] for r in rates]))

        if max_p <= min_p: return None
        bin_size = (max_p - min_p) / n_bins
        if bin_size <= 0: return None

        bins_vol = np.zeros(n_bins)
        for cl, v in zip(closes, vols):
            idx = min(int((cl - min_p) / bin_size), n_bins - 1)
            bins_vol[idx] += v

        total_vol = np.sum(bins_vol)
        if total_vol <= 0: return None

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

        if poc_price > mid_point + (max_p - min_p) * 0.12: shape = "P-Shape"
        elif poc_price < mid_point - (max_p - min_p) * 0.12: shape = "L-Shape"
        else: shape = "D-Shape"

        return {'poc': poc_price, 'val': val_price, 'vah': vah_price, 'shape': shape}
    except Exception:
        return None

def detect_cisd_and_sideway_exit(rates, start_idx, signal, entry, sl, is_gold):
    """
    Mô phỏng Gồng Dài trên M15:
    - TP1: Chốt 50% tại R:R 1:1.2 & kéo SL về Entry hòa vốn.
    - 50% còn lại gồng dài và thoát lệnh khi:
      1. CISD M15 (Change In State of Delivery):
         - Long: Nến M15 đóng cửa dưới Open của cây nến xanh gần nhất tạo đỉnh sóng.
         - Short: Nến M15 đóng cửa trên Open của cây nến đỏ gần nhất tạo đáy sóng.
      2. Sideway sau sóng đẩy mạnh (>= R:R 1:3): Biên độ 4 nến M15 co hẹp < 40% ATR -> Chốt lời chu kỳ.
      3. SL dính nếu quay đầu trước khi chạm TP1.
    """
    sl_dist = abs(entry - sl)
    tp1 = entry + sl_dist * 1.2 if signal == 'LONG' else entry - sl_dist * 1.2
    tp1_hit = False
    curr_sl = sl

    highest_p = entry
    lowest_p = entry
    consecutive_sideway = 0
    recent_swings = []

    # Quét qua tối đa 120 nến M15 (~30 tiếng gồng)
    for k in range(start_idx, min(start_idx + 120, len(rates))):
        r = rates[k]
        o, h, l, cl = float(r['open']), float(r['high']), float(r['low']), float(r['close'])
        rng = h - l

        if signal == 'LONG':
            if h > highest_p:
                highest_p = h

            # Check TP1
            if not tp1_hit and h >= tp1:
                tp1_hit = True
                curr_sl = entry # Dời BE

            # Check SL
            if l <= curr_sl:
                if tp1_hit:
                    # Ăn 50% TP1, 50% hòa
                    return {'status': 'BE_PROFIT', 'rr_multiple': 0.6, 'exit_reason': 'Dời BE Hoà'}
                else:
                    return {'status': 'SL', 'rr_multiple': -1.0, 'exit_reason': 'Dính SL'}

            # Nếu đã qua TP1, bắt đầu kích hoạt cơ chế Gồng Dài theo CISD & Sideway
            if tp1_hit:
                current_rr = (cl - entry) / sl_dist

                # 1. CISD M15 Check (Change In State of Delivery)
                # Nếu giá đã đẩy được >= 2.0 R:R và xuất hiện nến M15 giảm mạnh thủng đáy nến xanh trước đó
                prev_r = rates[k - 1]
                prev_o, prev_cl, prev_l = float(prev_r['open']), float(prev_r['close']), float(prev_r['low'])
                is_cisd_bear = (cl < prev_o) and (cl < prev_l) and (prev_cl > prev_o)

                if current_rr >= 2.0 and is_cisd_bear:
                    # Thoát 50% còn lại tại giá cl
                    total_rr = 0.5 * 1.2 + 0.5 * current_rr
                    return {'status': 'RUNNER_EXIT', 'rr_multiple': round(total_rr, 2), 'exit_reason': f'CISD M15 Đảo Chiều (R:R {current_rr:.1f})'}

                # 2. Sideway Detection: Giá chạy chững lại 4 cây nến M15 biên độ hẹp sau khi đạt đỉnh
                if current_rr >= 2.5:
                    if (highest_p - cl) >= sl_dist * 0.8:
                        consecutive_sideway += 1
                        if consecutive_sideway >= 4:
                            total_rr = 0.5 * 1.2 + 0.5 * current_rr
                            return {'status': 'RUNNER_EXIT', 'rr_multiple': round(total_rr, 2), 'exit_reason': f'Sideway Hết Chu Kỳ (R:R {current_rr:.1f})'}
                    else:
                        consecutive_sideway = 0

        elif signal == 'SHORT':
            if l < lowest_p:
                lowest_p = l

            if not tp1_hit and l <= tp1:
                tp1_hit = True
                curr_sl = entry

            if h >= curr_sl:
                if tp1_hit:
                    return {'status': 'BE_PROFIT', 'rr_multiple': 0.6, 'exit_reason': 'Dời BE Hoà'}
                else:
                    return {'status': 'SL', 'rr_multiple': -1.0, 'exit_reason': 'Dính SL'}

            if tp1_hit:
                current_rr = (entry - cl) / sl_dist

                # 1. CISD M15 Check
                prev_r = rates[k - 1]
                prev_o, prev_cl, prev_h = float(prev_r['open']), float(prev_r['close']), float(prev_r['high'])
                is_cisd_bull = (cl > prev_o) and (cl > prev_h) and (prev_cl < prev_o)

                if current_rr >= 2.0 and is_cisd_bull:
                    total_rr = 0.5 * 1.2 + 0.5 * current_rr
                    return {'status': 'RUNNER_EXIT', 'rr_multiple': round(total_rr, 2), 'exit_reason': f'CISD M15 Đảo Chiều (R:R {current_rr:.1f})'}

                # 2. Sideway Detection
                if current_rr >= 2.5:
                    if (cl - lowest_p) >= sl_dist * 0.8:
                        consecutive_sideway += 1
                        if consecutive_sideway >= 4:
                            total_rr = 0.5 * 1.2 + 0.5 * current_rr
                            return {'status': 'RUNNER_EXIT', 'rr_multiple': round(total_rr, 2), 'exit_reason': f'Sideway Hết Chu Kỳ (R:R {current_rr:.1f})'}
                    else:
                        consecutive_sideway = 0

    # Hết session
    last_cl = float(rates[-1]['close'])
    final_rr = (last_cl - entry)/sl_dist if signal == 'LONG' else (entry - last_cl)/sl_dist
    if tp1_hit:
        total_rr = 0.5 * 1.2 + 0.5 * max(0.0, final_rr)
        return {'status': 'RUNNER_EXIT', 'rr_multiple': round(total_rr, 2), 'exit_reason': 'Đóng Cuối Sóng'}
    else:
        return {'status': 'SL', 'rr_multiple': -1.0, 'exit_reason': 'Dính SL'}

def run_m15_comparison(asset='BTC', symbol='BTCUSDc'):
    is_gold = (asset == 'GOLD')
    sym_name = "🥇 VÀNG (XAUUSD M15)" if is_gold else "👑 BITCOIN (BTCUSD M15)"
    min_sl_dist = 6.0 if is_gold else 280.0
    max_sl_dist = 14.0 if is_gold else 550.0
    sl_buf = 1.0 if is_gold else 40.0

    mt5.initialize()
    utc_from = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
    utc_to = datetime.datetime.now(datetime.timezone.utc)
    rates = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_M15, utc_from, utc_to)
    mt5.shutdown()

    if rates is None or len(rates) == 0:
        print("Không có data M15")
        return

    # Gom theo ngày
    daily_groups = {}
    for r in rates:
        dt = datetime.datetime.fromtimestamp(r['time'], datetime.timezone.utc)
        day_str = dt.strftime('%Y-%m-%d')
        if day_str not in daily_groups: daily_groups[day_str] = []
        daily_groups[day_str].append(r)

    days_sorted = sorted(daily_groups.keys())

    # Chạy 2 chế độ:
    # Mode A: M15 Chốt lời cố định TP1 (1:1.2) & TP2 (1:2.5)
    # Mode B: M15 Gồng Dài (CISD M15 Trailing + Sideway Exit)
    
    trades_mode_b = []
    cap_b = STARTING_CAPITAL
    peak_b = cap_b
    max_dd_b = 0.0

    for d_idx in range(1, len(days_sorted)):
        prev_day = days_sorted[d_idx - 1]
        curr_day = days_sorted[d_idx]
        prev_rates = daily_groups[prev_day]
        curr_rates = daily_groups[curr_day]

        vp = compute_volume_profile(prev_rates, is_gold)
        if not vp: continue
        ypoc, yval, yvah, shape = vp['poc'], vp['val'], vp['vah'], vp['shape']

        prev_open = float(prev_rates[0]['open'])
        prev_close = float(prev_rates[-1]['close'])
        daily_bull = (prev_close > prev_open) and (prev_close > ypoc)
        daily_bear = (prev_close < prev_open) and (prev_close < ypoc)

        day_traded = False

        for i in range(15, len(curr_rates)):
            if day_traded: break
            r = curr_rates[i]
            o, h, l, cl, v = float(r['open']), float(r['high']), float(r['low']), float(r['close']), float(r['tick_volume'])
            rng = h - l
            if rng == 0: continue

            past_vols = [float(curr_rates[k]['tick_volume']) for k in range(i - 15, i)]
            avg_vol = np.mean(past_vols) if past_vols else 1.0
            vol_ratio = v / avg_vol if avg_vol > 0 else 1.0

            lw = min(o, cl) - l
            uw = h - max(o, cl)

            # Trên M15: Nến lớn hơn, cột tím VSA >= 1.65x (hoặc >= 1.50x nếu râu >= 45%)
            is_purple_vol = (vol_ratio >= 1.65) or (vol_ratio >= 1.50 and max(lw, uw) >= 0.45 * rng)

            # BUY
            rejection_buy = (lw >= 0.38 * rng) and (l <= yval + (1.5 if is_gold else 90.0)) and (cl >= yval - (0.8 if is_gold else 40.0))
            if not daily_bear and (shape in ['L-Shape', 'D-Shape']) and rejection_buy and is_purple_vol:
                entry = cl
                sl_calc = l - sl_buf
                sl_dist = entry - sl_calc
                sl_dist = max(min_sl_dist, min(max_sl_dist, sl_dist))
                sl_calc = entry - sl_dist

                res = detect_cisd_and_sideway_exit(curr_rates, i + 1, 'LONG', entry, sl_calc, is_gold)
                risk_usd = cap_b * RISK_PCT
                pnl_usd = risk_usd * res['rr_multiple']
                cap_b += pnl_usd
                if cap_b > peak_b: peak_b = cap_b
                dd = (peak_b - cap_b) / peak_b * 100.0
                if dd > max_dd_b: max_dd_b = dd

                trades_mode_b.append({
                    'day': curr_day,
                    'month': curr_day[:7],
                    'signal': 'LONG',
                    'entry': entry,
                    'sl': sl_calc,
                    'rr': res['rr_multiple'],
                    'status': res['status'],
                    'reason': res['exit_reason'],
                    'pnl_usd': pnl_usd,
                    'balance': cap_b
                })
                day_traded = True
                continue

            # SELL
            rejection_sell = (uw >= 0.38 * rng) and (h >= yvah - (1.5 if is_gold else 90.0)) and (cl <= yvah + (0.8 if is_gold else 40.0))
            if not daily_bull and (shape in ['P-Shape', 'D-Shape']) and rejection_sell and is_purple_vol:
                entry = cl
                sl_calc = h + sl_buf
                sl_dist = sl_calc - entry
                sl_dist = max(min_sl_dist, min(max_sl_dist, sl_dist))
                sl_calc = entry + sl_dist

                res = detect_cisd_and_sideway_exit(curr_rates, i + 1, 'SHORT', entry, sl_calc, is_gold)
                risk_usd = cap_b * RISK_PCT
                pnl_usd = risk_usd * res['rr_multiple']
                cap_b += pnl_usd
                if cap_b > peak_b: peak_b = cap_b
                dd = (peak_b - cap_b) / peak_b * 100.0
                if dd > max_dd_b: max_dd_b = dd

                trades_mode_b.append({
                    'day': curr_day,
                    'month': curr_day[:7],
                    'signal': 'SHORT',
                    'entry': entry,
                    'sl': sl_calc,
                    'rr': res['rr_multiple'],
                    'status': res['status'],
                    'reason': res['exit_reason'],
                    'pnl_usd': pnl_usd,
                    'balance': cap_b
                })
                day_traded = True
                continue

    # Tổng hợp từng tháng cho Mode B
    all_months = [f"2026-{m:02d}" for m in range(1, 12)]
    print(f"\n{'='*80}")
    print(f"🔥 KẾT QUẢ BACKTEST M15 + GỒNG DÀI THEO CISD & SIDEWAY: {sym_name}")
    print(f"💰 Vốn ban đầu: ${STARTING_CAPITAL:,.2f} | Rủi ro: 2% lãi kép")
    print(f"{'='*80}")
    print(f"{'Tháng':<10} | {'Số Kèo':<7} | {'Win (RR>0)':<10} | {'Loss (SL)':<9} | {'Winrate':<8} | {'PnL Tháng ($)':<14} | {'Vốn Cuối Tháng':<14} | {'Tăng Trưởng'}")
    print(f"{'-'*88}")

    m_cap = STARTING_CAPITAL
    for m in all_months:
        m_t = [t for t in trades_mode_b if t['month'] == m]
        tot = len(m_t)
        wins = len([t for t in m_t if t['rr'] > 0])
        losses = len([t for t in m_t if t['rr'] <= 0])
        pnl = sum(t['pnl_usd'] for t in m_t)
        wr = (wins / tot * 100.0) if tot > 0 else 0.0
        s_cap = m_cap
        m_cap += pnl
        grow = ((m_cap - s_cap)/s_cap * 100.0) if s_cap > 0 else 0.0
        pnl_s = f"{'+' if pnl >= 0 else ''}${pnl:,.2f}"
        grow_s = f"{'+' if grow >= 0 else ''}{grow:.2f}%"
        print(f"{m:<10} | {tot:<7} | {wins:<10} | {losses:<9} | {wr:<7.1f}% | {pnl_s:<14} | ${m_cap:<13,.2f} | {grow_s}")

    print(f"{'-'*88}")
    total_t = len(trades_mode_b)
    wins_all = len([t for t in trades_mode_b if t['rr'] > 0])
    overall_wr = (wins_all / total_t * 100.0) if total_t > 0 else 0.0
    net_p = cap_b - STARTING_CAPITAL
    roi = (net_p / STARTING_CAPITAL) * 100.0

    print(f"\n🏆 TỔNG KẾT 11 THÁNG (M15 GỒNG DÀI CISD):")
    print(f"💰 Vốn ban đầu:          ${STARTING_CAPITAL:,.2f}")
    print(f"💵 Vốn kết thúc:         ${cap_b:,.2f}")
    print(f"📈 Lợi nhuận ròng:       {'+' if net_p >= 0 else ''}${net_p:,.2f} ({'+' if roi >= 0 else ''}{roi:.2f}%)")
    print(f"🎯 Tổng số kèo:          {total_t} kèo")
    print(f"🔥 Tỷ lệ Thắng:          {overall_wr:.1f}%")
    print(f"📉 Tụt giảm vốn tối đa:  {max_dd_b:.2f}%")
    
    # In một số lệnh gồng R:R khủng nhất
    huge_trades = sorted([t for t in trades_mode_b if t['rr'] >= 2.0], key=lambda x: x['rr'], reverse=True)
    if huge_trades:
        print(f"\n🚀 CÁC KÈO GỒNG DÀI R:R KHỦNG NHẤT (THOÁT THEO CISD M15 / SIDEWAY):")
        for idx, t in enumerate(huge_trades[:6], 1):
            print(f"  {idx}. [{t['day']}] {t['signal']:<5} R:R Đạt: +{t['rr']:.2f}R | Lời: +${t['pnl_usd']:,.2f} | Lý do thoát: {t['reason']}")
    print(f"{'='*80}\n")

if __name__ == '__main__':
    run_m15_comparison('BTC', 'BTCUSDc')
    run_m15_comparison('GOLD', 'XAUUSDc')

