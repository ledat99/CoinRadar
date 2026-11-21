# 🚀 Hướng Dẫn Sử Dụng Bộ Công Cụ Săn Crypto (Momentum Surge)

Bộ công cụ này được thiết kế theo chiến lược bắt các siêu sóng "Pump" với 3 công cụ kết hợp chéo với nhau:
1. **Bot Cảnh báo Real-time** (`crypto_scanner.py`) — quét coin, lọc dòng tiền, báo tín hiệu qua Telegram.
2. **Bộ giả lập Backtest** (`backtest.py`) — kiểm tra tỷ lệ thắng trên lịch sử.
3. **Bảng dòng tiền 1 coin** (`flow_filter.py`) — xem Inflow/Outflow giống CoinGlass trước khi vào lệnh.

> **Lưu ý Windows quan trọng:** PowerShell **KHÔNG chạy** lệnh trong thư mục hiện tại nếu không có `.\` phía trước, và lệnh `python` mặc định trỏ về Microsoft Store.
>
> **Bắt buộc gõ đúng cú pháp (có `.\` phía trước + đuôi `.bat`):**
> ```powershell
> .\run_scanner.bat                      # quét coin + lọc tích lũy (~1 phút)
> .\run_flow.bat BTC/USDT                # xem dòng tiền 1 coin
> .\run_flow.bat IMX/USDT
> .\run_backtest.bat VANRY/USDT          # backtest 1 coin
> .\run_check.bat                        # theo dõi SL/TP các lệnh đang mở
> ```
>
> **Nếu vẫn lỗi *"Python was not found"*, gõ thẳng đường dẫn Python:**
> ```powershell
> C:\Users\vivas\AppData\Local\Python\bin\python.exe crypto_scanner.py
> ```
>
> Sau khi cửa sổ chạy xong sẽ có dòng "Press any key to continue . . ." — bấm Enter để đóng.

---

## 1. Bot Săn Tín Hiệu (Crypto Scanner)
Nhiệm vụ: Quét các đồng coin Lowcap (Volume 24h từ 5M - 1 Tỷ USD) trên Binance Spot và có mặt trên BingX. Bot tự động tìm điểm vào lệnh **Entry, Cắt Lỗ, Chốt Lời** dựa trên 3 đường SMA và báo qua Telegram.

**Lệnh chạy cơ bản:**
```powershell
python crypto_scanner.py
```
*Lưu ý: Bạn có thể chạy lệnh này bất cứ lúc nào. Khi chạy, bot sẽ lọc ra tối đa 5 đồng coin có tín hiệu đẹp nhất và in ra màn hình Bảng Xếp Hạng Top 5.*

> **Cập nhật mới:** Scanner giờ tìm coin **TÍCH LŨY** (accumulation):
> - **Stage 1 (lọc tích lũy)**: giữ coin có **giá đi ngang/giảm** (price change 4h < 2%) VÀ **dòng tiền 4h/8h/12h đều dương**. Đây là dấu hiệu cá mập đang gom hàng trước khi pump.
> - **Stage 2 (SMA + RSI)**: phân tích kỹ thuật trên các coin còn lại, kèm **chặn tín hiệu** nếu coin đang bị xả ở khung 5m.

---

## 1.1. Tool Xem Dòng Tiền 1 Coin Riêng Lẻ (`flow_filter.py`)

Nhiệm vụ: In bảng Inflow / Outflow / Net / % qua 7 khung thời gian (5m, 15m, 30m, 1h, 4h, 8h, 12h) — giống bảng trên **CoinGlass** nhưng tự tính từ Binance Futures, miễn phí, không cần API key.

**Lệnh chạy:**
```powershell
# Xem bảng cho 1 coin bất kỳ
python flow_filter.py BTC/USDT
python flow_filter.py IMX/USDT
python flow_filter.py HMSTR/USDT
```

**Bảng sẽ hiện ra kiểu:**
```
Thời gian  |    Dòng vào |          Ra |         Net |       % | Đánh giá
------------------------------------------------------------------------
5 phút     |    $607.57K |      $4.58M |    $-3.97M | -143.00% | 🔴
...
12 giờ     |   $2587.16M |   $2212.23M | +  $374.93M |  +0.00% | 🟢

🎯 Điểm tổng hợp: 0/100
   Long-term positive : False  (1/3 khung dài dương)
   Short-term no dump : False
   Momentum POSITIVE  : False
```

**Cách đọc nhanh:**
- **🟢 Net dương**: bên mua (taker) đang áp đảo → dòng tiền đang VÀO.
- **🔴 Net âm**: bên bán đang áp đảo → dòng tiền đang RÚT / xả hàng.
- **% (cột cuối)**: so sánh Net hiện tại với kỳ trước (cùng độ dài). `+166%` nghĩa là dòng tiền ròng đã tăng gấp 2.66 lần so với kỳ trước.

**Cách dùng:** Trước khi vào lệnh 1 coin do scanner báo, chạy `flow_filter.py SYMBOL` để kiểm tra nhanh. Coin đáng chơi là coin có:
1. 12h / 8h / 4h đều 🟢
2. 30m + 1h cùng dấu với hướng bạn đánh
3. 5m không bị 🔴 sâu quá −30%

---

## 2. Tool Theo Dõi Cắt Lỗ / Chốt Lời (Check Trades)
Nhiệm vụ: Sau khi Scanner tìm được coin và báo tín hiệu, các lệnh đó sẽ được lưu lại. Bạn dùng tool này để xem giá hiện tại đã chạm SL hay TP chưa. Nếu chạm, nó sẽ báo Telegram và xóa lệnh.

**Lệnh chạy cơ bản:**
```powershell
python check_trades.py
# hoặc
run_check
```

---

## 3. Tool Kiểm Thử Lịch Sử (Backtester)
Nhiệm vụ: Trước khi xuống tiền mua một đồng coin do bot báo, bạn KHÔNG NÊN mua mù quáng. Hãy dùng tool này để kiểm tra xem trong 10 ngày qua, tỷ lệ báo chuẩn của bot đối với đồng coin đó có sinh ra lợi nhuận bền vững hay không.

**Lệnh chạy (Thay thế tên coin muốn test):**
```powershell
# Cú pháp
python backtest.py <TÊN_COIN>/USDT

# Ví dụ 1: Test đồng VANRY
python backtest.py VANRY/USDT

# Ví dụ 2: Test đồng HMSTR
python backtest.py HMSTR/USDT
```

---

## 4. Hướng Dẫn Cấu Hình Telegram (Tùy Chọn)
Nếu bạn không muốn lúc nào cũng phải gõ lệnh mà muốn bot tự động nhắn tin cho bạn qua Telegram khi có sóng lớn:
1. Mở file `crypto_scanner.py` bằng Notepad hoặc VS Code.
2. Tìm đến dòng **15** và **16**, thay thế 2 dòng này bằng thông tin bot của bạn:
   - `TELEGRAM_BOT_TOKEN = "Mã token lấy từ @BotFather"`
   - `TELEGRAM_CHAT_ID = "Mã chat id lấy từ @userinfobot"`
3. Bạn có thể sử dụng các công cụ như Task Scheduler của Windows để cho file python tự động chạy ngầm mỗi 15 phút 1 lần.

---

## 5. Điều Chỉnh Ngưỡng Lọc Dòng Tiền (`flow_filter.py`)
Mở file `flow_filter.py`, chỉnh các hằng số ở phần **CONFIG**:
- `SHORT_TF_MIN_PCT = -30` — coin có 5m `pct` thấp hơn ngưỡng này → chặn tín hiệu SMA+RSI.
- `DUMP_PCT_THRESHOLD = -50` — coin có 5m `pct` thấp hơn ngưỡng này → trừ 20 điểm score.
- `SIDEWAYS_PCT_MAX = 2.0` — coin có `|price_change_4h|` < ngưỡng này được coi là "đi ngang". Tăng lên (vd 3-5%) nếu muốn tìm coin mới bắt đầu tăng nhẹ.
- `DEAD_PCT_12H = -15.0` — coin giảm > 15% trong 12h sẽ bị coi là đã "chết", bỏ qua.

Bảng xếp hạng `crypto_scanner.py` đã có cột `Flow: xx/100` để bạn so sánh nhanh giữa các coin. **Bảng chính cần xem là "TOP 5 COIN TÍCH LŨY"** — đây là coin cá mập đang gom trước khi pump.
