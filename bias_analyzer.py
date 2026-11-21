import ccxt
import pandas as pd
import ta
import time
from flow_filter import get_flow_snapshot

binance_futures = ccxt.binance({
    'enableRateLimit': True,
    'options': {'defaultType': 'future'}
})

def get_market_bias():
    """
    Xác định Bias toàn thị trường dựa trên Bitcoin (BTC/USDT):
    - Khung H4: Xu hướng dài (EMA 50 & EMA 200)
    - Khung H1: Momentum & Vị trí giá
    - Dòng tiền: Inflow/Outflow thực tế
    Returns:
        dict: {'bias': 'BULLISH'/'BEARISH'/'NEUTRAL', 'score': float, 'btc_price': float, 'details': str}
    """
    try:
        # Lấy dữ liệu nến H4 và H1 của BTC
        ohlcv_h4 = binance_futures.fetch_ohlcv('BTC/USDT:USDT', '4h', limit=100)
        ohlcv_h1 = binance_futures.fetch_ohlcv('BTC/USDT:USDT', '1h', limit=100)
        
        df_h4 = pd.DataFrame(ohlcv_h4, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df_h1 = pd.DataFrame(ohlcv_h1, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        # Chỉ báo H4
        df_h4['ema_50'] = ta.trend.EMAIndicator(close=df_h4['close'], window=50).ema_indicator()
        df_h4['ema_200'] = ta.trend.EMAIndicator(close=df_h4['close'], window=200).ema_indicator()
        df_h4['rsi'] = ta.momentum.RSIIndicator(close=df_h4['close'], window=14).rsi()
        
        # Chỉ báo H1
        df_h1['ema_20'] = ta.trend.EMAIndicator(close=df_h1['close'], window=20).ema_indicator()
        df_h1['ema_50'] = ta.trend.EMAIndicator(close=df_h1['close'], window=50).ema_indicator()
        df_h1['rsi'] = ta.momentum.RSIIndicator(close=df_h1['close'], window=14).rsi()

        btc_price = df_h1['close'].iloc[-1]
        h4_last = df_h4.iloc[-1]
        h1_last = df_h1.iloc[-1]
        
        score = 0 # -100 đến +100
        
        # Đánh giá H4
        if h4_last['close'] > h4_last['ema_50']: score += 25
        else: score -= 25
        
        if not pd.isna(h4_last['ema_200']):
            if h4_last['close'] > h4_last['ema_200']: score += 25
            else: score -= 25
            
        # Đánh giá H1
        if h1_last['close'] > h1_last['ema_20']: score += 15
        else: score -= 15
        
        if h1_last['rsi'] > 55: score += 15
        elif h1_last['rsi'] < 45: score -= 15
        
        # Dòng tiền BTC
        flow = get_flow_snapshot('BTC/USDT')
        flow_summary = flow.get('summary', {}) if flow else {}
        flow_score = flow_summary.get('score', 50)
        
        if flow_score >= 60: score += 20
        elif flow_score <= 40: score -= 20
        
        # Quyết định Bias
        if score >= 35:
            bias = "BULLISH" # Ưu tiên Long
            desc = "Thị trường xu hướng TĂNG (Ưu tiên LONG)"
        elif score <= -35:
            bias = "BEARISH" # Ưu tiên Short
            desc = "Thị trường xu hướng GIẢM (Ưu tiên SHORT)"
        else:
            bias = "NEUTRAL"
            desc = "Thị trường ĐI NGANG (Nên đánh thận trọng / Giảm volume)"
            
        return {
            'bias': bias,
            'score': score,
            'btc_price': btc_price,
            'h1_rsi': h1_last['rsi'],
            'h4_rsi': h4_last['rsi'],
            'flow_score': flow_score,
            'desc': desc
        }
    except Exception as e:
        print(f"Lỗi phân tích BTC bias: {e}")
        return {
            'bias': 'NEUTRAL',
            'score': 0,
            'btc_price': 0,
            'h1_rsi': 50,
            'h4_rsi': 50,
            'flow_score': 50,
            'desc': 'Không lấy được dữ liệu BTC Bias'
        }

def quick_scan_market(mode='long', limit=5):
    """
    Quét siêu tốc các coin thanh khoản cao trên Binance Futures theo chiều TĂNG hoặc GIẢM.
    Trả về ngay kết quả Top coin đẹp nhất kèm Entry, SL, TP (R:R 1:2) và Dòng tiền.
    """
    try:
        tickers = binance_futures.fetch_tickers()
        usdt_pairs = []
        for sym, t in tickers.items():
            if '/USDT:USDT' in sym and t.get('quoteVolume', 0) > 20000000: # Volume 24h > 20 Triệu USD
                usdt_pairs.append({
                    'symbol': sym.split(':')[0],
                    'full_symbol': sym,
                    'volume': t['quoteVolume'],
                    'change': t.get('percentage', 0),
                    'last': t['last']
                })
                
        if mode == 'long':
            # Tìm coin giữ giá tốt / tăng nhẹ hoặc hồi phục có volume
            usdt_pairs.sort(key=lambda x: x['change'], reverse=True)
        else: # short
            # Tìm coin giảm mạnh, gãy cấu trúc
            usdt_pairs.sort(key=lambda x: x['change'])
            
        candidates = usdt_pairs[:12]
        results = []
        
        for c in candidates:
            sym = c['full_symbol']
            ohlcv = binance_futures.fetch_ohlcv(sym, '15m', limit=50)
            if not ohlcv or len(ohlcv) < 30: continue
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['ema_20'] = ta.trend.EMAIndicator(close=df['close'], window=20).ema_indicator()
            df['atr'] = ta.volatility.AverageTrueRange(high=df['high'], low=df['low'], close=df['close'], window=14).average_true_range()
            df['rsi'] = ta.momentum.RSIIndicator(close=df['close'], window=14).rsi()
            
            last = df.iloc[-1]
            atr = last['atr']
            price = last['close']
            
            if mode == 'long':
                sl = min(df['low'].tail(5).min(), price - (1.6 * atr))
                sl_dist = price - sl
                tp1 = price + (sl_dist * 2.0)
                sl_pct = (sl_dist / price) * 100
                score = (last['rsi'] - 40) + (c['change'] * 2)
            else:
                sl = max(df['high'].tail(5).max(), price + (1.6 * atr))
                sl_dist = sl - price
                tp1 = price - (sl_dist * 2.0)
                sl_pct = (sl_dist / price) * 100
                score = (60 - last['rsi']) + (abs(c['change']) * 2)
                
            results.append({
                'symbol': c['symbol'],
                'type': 'LONG' if mode == 'long' else 'SHORT',
                'entry': price,
                'sl': sl,
                'sl_pct': sl_pct,
                'tp1': tp1,
                'change_24h': c['change'],
                'rsi': last['rsi'],
                'vol_m': c['volume'] / 1000000,
                'score': score
            })
            
        results.sort(key=lambda x: x['score'], reverse=True)
        return results[:limit]
    except Exception as e:
        print(f"Lỗi quick scan: {e}")
        return []

def get_oanda_gold_tradingview():
    """
    Lấy dữ liệu thời gian thực trực tiếp từ biểu đồ OANDA:XAUUSD trên TradingView:
    Bao gồm: Giá Close, Open, High, Low, Volume, RSI M15, ATR M15, EMA20 M15, EMA50 M15.
    """
    import urllib.request
    import json
    url = 'https://scanner.tradingview.com/cfd/scan'
    payload = json.dumps({
        'symbols': {'tickers': ['OANDA:XAUUSD']},
        'columns': [
            'close|15', 'open|15', 'high|15', 'low|15', 'volume|15',
            'RSI|15', 'ATR|15', 'EMA20|15', 'EMA50|15', 'Recommend.All|15'
        ]
    }).encode()
    headers = {'User-Agent': 'Mozilla/5.0'}
    req = urllib.request.Request(url, data=payload, headers=headers)
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode())
        row = data['data'][0]['d']
        return {
            'close': row[0],
            'open': row[1],
            'high': row[2],
            'low': row[3],
            'volume': row[4],
            'rsi': row[5],
            'atr': row[6],
            'ema_20': row[7],
            'ema_50': row[8],
            'recommendation': row[9]
        }

def analyze_major_asset(symbol='BTC/USDT', risk_capital_percent=2.0, account_balance=1000.0, timeframe='15m'):
    """
    Phân tích chuyên sâu cho các tài sản lớn:
    - Vàng: Lấy trực tiếp từ biểu đồ OANDA:XAUUSD trên TradingView.
    - BTC: Lấy từ Binance Futures BTC/USDT.
    Tính toán chính xác Entry, SL, TP (R:R 1:2 & 1:3), và Khối lượng vào lệnh (% Vốn).
    """
    try:
        # NẾU LÀ VÀNG -> LẤY TỪ OANDA:XAUUSD TRADINGVIEW
        if 'PAXG' in symbol or 'XAU' in symbol or 'GOLD' in symbol:
            try:
                tv_data = get_oanda_gold_tradingview()
                price = tv_data['close']
                atr = tv_data['atr']
                rsi = tv_data['rsi']
                ema_20 = tv_data['ema_20']
                ema_50 = tv_data['ema_50']
                
                signal = None
                if price > ema_20 and ema_20 > ema_50 and 48 <= rsi <= 68:
                    signal = "LONG"
                    sl = price - (1.8 * atr)
                    sl_dist = price - sl
                    tp1 = price + (sl_dist * 2.0)
                    tp2 = price + (sl_dist * 3.0)
                elif price < ema_20 and ema_20 < ema_50 and 32 <= rsi <= 52:
                    signal = "SHORT"
                    sl = price + (1.8 * atr)
                    sl_dist = sl - price
                    tp1 = price - (sl_dist * 2.0)
                    tp2 = price - (sl_dist * 3.0)
                    
                if not signal:
                    return {
                        'has_signal': False,
                        'symbol': 'OANDA:XAUUSD (TradingView)',
                        'price': price,
                        'rsi': rsi,
                        'volume': tv_data['volume'],
                        'trend': "UPTREND" if price > ema_50 else "DOWNTREND",
                        'ema_20': ema_20,
                        'ema_50': ema_50
                    }
                    
                sl_percent = (sl_dist / price) * 100
                max_loss_usd = account_balance * (risk_capital_percent / 100.0)
                position_size_usd = (max_loss_usd / (sl_percent / 100.0))
                suggested_leverage = min(20, max(2, int(position_size_usd / account_balance)))
                margin_needed = position_size_usd / suggested_leverage
                margin_percent = (margin_needed / account_balance) * 100.0

                return {
                    'has_signal': True,
                    'symbol': 'OANDA:XAUUSD (TradingView)',
                    'type': signal,
                    'entry': price,
                    'sl': sl,
                    'sl_percent': sl_percent,
                    'tp1': tp1,
                    'tp2': tp2,
                    'rr_tp1': "1:2.0",
                    'rr_tp2': "1:3.0",
                    'risk_percent': risk_capital_percent,
                    'position_size_usd': position_size_usd,
                    'suggested_leverage': f"{suggested_leverage}x",
                    'margin_percent': margin_percent,
                    'margin_usd': margin_needed,
                    'rsi': rsi,
                    'volume': tv_data['volume']
                }
            except Exception as e:
                print(f"Lỗi lấy OANDA TradingView: {e}")
                # Fallback qua Binance Futures nếu TV nghẽn mạng

        # NẾU LÀ BITCOIN / COIN KHÁC -> BINANCE FUTURES
        target_symbol = f"{symbol}:USDT" if ':USDT' not in symbol else symbol
        ohlcv = binance_futures.fetch_ohlcv(target_symbol, timeframe, limit=120)
        if not ohlcv or len(ohlcv) < 60:
            # Fallback nếu cần
            if target_symbol == 'XAU/USDT:USDT':
                target_symbol = 'PAXG/USDT:USDT'
                ohlcv = binance_futures.fetch_ohlcv(target_symbol, timeframe, limit=120)

        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['ema_20'] = ta.trend.EMAIndicator(close=df['close'], window=20).ema_indicator()
        df['ema_50'] = ta.trend.EMAIndicator(close=df['close'], window=50).ema_indicator()
        df['atr'] = ta.volatility.AverageTrueRange(high=df['high'], low=df['low'], close=df['close'], window=14).average_true_range()
        df['rsi'] = ta.momentum.RSIIndicator(close=df['close'], window=14).rsi()
        
        last = df.iloc[-1]
        prev = df.iloc[-2]
        atr = last['atr']
        price = last['close']
        
        # Kiểm tra điều kiện Tín hiệu (Trend Following + Pullback)
        signal = None
        # LONG: Giá trên EMA 20 & 50, RSI 48-68 (không quá mua), nến xanh
        if last['close'] > last['ema_20'] and last['ema_20'] > last['ema_50'] and 48 <= last['rsi'] <= 68:
            signal = "LONG"
            # SL đặt dưới swing low hoặc 1.8 * ATR để tránh quét râu
            sl = min(df['low'].tail(8).min(), price - (1.8 * atr))
            sl_dist = price - sl
            tp1 = price + (sl_dist * 2.0) # R:R 1:2
            tp2 = price + (sl_dist * 3.0) # R:R 1:3
            
        # SHORT: Giá dưới EMA 20 & 50, RSI 32-52 (không quá bán), nến đỏ
        elif last['close'] < last['ema_20'] and last['ema_20'] < last['ema_50'] and 32 <= last['rsi'] <= 52:
            signal = "SHORT"
            # SL đặt trên swing high hoặc 1.8 * ATR
            sl = max(df['high'].tail(8).max(), price + (1.8 * atr))
            sl_dist = sl - price
            tp1 = price - (sl_dist * 2.0)
            tp2 = price - (sl_dist * 3.0)
            
        if not signal:
            # Nếu chưa có điểm vào đẹp, trả về trạng thái theo dõi
            return {
                'has_signal': False,
                'symbol': target_symbol.split(':')[0],
                'price': price,
                'rsi': last['rsi'],
                'trend': "UPTREND" if last['close'] > last['ema_50'] else "DOWNTREND",
                'ema_20': last['ema_20'],
                'ema_50': last['ema_50']
            }
            
        # Tính toán Quản lý Vốn (Position Sizing & Risk Management)
        sl_percent = (sl_dist / price) * 100
        max_loss_usd = account_balance * (risk_capital_percent / 100.0)
        position_size_usd = (max_loss_usd / (sl_percent / 100.0))
        suggested_leverage = min(20, max(2, int(position_size_usd / account_balance)))
        margin_needed = position_size_usd / suggested_leverage
        margin_percent = (margin_needed / account_balance) * 100.0

        return {
            'has_signal': True,
            'symbol': target_symbol.split(':')[0],
            'type': signal,
            'entry': price,
            'sl': sl,
            'sl_percent': sl_percent,
            'tp1': tp1,
            'tp2': tp2,
            'rr_tp1': "1:2.0",
            'rr_tp2': "1:3.0",
            'risk_percent': risk_capital_percent,
            'position_size_usd': position_size_usd,
            'suggested_leverage': f"{suggested_leverage}x",
            'margin_percent': margin_percent,
            'margin_usd': margin_needed,
            'rsi': last['rsi']
        }
    except Exception as e:
        print(f"Lỗi phân tích {symbol}: {e}")
        return None

