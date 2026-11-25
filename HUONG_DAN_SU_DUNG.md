# 🤖 HƯỚNG DẪN SỬ DỤNG HỆ THỐNG BOT TRADING & SĂN COIN (FX DREAM & COINRADAR)

Chào mừng bạn đến với hệ thống giao dịch tự động 24/7 **FX Dream Trading Bot** (`@fx_cryto_bot`). Hệ thống tích hợp toàn diện từ **Vàng (OANDA MT5)**, **Bitcoin/Ethereum (Binance)** đến **Săn Altcoins & Cổ phiếu Việt Nam**.

---

## 📑 MỤC LỤC
1. [Hệ Thống 2 Bot Chạy Song Song](#1-hệ-thống-2-bot-chạy-song-song)
2. [Hướng Dẫn Sử Dụng Menu Telegram](#2-hướng-dẫn-sử-dụng-menu-telegram)
3. [Cấu Trúc Báo Cáo Lệnh (Đang Vào - Đang Chạy - Đã Chốt)](#3-cấu-trúc-báo-cáo-lệnh)
4. [Lệnh Quản Lý Lệnh Thực Chiến (/themlenh, /xoalenh)](#4-lệnh-quản-lý-lệnh-thực-chiến)
5. [Cơ Chế Phân Quyền & Chế Độ Public (/public, /approve)](#5-cơ-chế-phân-quyền--chế-độ-public)
6. [Bộ Công Cụ Săn Crypto & Dòng Tiền Chạy Local](#6-bộ-công-cụ-săn-crypto--dòng-tiền-chạy-local)

---

## 1. HỆ THỐNG 2 BOT CHẠY SONG SONG

Bot vận hành đồng thời 2 chiến thuật độc lập cho cả **Vàng (XAUUSD)** và **Bitcoin (BTCUSDT)** để đa dạng hóa danh mục:

### ⚡ Phân Hệ 1: SCALPING M5 (VOLUME PROFILE & ORDER BLOCK)
* **Khung thời gian:** Khung M5 (kết hợp cấu trúc D1/W1).
* **Nguyên lý:** Xác định vùng tích luỹ khối lượng ngày hôm trước (yVAL, yPOC, yVAH), theo dõi sự dịch chuyển của dPOC hôm nay và săn tín hiệu rút râu cản M5 kèm nổ Volume.
* **Chiến lược chốt lời:**
  * **TP1:** R:R 1:1.2 (Chốt 50% khối lượng).
  * **Bảo vệ vốn:** Tự động dời Stop Loss về **Hoà Vốn (Breakeven)** ngay khi chạm TP1.
  * **Trailing Lock:** Đạt +1.5R ➔ Tự động khóa chặt +0.8R lợi nhuận.
  * **TP2 / Runner:** Gồng sóng theo tín hiệu đảo chiều CISD trên khung M15.

### 🧙‍♀️ Phân Hệ 2: SWING H1 (HỆ THỐNG MA NỮ - SENPAI THÀNH)
* **Khung thời gian:** Khung nến H1.
* **Nguyên lý:** Ứng dụng trọn bộ giáo trình nến Ma Nữ:
  * Chiêu 7 cơ bản (c7cb) & Chiêu 7 thân tăng (c7tt).
  * Kháng cự / Hỗ trợ nến đôi (Cản 2 nến), Râu cô đơn, Cản Linechart.
  * Phá vỡ nến trước (Break of previous candle) & Mô hình kiểm tra râu nến (Perfect wick).
* **Đặc điểm:** Tần suất vào lệnh chọn lọc, ăn sóng dài, giảm tối đa tín hiệu nhiễu.

---

## 2. HƯỚNG DẪN SỬ DỤNG MENU TELEGRAM

Bạn có thể bấm trực tiếp các nút bấm trên bàn phím Telegram hoặc gõ lệnh:

| Tên Nút Bấm | Lệnh Gõ | Chức Năng |
| :--- | :--- | :--- |
| 💵 **Xem Giá Live (Vàng/BTC/ETH)** | `/price`, `/gia` | Xem thị giá tức thời Vàng OANDA MT5, BTC & ETH Binance (HOD, LOD, Volume 24h). |
| 🔍 **Kiểm Tra Lệnh & Báo Cáo Ngày** | `/check` | Giám sát toàn diện 3 khu vực: Lệnh đang vào, Lệnh đang chạy và Kết quả trong ngày. |
| 📊 **Tổng Kết Kèo TP/SL** | `/tongket`, `/pnl` | Xem bảng tổng kết hiệu suất Winrate %, PnL Vàng & BTC theo 24h, 7 ngày và toàn thời gian. |
| ⚖️ **Báo Cáo Đối Đầu 2 Bot** | `/sosanh` | So sánh chi tiết tỷ lệ thắng, số kèo và PnL giữa Bot M5 Scalp và Bot H1 Swing. |
| 🧙‍♀️ **Swing H1 Ma Nữ (Senpai Thành)** | `/manu`, `/h1` | Phân tích chi tiết thị trường Vàng & BTC theo cấu trúc nến Ma Nữ H1. |
| 🎯 **Scalping Volume Profile M5** | `/scalp`, `/vp` | Xem chi tiết trục giá Volume Profile, dPOC, Daily Open và trạng thái bảo vệ cản M5. |
| ⚡ **Tuyệt Chiêu H4 Lưỡng Lự** | `/h4` | Bắt các pha bứt phá Breakout nến nén H4. |
| 💣 **Săn Coin Rác (Vol > $100M)** | `/meme`, `/coinrac` | Quét các Altcoin có dòng tiền bùng nổ, quản lý vốn rủi ro 2%. |
| 📈 **Tìm Coin TĂNG (LONG)** | `/long` | Lọc danh sách coin tích luỹ gom hàng trên Binance Spot/Futures. |
| 📉 **Tìm Coin GIẢM (SHORT)** | `/short` | Lọc danh sách coin phân phối xả hàng trên Binance. |
| 🇻🇳 **Đánh Giá Cổ Phiếu VN** | `/vnstock`, `/cp` | Phân tích định giá PE, tăng trưởng và dòng tiền cổ phiếu VN30 & sàn VN. |

---

## 3. CẤU TRÚC BÁO CÁO LỆNH

Khi bấm **`🔍 Kiểm Tra Lệnh & Báo Cáo Ngày`** (hoặc gõ `/check`), báo cáo được chia làm **3 mục rõ ràng**:

1. **⏳ 1. LỆNH ĐANG VÀO (LỆNH CHỜ / PENDING LIMIT):**
   * Danh sách các lệnh Limit đang treo sàn chờ giá hồi về khớp (hiển thị rõ khoảng cách tới giá hiện tại, mốc SL, TP1, TP2).
   * Nếu không có lệnh Limit treo, bot sẽ tóm tắt vùng cản đang rình đón của Vàng và BTC.
2. **🔥 2. LỆNH ĐANG CHẠY (ACTIVE & FLOATING PnL):**
   * Các lệnh đã khớp và đang chạy trực tiếp trên thị trường.
   * Hiển thị: Giá vào Entry ➔ Giá hiện tại, Lãi/Lỗ tạm tính thời gian thực (Xanh 🟢 / Đỏ 🔴), Trạng thái dời SL Hoà Vốn (Risk-Free).
3. **📜 3. LỆNH ĐÃ CÓ KẾT QUẢ TRONG NGÀY (HÔM NAY):**
   * Tự động tổng kết các lệnh đã đóng trong ngày hôm nay (từ 00:00 sáng đến nay).
   * Thống kê: Tổng số kèo hôm nay, Thắng, Hoà vốn, Cắt lỗ, Winrate % và Tổng PnL.
   * Chi tiết từng lệnh: Kèo ăn Full TP2, kèo dời BE ăn 50% TP1, hay kèo dính SL.

---

## 4. LỆNH QUẢN LÝ LỆNH THỰC CHIẾN

Dành cho Admin hoặc người dùng muốn bổ sung / khôi phục lệnh tay trực tiếp trên Telegram:

### ➕ Thêm / Khôi phục lệnh: `/themlenh`
* **Cú pháp:**
  ```text
  /themlenh <VANG|BTC> <BUY|SELL> <ENTRY> <SL> <TP1> [TP2] [H1|M5]
  ```
* **Ví dụ mẫu:**
  * Lệnh Vàng H1: `/themlenh VANG SELL 3580 3586 3572.8 3565 H1`
  * Lệnh BTC M5: `/themlenh BTC BUY 59000 58500 59600 60500 M5`
* **Cơ chế:** Bot sẽ lập tức nạp vị thế vào danh sách giám sát thời gian thực, tự động theo dõi giá live, tính PnL và tự động bắn thông báo khi chạm TP1 / dời SL Hoà Vốn / chạm TP2.

### 🗑️ Xoá / Reset lệnh đang mở: `/xoalenh`
* **Cú pháp:** `/xoalenh`
* **Chức năng:** Làm sạch danh sách các lệnh đang mở (giải phóng slot theo dõi).

---

## 5. CƠ CHẾ PHÂN QUYỀN & CHẾ ĐỘ PUBLIC

Hệ thống hỗ trợ cơ chế phân quyền bảo mật nhưng cực kỳ linh hoạt:

### 🌐 Chế độ Public (Hiện đang BẬT mặc định):
* **Bất kỳ ai** mở bot `@fx_cryto_bot` và bấm `/start` đều **tự động được cấp quyền ngay lập tức** mà không cần chờ duyệt.
* Người tham gia sẽ tự động được thêm vào danh sách nhận thông báo broadcast (khi có tín hiệu mới hoặc báo cáo định kỳ, bot sẽ gửi đồng loạt cho mọi người).
* Mỗi khi có người mới mở bot, Admin sẽ nhận được tin nhắn thông báo: `📢 [THÀNH VIÊN MỚI THAM GIA BOT (PUBLIC)]`.

### ⚙️ Các lệnh điều khiển quyền (Dành riêng cho Admin):
* **Chuyển đổi chế độ Public / Private:**
  * `/public off` ➔ Chuyển sang chế độ **Riêng tư (Private)**: Người lạ vào sẽ bị chặn và phải chờ Admin duyệt bằng `/approve`.
  * `/public on` ➔ Chuyển sang chế độ **Cộng đồng (Public)**: Mở tự do cho mọi người sử dụng.
* **Duyệt thành viên thủ công:**
  * `/approve <ID_Telegram>` ➔ Cấp quyền cho một Telegram ID cụ thể.
* **Huỷ quyền thành viên:**
  * `/revoke <ID_Telegram>` ➔ Thu hồi quyền sử dụng của một Telegram ID.
* **Xem danh sách thành viên:**
  * `/users` hoặc `/members` ➔ Liệt kê toàn bộ danh sách người đang được cấp quyền.

---

## 6. BỘ CÔNG CỤ SĂN CRYPTO & DÒNG TIỀN CHẠY LOCAL

Ngoài Bot Telegram 24/7 trên Render, bạn vẫn có thể chạy các công cụ phân tích dòng tiền chuyên sâu ngay trên máy tính cá nhân:

```powershell
.\run_scanner.bat                      # Quét coin tích luỹ gom hàng Binance (~1 phút)
.\run_flow.bat BTC/USDT                # Soi bảng dòng tiền Inflow/Outflow đa khung (như CoinGlass)
.\run_flow.bat IMX/USDT
.\run_backtest.bat VANRY/USDT          # Kiểm thử chiến lược trên dữ liệu lịch sử
.\run_check.bat                        # Kiểm tra trạng thái SL/TP offline
```

*Lưu ý trên Windows PowerShell: Luôn có `.\` phía trước file `.bat` để thực thi.*
