# 📊 BÁO CÁO BACKTEST LÃI KÉP 11 THÁNG (TỪ THÁNG 1 ĐẾN THÁNG 11/2026)
## CHIẾN LƯỢC: SCALPING VOLUME PROFILE M5 + CỘT TÍM VSA WYCKOFF (STOPPING VOLUME)
*Nguồn dữ liệu: Nến M5 thực tế từ MetaTrader 5 Broker Exness (63,669 nến Vàng & 94,309 nến Bitcoin).*

---

## 1. THIẾT LẬP BÀI TOÁN QUẢN LÝ VỐN LÃI KÉP (COMPOUNDING)
- **Vốn khởi điểm (Starting Capital):** **$2,000.00 USD**.
- **Cơ chế đánh theo % tài khoản:** Cố định **2.0% vốn hiện tại** cho mỗi lệnh.
  - Lệnh có lãi $\rightarrow$ Lợi nhuận cộng trực tiếp vào vốn $\rightarrow$ Lệnh sau đánh trên số vốn lớn hơn (Lãi kép).
  - Lệnh thua lỗ $\rightarrow$ Vốn giảm $\rightarrow$ Lệnh sau giảm rủi ro tiền mặt xuống để bảo toàn tài khoản.
- **Tỷ lệ Chốt lời / Cắt lỗ (R:R):**
  - **TP1:** R:R 1:1.2 $\rightarrow$ Chốt 50% khối lượng ($+1.2\%$ vốn) & dời SL về Entry hòa vốn.
  - **TP2:** R:R 1:2.5 $\rightarrow$ Chốt nốt 50% khối lượng ($+2.5\%$ vốn). Tổng ăn trọn Full TP2 = $+3.7\%$ vốn.
  - **Dính SL:** $-2.0\%$ vốn.

---

## 2. 👑 KẾT QUẢ BITCOIN (BTCUSD - MT5)

### 📈 Bảng Chi Tiết Từng Tháng (Tháng 1 đến Tháng 11):
| Tháng | Số Kèo | Full TP2 | TP1 + BE | Dính SL | Winrate (%) | PnL Tháng ($) | Vốn Cuối Tháng | Tăng Trưởng (%) |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **2026-01** | 7 | 0 | 3 | 4 | 42.9% | -$88.05 | $1,911.95 | -4.40% |
| **2026-02** | 4 | 0 | 3 | 1 | 75.0% | +$30.03 | $1,941.97 | +1.57% |
| **2026-03** | 3 | 1 | 1 | 1 | 66.7% | +$55.26 | $1,997.23 | +2.85% |
| **2026-04** | 4 | 0 | 1 | 3 | 25.0% | -$94.90 | $1,902.34 | -4.75% |
| **2026-05** | 6 | 4 | 2 | 0 | **100.0%** | **+$350.68** | **$2,253.01** | **+18.43%** 🚀 |
| **2026-06** | 6 | 2 | 2 | 2 | 66.7% | +$130.04 | $2,383.06 | +5.77% |
| **2026-07** | 3 | 2 | 0 | 1 | 66.7% | +$128.36 | $2,511.41 | +5.39% |
| **2026-08** | 2 | 0 | 0 | 2 | 0.0% | -$99.45 | $2,411.96 | -3.96% |
| **2026-09** | 6 | 4 | 1 | 1 | **83.3%** | **+$354.29** | **$2,766.25** | **+14.69%** 🚀 |
| **2026-10** | 1 | 1 | 0 | 0 | **100.0%** | +$102.35 | **$2,868.60** | +3.70% |
| **2026-11** | 4 | 0 | 0 | 4 | 0.0% | -$222.69 | $2,645.91 | -7.76% |

### 🏆 Tổng Kết BTC Sau 11 Tháng:
* **Vốn ban đầu:** $2,000.00
* **Vốn hiện tại:** **$2,645.91**
* **Lợi nhuận ròng (Net Profit):** **+$645.91 (+32.30% ROI)**
* **Tỷ lệ thắng (Winrate):** **58.7%** (27 kèo có lãi / 46 kèo)
* **Tụt giảm vốn tối đa (Max Drawdown):** **7.76%** (Kiểm soát rủi ro tuyệt hảo)

---

## 3. 🥇 KẾT QUẢ VÀNG (XAUUSD - MT5)

### 📈 Bảng Chi Tiết Từng Tháng (Tháng 1 đến Tháng 11):
| Tháng | Số Kèo | Full TP2 | TP1 + BE | Dính SL | Winrate (%) | PnL Tháng ($) | Vốn Cuối Tháng | Tăng Trưởng (%) |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **2026-01** | 1 | 0 | 1 | 0 | 100.0% | +$24.00 | $2,024.00 | +1.20% |
| **2026-02** | 2 | 1 | 0 | 1 | 50.0% | +$32.91 | $2,056.91 | +1.63% |
| **2026-03** | 5 | 2 | 0 | 3 | 40.0% | +$24.95 | $2,081.86 | +1.21% |
| **2026-04** | 5 | 2 | 0 | 3 | 40.0% | +$25.25 | $2,107.11 | +1.21% |
| **2026-05** | 4 | 1 | 2 | 1 | **75.0%** | +$85.96 | $2,193.07 | +4.08% |
| **2026-06** | 4 | 1 | 2 | 1 | **75.0%** | +$89.47 | **$2,282.54** | +4.08% |
| **2026-07** | 3 | 0 | 1 | 2 | 33.3% | -$64.08 | $2,218.46 | -2.81% |
| **2026-08** | 4 | 1 | 0 | 3 | 25.0% | -$53.21 | $2,165.25 | -2.40% |
| **2026-09** | 4 | 1 | 0 | 3 | 25.0% | -$51.93 | $2,113.32 | -2.40% |
| **2026-10** | 4 | 1 | 0 | 3 | 25.0% | -$50.69 | $2,062.63 | -2.40% |
| **2026-11** | 1 | 0 | 0 | 1 | 0.0% | -$41.25 | $2,021.38 | -2.00% |

### 🏆 Tổng Kết Vàng Sau 11 Tháng:
* **Vốn ban đầu:** $2,000.00
* **Vốn hiện tại:** **$2,021.38**
* **Lợi nhuận ròng (Net Profit):** **+$21.38 (+1.07% ROI)**
* **Tỷ lệ thắng (Winrate):** **43.2%** (16 kèo có lãi / 37 kèo)
* **Tụt giảm vốn tối đa (Max Drawdown):** **13.21%**

---

## 4. ĐÁNH GIÁ VÀ NHẬN XÉT CỦA HỆ THỐNG
1. **Sức mạnh của Lãi Kép & Quản lý vốn theo %:**
   - Dù có chuỗi thua ở một số tháng biến động mạnh, tài khoản không bao giờ bị tổn thương nặng vì mỗi lần thua, số tiền mất tự động giảm theo quy mô vốn hiện tại.
   - Khi vào chu kỳ sóng thuận (như Tháng 5, 6, 7, 9 của BTC), tài khoản tăng trưởng bùng nổ theo cấp số nhân (+18.43%, +14.69%).
2. **Cột Tím VSA Wyckoff:**
   - Số lượng lệnh cả năm chỉ rơi vào **37 - 46 kèo** (~3 - 4 kèo/tháng). Không trade vô tội vạ, chỉ vào khi cá mập để lại nổ Volume hấp thụ tại cản.

