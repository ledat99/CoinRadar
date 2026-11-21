# 🤖 HƯỚNG DẪN VẬN HÀNH & HỆ THỐNG TỰ ĐỘNG TRIỂN KHAI (DEVOPS COINRADAR)

File này lưu trữ thông tin cấu hình và hướng dẫn để trợ lý AI (hoặc bạn) có thể tự động triển khai cập nhật lên Render Cloud mà **không bao giờ cần hỏi lại Token hay API Key**.

---

## 📌 1. THÔNG TIN CẤU HÌNH ĐÃ LƯU TRỮ TRONG `.env`

Tất cả các mã bí mật được lưu an toàn tại file [`.env`](file:///c:/Users/vivas/Desktop/Coin/.env) (đã được thêm vào `.gitignore` để tránh lộ ra ngoài GitHub):

| Thành phần | Tên biến | Giá trị lưu trữ |
| :--- | :--- | :--- |
| **Telegram Bot Token** | `TELEGRAM_BOT_TOKEN` | `9051874352:AAFrnfJ8Mm0QF4wBlz8V3vYjYiqz5_sIVF8` |
| **Telegram Chat ID** | `TELEGRAM_CHAT_ID` | `6022180065` (User: Lê Duy Đạt) |
| **Render API Key** | `RENDER_API_KEY` | `rnd_luHWASkAdTcoKs2HyI6PpV2xxJYE` |
| **Render Service ID** | `RENDER_SERVICE_ID` | `srv-dc0gn5k0916s73bm1d4g` |
| **GitHub Repo** | `GITHUB_REPO` | `https://github.com/ledat99/CoinRadar.git` (`master`) |

---

## 🚀 2. QUY TRÌNH TỰ ĐỘNG ĐẨY LÊN RENDER (CHO AI & DEV)

Bất kỳ khi nào bạn yêu cầu sửa đổi code hoặc thêm tính năng mới, AI chỉ cần thực hiện 1 câu lệnh duy nhất:

```bash
git add . && git commit -m "Cập nhật tính năng" && git push origin master
```

### Cơ chế Auto-Deploy của Render:
1. Vì dịch vụ **`coinradar-tele-bot`** trên Render đã được kết nối với nhánh `master` của GitHub `ledat99/CoinRadar` và bật `autoDeploy: true`.
2. Do đó, **ngay khi code được `git push` lên GitHub, Render sẽ TỰ ĐỘNG phát hiện và kéo code mới về deploy** mà không cần thao tác tay.
3. Nếu cần ép Render deploy ngay lập tức qua API (Force Deploy), AI chỉ cần gọi API sau bằng `RENDER_API_KEY`:
   ```bash
   POST https://api.render.com/v1/services/srv-dc0gn5k0916s73bm1d4g/deploys
   Header: Authorization: Bearer rnd_luHWASkAdTcoKs2HyI6PpV2xxJYE
   ```

---

## 📱 3. CÁC NÚT ĐIỀU KHIỂN TRÊN TELEGRAM (@fx_cryto_bot)

- 📈 **Tìm Coin TĂNG (LONG)**: Quét siêu tốc các coin thanh khoản cao trên Binance Futures đang có xu hướng giữ giá / tăng trưởng kèm Entry, SL, TP (R:R 1:2) và tự động lưu lệnh theo dõi.
- 📉 **Tìm Coin GIẢM (SHORT)**: Quét các coin gãy cản, dòng tiền xả mạnh nhất thị trường.
- 👑 **Phân Tích BTC**: Kiểm tra Market Bias (H4 & H1) + RSI + Tín hiệu Entry/SL/TP và % vốn quản lý rủi ro 2%.
- 🥇 **Phân Tích VÀNG (XAU)**: Lấy trực tiếp dữ liệu nến, volume và RSI từ biểu đồ **TradingView (OANDA:XAUUSD)**.
- 🔍 **Kiểm Tra Lệnh & Báo Cáo Ngày**: Kiểm tra các lệnh đã chạm SL/TP chưa, hiện lãi/lỗ tạm thời (Floating PnL) và tổng kết số lệnh Thắng/Thua trong ngày.

