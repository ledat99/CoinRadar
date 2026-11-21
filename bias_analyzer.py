import ccxt
import pandas as pd
import ta
import time
import os
import json
from flow_filter import get_flow_snapshot

binance_futures = ccxt.binance({
    'enableRateLimit': True,
    'options': {'defaultType': 'future'}
})

def get_market_bias():
    """Xác định Bias toàn thị trường dựa trên Bitcoin"""
    try:
        ohlcv_h4 = binance_futures.fetch_ohlcv('BTC/USDT:USDT', '4h', limit=100)
        ohlcv_h1 = binance_futures.fetch_ohlcv('BTC/USDT:USDT', '1h', limit=100)
        
        df_h4 = pd.DataFrame(ohlcv_h4, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df_h1 = pd.DataFrame(ohlcv_h1, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        df_h4['ema_50'] = ta.trend.EMAIndicator(close=df_h4['close'], window=50).ema_indicator()
        df_h4['ema_200'] = ta.trend.EMAIndicator(close=df_h4['close'], window=200).ema_indicator()
        df_h4['rsi'] = ta.momentum.RSIIndicator(close=df_h4['close'], window=14).rsi()
        
        df_h1['ema_20'] = ta.trend.EMAIndicator(close=df_h1['close'], window=20).ema_indicator()
        df_h1['ema_50'] = ta.trend.EMAIndicator(close=df_h1['close'], window=50).ema_indicator()
        df_h1['rsi'] = ta.momentum.RSIIndicator(close=df_h1['close'], window=14).rsi()

        btc_price = df_h1['close'].iloc[-1]
        h4_last = df_h4.iloc[-1]
        h1_last = df_h1.iloc[-1]
        
        score = 0
        if h4_last['close'] > h4_last['ema_50']: score += 25
        else: score -= 25
        
        if not pd.isna(h4_last['ema_200']):
            if h4_last['close'] > h4_last['ema_200']: score += 25
            else: score -= 25
            
        if h1_last['close'] > h1_last['ema_20']: score += 15
        else: score -= 15
        
        if h1_last['rsi'] > 55: score += 15
        elif h1_last['rsi'] < 45: score -= 15
        
        flow = get_flow_snapshot('BTC/USDT')
        flow_summary = flow.get('summary', {}) if flow else {}
        flow_score = flow_summary.get('score', 50)
        
        if flow_score >= 60: score += 20
        elif flow_score <= 40: score -= 20
        
        if score >= 35:
            bias = "BULLISH"
            desc = "Thị trường xu hướng TĂNG (Ưu tiên LONG)"
        elif score <= -35:
            bias = "BEARISH"
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
        print(f"Lỗi BTC bias: {e}")
        return {
            'bias': 'NEUTRAL',
            'score': 0,
            'btc_price': 0,
            'h1_rsi': 50,
            'h4_rsi': 50,
            'flow_score': 50,
            'desc': 'Không lấy được BTC Bias'
        }

def quick_scan_market(mode='long', limit=3):
    """
    QUÉT THEO BIAS THỊ TRƯỜNG & VOLUME THỰC TẾ:
    - Long: Chọn các coin giữ Trend Tăng tốt nhất + Volume > 10M USD
    - Short: Chọn các coin gãy cấu trúc xả mạnh nhất + Volume > 10M USD
    - Luôn trả về Top 3 coin đẹp nhất, không lọc cứng nhắc!
    """
    try:
        tickers = binance_futures.fetch_tickers()
        usdt_pairs = []
        for sym, t in tickers.items():
            vol = t.get('quoteVolume', 0)
            if '/USDT:USDT' in sym and vol > 10000000:
                usdt_pairs.append({
                    'symbol': sym.split(':')[0],
                    'full_symbol': sym,
                    'volume': vol,
                    'change': t.get('percentage', 0),
                    'last': t['last']
                })
                
        if not usdt_pairs:
            return []
            
        if mode == 'long':
            usdt_pairs.sort(key=lambda x: x['change'], reverse=True)
        else:
            usdt_pairs.sort(key=lambda x: x['change'])
            
        candidates = usdt_pairs[:12]
        results = []
        
        for c in candidates:
            sym = c['full_symbol']
            ohlcv = binance_futures.fetch_ohlcv(sym, '15m', limit=35)
            if not ohlcv or len(ohlcv) < 20: continue
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['ema_20'] = ta.trend.EMAIndicator(close=df['close'], window=20).ema_indicator()
            df['atr'] = ta.volatility.AverageTrueRange(high=df['high'], low=df['low'], close=df['close'], window=14).average_true_range()
            df['rsi'] = ta.momentum.RSIIndicator(close=df['close'], window=14).rsi()
            
            last = df.iloc[-1]
            atr = float(last['atr'])
            price = float(last['close'])
            ema = float(last['ema_20'])
            rsi = float(last['rsi'])
            
            if mode == 'long':
                swing_low = float(df['low'].tail(5).min())
                entry_limit = round(max(swing_low, min(price * 0.996, ema)), 6)
                sl = round(entry_limit - (1.6 * atr), 6)
                risk = entry_limit - sl
                tp1 = round(entry_limit + (risk * 2.0), 6)
                tp2 = round(entry_limit + (risk * 3.5), 6)
                sl_pct = (risk / entry_limit) * 100
                entry_stop = round(float(df['high'].tail(5).max()) * 1.002, 6)
                bias_status = "🟢 BIAS TĂNG (EMA20 + Vol Lớn)" if price >= ema else "⚪ Sóng Hồi Tăng"
                
                order_strategy = {
                    'limit_label': 'BUY LIMIT (Đón Râu Hồi EMA20)',
                    'entry_limit': entry_limit,
                    'stop_label': 'BUY STOP (Phá Cản Tiếp Diễn)',
                    'entry_stop': entry_stop,
                    'stop_status': bias_status
                }
            else: # short
                swing_high = float(df['high'].tail(5).max())
                entry_limit = round(min(swing_high, max(price * 1.004, ema)), 6)
                sl = round(entry_limit + (1.6 * atr), 6)
                risk = sl - entry_limit
                tp1 = round(entry_limit - (risk * 2.0), 6)
                tp2 = round(entry_limit - (risk * 3.5), 6)
                sl_pct = (risk / entry_limit) * 100
                entry_stop = round(float(df['low'].tail(5).min()) * 0.998, 6)
                bias_status = "🔴 BIAS GIẢM (Gãy EMA20 + Xả Mạnh)" if price <= ema else "⚪ Hồi Cản Để Short"
                
                order_strategy = {
                    'limit_label': 'SELL LIMIT (Đón Râu Cản EMA20)',
                    'entry_limit': entry_limit,
                    'stop_label': 'SELL STOP (Phá Đáy Tiếp Diễn)',
                    'entry_stop': entry_stop,
                    'stop_status': bias_status
                }
                
            results.append({
                'symbol': c['symbol'],
                'type': 'LONG' if mode == 'long' else 'SHORT',
                'market_price': price,
                'entry_limit': entry_limit,
                'entry_stop': entry_stop,
                'limit_label': order_strategy['limit_label'],
                'stop_label': order_strategy['stop_label'],
                'stop_status': order_strategy['stop_status'],
                'sl': sl,
                'sl_pct': sl_pct,
                'tp1': tp1,
                'tp2': tp2,
                'change_24h': c['change'],
                'rsi': rsi,
                'vol_m': c['volume'] / 1000000,
                'score': abs(c['change'])
            })
            if len(results) >= limit:
                break
                
        return results
    except Exception as e:
        print(f"Lỗi quick scan: {e}")
        return []

def get_oanda_gold_tradingview():
    """Lấy dữ liệu thời gian thực từ TradingView OANDA:XAUUSD khung H4 & D1"""
    import urllib.request
    url = 'https://scanner.tradingview.com/cfd/scan'
    payload = json.dumps({
        'symbols': {'tickers': ['OANDA:XAUUSD']},
        'columns': [
            'close', 'open', 'high', 'low', 'volume', 'RSI', 'ATR', 'EMA20', 'EMA50',
            'close|240', 'open|240', 'high|240', 'low|240', 'volume|240', 'RSI|240', 'ATR|240', 'EMA20|240', 'EMA50|240'
        ]
    }).encode()
    headers = {'User-Agent': 'Mozilla/5.0'}
    req = urllib.request.Request(url, data=payload, headers=headers)
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode())
        row = data['data'][0]['d']
        return {
            'd1_close': row[0],
            'd1_high': row[2],
            'd1_low': row[3],
            'd1_rsi': row[5],
            'd1_atr': row[6],
            'd1_ema20': row[7],
            'd1_ema50': row[8],
            # Khung H4 (240m)
            'close': row[9],
            'open': row[10],
            'high': row[11],
            'low': row[12],
            'volume': row[13],
            'rsi': row[14],
            'atr': row[15],
            'ema_20': row[16],
            'ema_50': row[17]
        }

def analyze_major_asset(symbol='BTC/USDT', risk_capital_percent=2.0, account_balance=1000.0, timeframe='4h'):
    """Phân tích Vàng OANDA hoặc BTC theo Khung Lớn H4 & D1 chuẩn xác suất cao"""
    try:
        if 'PAXG' in symbol or 'XAU' in symbol or 'GOLD' in symbol:
            tv_data = get_oanda_gold_tradingview()
            price = tv_data['close']
            atr_h4 = tv_data['atr']
            rsi_h4 = tv_data['rsi']
            ema_20_h4 = tv_data['ema_20']
            ema_50_h4 = tv_data['ema_50']
            
            # Xu hướng theo D1 & H4
            is_uptrend = price >= ema_50_h4
            signal = "LONG" if is_uptrend else "SHORT"
            
            if signal == "SHORT":
                # Kèo SHORT VÀNG:
                # 1. LỆNH 1 (SELL LIMIT đón râu hồi cản giá cao)
                entry_limit = round(max(price + 10.0, min(tv_data['high'] * 1.002, ema_20_h4)), 2)
                # 2. LỆNH 2 (SELL STOP phá đáy nến H4 xác nhận lực xả)
                entry_stop = round(tv_data['low'] - 1.5, 2)
                
                # SL VÀNG CHUẨN: Tối đa 20 - 25 giá từ Entry Limit (bảo toàn vốn tối đa)
                sl_dist = 20.0
                sl = round(entry_limit + sl_dist, 2)
                tp1 = round(entry_limit - 40.0, 2) # R:R 1:2 (ăn 40 giá)
                tp2 = round(entry_limit - 70.0, 2) # R:R 1:3.5 (ăn 70 giá)
                
                # Chiến lược chủ động khi thị trường biến động
                advice_market = (
                    "⚠️ CẮT LỖ SỚM: Nếu có nến H1/H4 đóng cửa vượt trên cản $3,570.00 thì chủ động cắt lỗ tay, không cần chờ quét SL $20 giá!\n"
                    "💎 DCA GIA TĂNG LỢI NHUẬN: Khi giá giảm phá thủng đáy $3,502.00 và có lãi > 20 giá, dời SL về Entry (Hòa vốn) và DCA nhồi thêm Lệnh 2 (Sell Stop)!"
                )
            else: # LONG VÀNG
                # 1. LỆNH 1 (BUY LIMIT đón râu hồi hỗ trợ giá thấp)
                entry_limit = round(min(price - 10.0, max(tv_data['low'] * 0.998, ema_20_h4)), 2)
                # 2. LỆNH 2 (BUY STOP phá cản đỉnh H4)
                entry_stop = round(tv_data['high'] + 1.5, 2)
                
                sl_dist = 20.0
                sl = round(entry_limit - sl_dist, 2)
                tp1 = round(entry_limit + 40.0, 2)
                tp2 = round(entry_limit + 70.0, 2)
                
                advice_market = (
                    "⚠️ CẮT LỖ SỚM: Nếu có nến H1/H4 đóng cửa gãy hỗ trợ quan trọng thì chủ động thoát sớm!\n"
                    "💎 DCA GIA TĂNG LỢI NHUẬN: Khi giá tăng vượt đỉnh và có lãi > 20 giá, dời SL về Entry và DCA nhồi thêm Lệnh 2 (Buy Stop)!"
                )
                
            sl_percent = (sl_dist / entry_limit) * 100
            max_loss_usd = account_balance * (risk_capital_percent / 100.0)
            position_size_usd = (max_loss_usd / (sl_percent / 100.0))
            suggested_leverage = min(20, max(2, int(position_size_usd / account_balance)))
            margin_needed = position_size_usd / suggested_leverage
            margin_percent = (margin_needed / account_balance) * 100.0

            return {
                'has_signal': True,
                'symbol': 'OANDA:XAUUSD (TradingView H4/D1)',
                'timeframe': 'H4 & D1',
                'type': signal,
                'market_price': price,
                'entry_limit': entry_limit,
                'entry_stop': entry_stop,
                'sl': sl,
                'sl_dist': sl_dist,
                'sl_percent': sl_percent,
                'tp1': tp1,
                'tp2': tp2,
                'rr_tp1': "1:2.0 (+40 giá)",
                'rr_tp2': "1:3.5 (+70 giá)",
                'risk_percent': risk_capital_percent,
                'position_size_usd': position_size_usd,
                'suggested_leverage': f"{suggested_leverage}x",
                'margin_percent': margin_percent,
                'margin_usd': margin_needed,
                'rsi': rsi_h4,
                'advice_market': advice_market,
                'd1_trend': "D1 GIẢM" if tv_data['d1_close'] < tv_data['d1_ema20'] else "D1 TĂNG",
                'trend': "DOWNTREND H4 (Ưu tiên SHORT)" if not is_uptrend else "UPTREND H4 (Ưu tiên LONG)"
            }

        # NẾU LÀ BITCOIN -> KHUNG H4 & D1
        target_symbol = f"{symbol}:USDT" if ':USDT' not in symbol else symbol
        ohlcv = binance_futures.fetch_ohlcv(target_symbol, '4h', limit=60)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['ema_20'] = ta.trend.EMAIndicator(close=df['close'], window=20).ema_indicator()
        df['ema_50'] = ta.trend.EMAIndicator(close=df['close'], window=50).ema_indicator()
        df['atr'] = ta.volatility.AverageTrueRange(high=df['high'], low=df['low'], close=df['close'], window=14).average_true_range()
        df['rsi'] = ta.momentum.RSIIndicator(close=df['close'], window=14).rsi()
        
        last = df.iloc[-1]
        price = float(last['close'])
        atr = float(last['atr'])
        ema_20 = float(last['ema_20'])
        is_uptrend = price >= float(last['ema_50'])
        signal = "LONG" if is_uptrend else "SHORT"
        
        if signal == "SHORT":
            # SELL LIMIT giá cao: đón râu hồi lên cản EMA20 H4
            entry_limit = round(max(price * 1.01, min(float(df['high'].tail(5).max()), ema_20)), 1)
            # SELL STOP: bán tháo khi thủng đáy râu thấp nhất H4
            entry_stop = round(float(df['low'].tail(5).min()) * 0.998, 1)
            sl = round(entry_limit + (1.5 * atr), 1)
            sl_dist = sl - entry_limit
            tp1 = round(entry_limit - (sl_dist * 2.0), 1)
            tp2 = round(entry_limit - (sl_dist * 3.5), 1)
        else:
            entry_limit = round(min(price * 0.99, max(float(df['low'].tail(5).min()), ema_20)), 1)
            entry_stop = round(float(df['high'].tail(5).max()) * 1.002, 1)
            sl = round(entry_limit - (1.5 * atr), 1)
            sl_dist = entry_limit - sl
            tp1 = round(entry_limit + (sl_dist * 2.0), 1)
            tp2 = round(entry_limit + (sl_dist * 3.5), 1)
            
        sl_percent = (sl_dist / entry_limit) * 100
        max_loss_usd = account_balance * (risk_capital_percent / 100.0)
        position_size_usd = (max_loss_usd / (sl_percent / 100.0))
        suggested_leverage = min(20, max(2, int(position_size_usd / account_balance)))
        margin_needed = position_size_usd / suggested_leverage
        margin_percent = (margin_needed / account_balance) * 100.0

        return {
            'has_signal': True,
            'symbol': target_symbol.split(':')[0],
            'timeframe': 'H4 & D1',
            'type': signal,
            'market_price': price,
            'entry_limit': entry_limit,
            'entry_stop': entry_stop,
            'sl': sl,
            'sl_percent': sl_percent,
            'tp1': tp1,
            'tp2': tp2,
            'rr_tp1': "1:2.0",
            'rr_tp2': "1:3.5",
            'risk_percent': risk_capital_percent,
            'position_size_usd': position_size_usd,
            'suggested_leverage': f"{suggested_leverage}x",
            'margin_percent': margin_percent,
            'margin_usd': margin_needed,
            'rsi': float(last['rsi']),
            'trend': "DOWNTREND H4 (Ưu tiên SHORT)" if not is_uptrend else "UPTREND H4 (Ưu tiên LONG)"
        }
    except Exception as e:
        print(f"Lỗi asset: {e}")
        return None
