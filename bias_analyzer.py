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

def analyze_major_asset(symbol='BTC/USDT', risk_capital_percent=2.0, account_balance=1000.0, timeframe='15m'):
    """
    Phân tích chuyên sâu cho các tài sản lớn (BTC/USDT hoặc XAU/USDT - Vàng thế giới).
    Tính toán chính xác Entry, SL, TP (R:R 1:2 & 1:3), và Khối lượng vào lệnh (% Vốn).
    """
    try:
        # Nếu là phân tích vàng, ưu tiên dùng XAU/USDT:USDT (Hợp đồng Vàng thế giới volume > 4 Tỷ USD/ngày)
        target_symbol = symbol
        if 'PAXG' in symbol or 'XAU' in symbol or 'GOLD' in symbol:
            target_symbol = 'XAU/USDT:USDT'
        elif ':USDT' not in target_symbol:
            target_symbol = f"{symbol}:USDT"

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

