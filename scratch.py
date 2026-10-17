import ccxt
import pandas as pd
import ta
import warnings

warnings.filterwarnings('ignore')

binance = ccxt.binance()
bingx = ccxt.bingx()

bingx.load_markets()
bingx_symbols = set(bingx.symbols)

tickers = binance.fetch_tickers()
valid_pairs = []
for symbol, ticker in tickers.items():
    if symbol.endswith('/USDT') and symbol in bingx_symbols:
        vol = ticker.get('quoteVolume', 0)
        if 5000000 <= vol <= 1000000000:
            valid_pairs.append(symbol)

results = []
for symbol in valid_pairs:
    try:
        ohlcv = binance.fetch_ohlcv(symbol, '15m', limit=20)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        current = df.iloc[-1]
        
        # Calculate volume surge ratio
        sma_vol = df['volume'].mean()
        vol_ratio = current['volume'] / sma_vol if sma_vol > 0 else 0
        
        # Calculate recent price change (last 4 candles = 1h)
        price_change = (current['close'] - df.iloc[-4]['open']) / df.iloc[-4]['open'] * 100
        
        # RSI
        rsi_val = ta.momentum.RSIIndicator(close=df['close'], window=14).rsi().iloc[-1]
        
        results.append({
            'symbol': symbol,
            'vol_ratio': vol_ratio,
            'price_change_1h': price_change,
            'rsi': rsi_val
        })
    except:
        continue

df_res = pd.DataFrame(results)
print("\n--- TOP 5 COIN TĂNG MẠNH NHẤT TRONG 1 GIỜ QUA ---")
top_price = df_res.sort_values(by='price_change_1h', ascending=False).head(5)
for _, r in top_price.iterrows():
    print(f"{r['symbol']}: Tăng {r['price_change_1h']:.2f}% | Vol Surge: {r['vol_ratio']:.2f}x | RSI: {r['rsi']:.1f}")

print("\n--- TOP 5 COIN ĐANG CÓ DÒNG TIỀN (VOLUME) VÀO MẠNH NHẤT LÚC NÀY ---")
top_vol = df_res.sort_values(by='vol_ratio', ascending=False).head(5)
for _, r in top_vol.iterrows():
    print(f"{r['symbol']}: Vol Surge {r['vol_ratio']:.2f}x | Tăng 1h: {r['price_change_1h']:.2f}% | RSI: {r['rsi']:.1f}")
