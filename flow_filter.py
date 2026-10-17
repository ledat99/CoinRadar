"""
flow_filter.py — Tính & lọc dòng tiền Inflow/Outflow trên Binance Futures,
tương đương bảng "Impossible Cloud Network" của CoinGlass mà user gửi.

Cách tính:
  - Lấy 144 nến 5m (12 giờ) từ endpoint https://fapi.binance.com/fapi/v1/klines
  - Mỗi candle có sẵn:
        * quoteVolume         = tổng giá trị giao dịch
        * taker_buy_quote_volume = tổng giá trị lệnh taker MUA
    => Inflow  = taker_buy_quote_volume
       Outflow = quoteVolume - taker_buy_quote_volume
       Net     = Inflow - Outflow

Khung thời gian: 5m / 15m / 30m / 1h / 4h / 8h / 12h (ghép từ nhiều nến 5m).
"""

import requests
import pandas as pd

# ---------------------------------------------------------------------------
# CẤU HÌNH — chỉnh tại đây nếu muốn nới / siết bộ lọc
# ---------------------------------------------------------------------------
FUTURES_BASE = 'https://fapi.binance.com'
KLINES_ENDPOINT = '/fapi/v1/klines'
REQUEST_TIMEOUT = 10
SCAN_INTERVAL = '5m'
SCAN_LIMIT = 144  # 144 * 5m = 12 giờ

# Ngưỡng đánh giá
SHORT_TF_MIN_PCT = -30   # 5m net_pct_change > ngưỡng này → không bị dump
DUMP_PCT_THRESHOLD = -50 # 5m pct < ngưỡng này → trừ điểm mạnh

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_futures_symbol(symbol: str) -> str:
    """Chuẩn hoá 'BTC/USDT:USDT' / 'BTC/USDT' → 'BTCUSDT' cho endpoint Futures."""
    if not symbol:
        return ''
    s = symbol.replace('/', '').replace(':USDT', '').replace(':USDC', '')
    return s


def fetch_klines_with_taker(symbol: str, interval: str = SCAN_INTERVAL,
                            limit: int = SCAN_LIMIT) -> pd.DataFrame | None:
    """Gọi fapi.binance.com và trả về DataFrame có cột `quote_volume`, `taker_buy_quote`."""
    fapi_symbol = _to_futures_symbol(symbol)
    params = {'symbol': fapi_symbol, 'interval': interval, 'limit': limit}
    url = FUTURES_BASE + KLINES_ENDPOINT
    try:
        r = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        if r.status_code != 200:
            return None
        data = r.json()
        if not isinstance(data, list) or not data:
            return None
        rows = []
        for c in data:
            rows.append({
                'open_time':   int(c[0]),
                'open':        float(c[1]),
                'high':        float(c[2]),
                'low':         float(c[3]),
                'close':       float(c[4]),
                'volume':      float(c[5]),         # base volume
                'quote_volume':     float(c[7]),    # quote volume (tổng)
                'count':             int(c[8]),
                'taker_buy_base':    float(c[9]),   # base bought by taker
                'taker_buy_quote':   float(c[10]),  # quote bought by taker
            })
        df = pd.DataFrame(rows)
        df['open_time'] = pd.to_datetime(df['open_time'], unit='ms')
        return df
    except Exception as e:
        print(f"Lỗi fetch klines {symbol}: {e}")
        return None


def compute_inflow_outflow(df: pd.DataFrame, last_n_candles: int) -> dict | None:
    """Tính inflow/outflow cho N nến gần nhất.
    Trả về: {'inflow': USD, 'outflow': USD, 'net': USD, 'pct': float}
      pct = % thay đổi của net so với N nến liền trước (giống cột "%" CoinGlass).
    """
    if df is None or df.empty:
        return None
    need = last_n_candles * 2  # cần đủ 2 đoạn để tính % thay đổi
    if len(df) < need:
        return None

    cur = df.tail(last_n_candles)
    prev = df.iloc[-(last_n_candles * 2):-last_n_candles]

    def summarize(part: pd.DataFrame) -> tuple:
        inflow = float(part['taker_buy_quote'].sum())
        total  = float(part['quote_volume'].sum())
        outflow = total - inflow
        net = inflow - outflow
        return inflow, outflow, net

    inflow, outflow, net = summarize(cur)
    _, _, prev_net = summarize(prev)

    if prev_net != 0:
        pct = (net - prev_net) / abs(prev_net) * 100.0
    elif net != 0:
        pct = 100.0 if net > 0 else -100.0
    else:
        pct = 0.0

    return {
        'inflow':  inflow,
        'outflow': outflow,
        'net':     net,
        'pct':     pct,
    }


# ---------------------------------------------------------------------------
# API chính
# ---------------------------------------------------------------------------

# Số nến 5m cho mỗi khung thời gian
CANDLES_PER_BUCKET = {
    '5m':  1,
    '15m': 3,
    '30m': 6,
    '1h':  12,
    '4h':  48,
    '8h':  96,
    '12h': 144,
}


def get_flow_snapshot(symbol: str) -> dict | None:
    """Lấy snapshot dòng tiền 7 khung: 5m / 15m / 30m / 1h / 4h / 8h / 12h.

    Trả về dict:
      {
        '5m':  {'inflow','outflow','net','pct'},
        '15m': {...},
        ...
        '12h': {...},
        'summary': {
            'long_term_positive': bool,         # (4h, 8h, 12h) đều net > 0
            'short_term_not_dump': bool,        # 5m pct > SHORT_TF_MIN_PCT
            'momentum_aligned_positive': bool,  # 30m và 1h đều net > 0
            'momentum_aligned_negative': bool,  # 30m và 1h đều net < 0
            'score': float,                     # 0..100
            'long_positive_count': int,         # bao nhiêu khung dài dương
        }
      }
    Hoặc None nếu fetch thất bại.
    """
    df = fetch_klines_with_taker(symbol)
    if df is None or len(df) < SCAN_LIMIT:
        return None

    snapshot: dict = {}
    for tf, n in CANDLES_PER_BUCKET.items():
        snap = compute_inflow_outflow(df, n)
        if snap:
            snapshot[tf] = snap

    if '12h' not in snapshot:
        return None

    long_tfs = ['4h', '8h', '12h']
    long_pos = sum(1 for tf in long_tfs if snapshot.get(tf, {}).get('net', 0) > 0)
    long_term_positive = (long_pos == len(long_tfs))

    five_m = snapshot.get('5m', {'pct': 0})
    short_term_not_dump = five_m.get('pct', 0) > SHORT_TF_MIN_PCT

    thirty_m = snapshot.get('30m', {'net': 0})
    one_h    = snapshot.get('1h',  {'net': 0})
    momentum_aligned_positive = (thirty_m['net'] > 0) and (one_h['net'] > 0)
    momentum_aligned_negative = (thirty_m['net'] < 0) and (one_h['net'] < 0)

    # --- ĐIỂM 0..100 ---
    score = 0
    if long_term_positive:
        score += 30
    if momentum_aligned_positive:
        score += 20
    if five_m.get('net', 0) > 0:
        score += 20
    short_momentum = [snapshot.get('15m', {'net': 0})['net'], thirty_m['net']]
    if all(n > 0 for n in short_momentum):
        score += 15

    long_data = snapshot.get('12h', {})
    if long_data.get('quote_volume', 0) > 0:
        net_ratio = abs(long_data.get('net', 0)) / long_data['quote_volume']
        if net_ratio > 0.05:
            score += 15

    if five_m.get('pct', 0) < DUMP_PCT_THRESHOLD:
        score -= 20

    score = max(0, min(100, score))

    snapshot['summary'] = {
        'long_term_positive':          long_term_positive,
        'short_term_not_dump':         short_term_not_dump,
        'momentum_aligned_positive':  momentum_aligned_positive,
        'momentum_aligned_negative':  momentum_aligned_negative,
        'score':                       score,
        'long_positive_count':         long_pos,
    }
    return snapshot


def format_flow_table(snapshot: dict) -> str:
    """In bảng giống CoinGlass: Thời gian | Dòng vào | Ra | Net | % | Đánh giá."""
    if not snapshot:
        return "Không có dữ liệu dòng tiền"

    labels = {'5m': '5 phút', '15m': '15 phút', '30m': '30 phút',
              '1h': '1 giờ', '4h': '4 giờ', '8h': '8 giờ', '12h': '12 giờ'}

    def fmt_usd(v: float) -> str:
        av = abs(v)
        if av >= 1_000_000:
            return f"${v/1_000_000:.2f}M"
        if av >= 1_000:
            return f"${v/1_000:.2f}K"
        return f"${v:.2f}"

    lines = []
    lines.append(f"{'Thời gian':<10} | {'Dòng vào':>11} | {'Ra':>11} | "
                 f"{'Net':>11} | {'%':>7} | Đánh giá")
    lines.append('-' * 72)
    for tf in ['5m', '15m', '30m', '1h', '4h', '8h', '12h']:
        d = snapshot.get(tf)
        if not d:
            continue
        net = d['net']
        sign = '+' if net >= 0 else ''
        emo = '🟢' if net > 0 else '🔴'
        lines.append(
            f"{labels[tf]:<10} | {fmt_usd(d['inflow']):>11} | "
            f"{fmt_usd(d['outflow']):>11} | {sign}{fmt_usd(net):>10} | "
            f"{d['pct']:>+6.2f}% | {emo}"
        )
    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------
if __name__ == '__main__':
    import sys
    symbol = sys.argv[1] if len(sys.argv) > 1 else 'BTC/USDT'
    print(f"🚀 Đang lấy dòng tiền Futures cho {symbol} ...")
    snap = get_flow_snapshot(symbol)
    if snap is None:
        print(f"❌ Không có dữ liệu cho {symbol} (có thể chưa có Futures)")
        sys.exit(1)
    print(f"\n📊 Bảng Dòng Tiền Futures — {symbol}")
    print(format_flow_table(snap))
    s = snap['summary']
    print(f"\n🎯 Điểm tổng hợp: {s['score']}/100")
    print(f"   Long-term positive : {s['long_term_positive']}  "
          f"({s['long_positive_count']}/3 khung dài dương)")
    print(f"   Short-term no dump : {s['short_term_not_dump']}")
    print(f"   Momentum POSITIVE  : {s['momentum_aligned_positive']}")
    print(f"   Momentum NEGATIVE  : {s['momentum_aligned_negative']}")
