# 🚀 Hướng Dẫn Sử Dụng Bộ Công Cụ Săn Crypto (Momentum Surge)

Bộ công cụ này được thiết kế theo chiến lược bắt các siêu sóng "Pump" với 2 công cụ kết hợp chéo với nhau: (1) Bot Cảnh báo Real-time và (2) Bộ giả lập Backtest kiểm tra tỷ lệ thắng.

---

## 1. Bot Săn Tín Hiệu (Crypto Scanner)
Nhiệm vụ: Quét các đồng coin Lowcap (Volume 24h từ 5M - 1 Tỷ USD) trên Binance Spot và có mặt trên BingX. Bot tự động tìm điểm vào lệnh **Entry, Cắt Lỗ, Chốt Lời** dựa trên 3 đường SMA và báo qua Telegram.

**Lệnh chạy cơ bản:**
```powershell
python crypto_scanner.py
```
*Lưu ý: Bạn có thể chạy lệnh này bất cứ lúc nào. Khi chạy, bot sẽ lọc ra tối đa 5 đồng coin có tín hiệu đẹp nhất và in ra màn hình Bảng Xếp Hạng Top 5.*

---

## 2. Tool Theo Dõi Cắt Lỗ / Chốt Lời (Check Trades)
Nhiệm vụ: Sau khi Scanner tìm được coin và báo tín hiệu, các lệnh đó sẽ được lưu lại. Bạn dùng tool này để xem giá hiện tại đã chạm SL hay TP chưa. Nếu chạm, nó sẽ báo Telegram và xóa lệnh.

**Lệnh chạy cơ bản:**
```powershell
python check_trades.py
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

## 3. Hướng Dẫn Cấu Hình Telegram (Tùy Chọn)
Nếu bạn không muốn lúc nào cũng phải gõ lệnh mà muốn bot tự động nhắn tin cho bạn qua Telegram khi có sóng lớn:
1. Mở file `crypto_scanner.py` bằng Notepad hoặc VS Code.
2. Tìm đến dòng 10 và 11, thay thế 2 dòng này bằng thông tin bot của bạn:
   - `TELEGRAM_BOT_TOKEN = "Mã token lấy từ @BotFather"`
   - `TELEGRAM_CHAT_ID = "Mã chat id lấy từ @userinfobot"`
3. Bạn có thể sử dụng các công cụ như Task Scheduler của Windows để cho file python tự động chạy ngầm mỗi 15 phút 1 lần.
