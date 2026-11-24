//+------------------------------------------------------------------+
//|                               FXDream_VolumeProfile_Scalper.mq5 |
//|                                  Copyright 2026, FX DREAM SYSTEM |
//|        Chiến Lược Scalping Volume Profile Ngày Hôm Trước M5     |
//+------------------------------------------------------------------+
#property copyright   "FX DREAM SYSTEM"
#property link        "https://t.me/fxdream"
#property version     "2.00"
#property description "EA Scalping chuẩn Volume Profile hôm trước (yVAL, yPOC, yVAH) + Phản ứng râu M5 + Nổ Volume bảo vệ cản"
#property strict

#include <Trade\Trade.mqh>

enum ENUM_ASSET_TYPE
{
   ASSET_AUTO = 0, // Tự động nhận diện
   ASSET_GOLD = 1, // Vàng (XAUUSD)
   ASSET_BTC  = 2  // Bitcoin (BTCUSD)
};

//--- Inputs
input group "=== Cài Đặt Giao Dịch ==="
input bool              InpAutoTrade       = true;        // Bật / Tắt tự động vào lệnh
input double            InpLotSize         = 0.01;        // Khối lượng lệnh cố định (Lot)
input bool              InpUseAutoLot      = false;       // Tự động tính Lot theo % Rủi Ro
input double            InpRiskPct         = 2.0;         // % Rủi ro mỗi lệnh (nếu dùng AutoLot)
input ulong             InpMagicNumber     = 20261124;    // Magic Number quản lý lệnh
input ulong             InpSlippage        = 30;          // Độ trượt giá tối đa (points)

input group "=== Cấu Hình Volume Profile Ngày Hôm Trước ==="
input int               InpRows            = 50;          // Số hàng chia nấc giá (Price Bins)
input double            InpVaPct           = 70.0;        // Tỷ lệ Value Area (%)
input bool              InpUseTrendFilter  = true;        // Bộ lọc xu hướng ngày (Chống bắt dao rơi)
input int               InpVolLen          = 20;          // Chu kỳ tính SMA Volume M5
input double            InpVolMult         = 1.8;         // Volume M5 chuẩn VSA Cột Tím (>= 1.8x SMA20)
input double            InpWickRatio       = 0.40;        // Tỷ lệ râu nến tối thiểu (40% biên độ chuẩn Pinbar)

input group "=== Quản Lý Lợi Nhuận & Rủi Ro (R:R) ==="
input ENUM_ASSET_TYPE   InpAssetMode       = ASSET_AUTO;  // Chế độ tài sản
input double            InpRR_TP1          = 1.2;         // Tỷ lệ R:R cho TP1 (Chốt 50% & Dời Hoà)
input double            InpRR_TP2          = 2.0;         // Tỷ lệ R:R cho TP2 (Điểm ngọt 2.0R tối ưu 41.2% sóng)
input bool              InpUseTrailingLock = true;        // Bật khóa lãi bậc thang (Trailing Lock-in)
input double            InpLockTriggerRR   = 1.5;         // Mức R:R kích hoạt khóa lãi (+1.5R)
input double            InpLockProfitRR    = 0.8;         // Mức R:R khóa cứng bảo toàn (+0.8R)
input bool              InpUseM15Runner    = true;        // Bật chế độ Gồng Dài theo CISD M15 (Không chốt non TP2)
input double            InpMinRunnerRR     = 2.2;         // Bắt đầu quét CISD M15 khi đạt R:R >= 2.2
input double            InpGoldMinSL       = 5.5;         // [Vàng] SL tối thiểu (giá)
input double            InpGoldMaxSL       = 9.5;         // [Vàng] SL tối đa (giá)
input double            InpGoldBuf         = 0.8;         // [Vàng] Buffer đệm ngoài râu nến (giá)
input double            InpBtcMinSL        = 250.0;       // [BTC] SL tối thiểu (USD)
input double            InpBtcMaxSL        = 420.0;       // [BTC] SL tối đa (USD)
input double            InpBtcBuf          = 35.0;        // [BTC] Buffer đệm ngoài râu nến (USD)

//--- Biến toàn cục
CTrade      ExtTrade;
datetime    ExtLastBarTime   = 0;
bool        ExtIsGold        = false;
bool        ExtIsBtc         = false;
double      ExtMinSL         = 5.5;
double      ExtMaxSL         = 9.5;
double      ExtBuf           = 0.8;

// Cấu trúc lưu trữ Profile ngày hôm trước
struct SYesterdayProfile
{
   datetime day;
   double   poc;
   double   val;
   double   vah;
   double   high;
   double   low;
   string   shape;      // L-Shape, P-Shape, D-Shape
   bool     is_bull;    // Xu hướng ngày hôm trước tăng
   bool     is_bear;    // Xu hướng ngày hôm trước giảm
   bool     valid;
};

SYesterdayProfile ExtYProfile;

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
{
   ExtTrade.SetExpertMagicNumber(InpMagicNumber);
   ExtTrade.SetDeviationInPoints(InpSlippage);
   ExtTrade.SetTypeFilling(ORDER_FILLING_IOC);

   // Nhận diện tài sản
   string sym = _Symbol;
   StringToUpper(sym);
   if(InpAssetMode == ASSET_GOLD || StringFind(sym, "XAU") >= 0 || StringFind(sym, "GOLD") >= 0)
   {
      ExtIsGold = true;
      ExtMinSL  = InpGoldMinSL;
      ExtMaxSL  = InpGoldMaxSL;
      ExtBuf    = InpGoldBuf;
      Print("✅ Khởi động EA cho VÀNG (XAUUSD). SL Buffer: ", ExtBuf, " | SL Limit: [", ExtMinSL, " - ", ExtMaxSL, "]");
   }
   else if(InpAssetMode == ASSET_BTC || StringFind(sym, "BTC") >= 0)
   {
      ExtIsBtc  = true;
      ExtMinSL  = InpBtcMinSL;
      ExtMaxSL  = InpBtcMaxSL;
      ExtBuf    = InpBtcBuf;
      Print("✅ Khởi động EA cho BITCOIN (BTCUSD). SL Buffer: ", ExtBuf, " | SL Limit: [", ExtMinSL, " - ", ExtMaxSL, "]");
   }
   else
   {
      ExtIsGold = true; // Mặc định chế độ Vàng
      ExtMinSL  = InpGoldMinSL;
      ExtMaxSL  = InpGoldMaxSL;
      ExtBuf    = InpGoldBuf;
   }

   ExtYProfile.valid = false;
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   Print("🛑 Dừng EA Volume Profile Scalper. Lý do: ", reason);
}

//+------------------------------------------------------------------+
//| Tính toán Volume Profile ngày hôm trước                          |
//+------------------------------------------------------------------+
bool CalculateYesterdayProfile(SYesterdayProfile &yp)
{
   MqlDateTime dt_now;
   TimeCurrent(dt_now);

   // Thời điểm đầu ngày hôm nay 00:00:00
   datetime today_start = StringToTime(StringFormat("%04d.%02d.%02d 00:00:00", dt_now.year, dt_now.mon, dt_now.day));
   // Thời điểm đầu ngày hôm qua 00:00:00
   datetime yest_start  = today_start - 86400;

   // Lấy các nến M5 trong ngày hôm qua
   MqlRates rates[];
   int copied = CopyRates(_Symbol, PERIOD_M5, yest_start, today_start, rates);
   if(copied < 50)
   {
      // Nếu là đầu tuần (Thứ Hai), lùi 3 ngày để lấy nến Thứ Sáu
      if(dt_now.day_of_week == 1) // Thứ Hai
      {
         yest_start = today_start - 3 * 86400;
         datetime yest_end = yest_start + 86400;
         copied = CopyRates(_Symbol, PERIOD_M5, yest_start, yest_end, rates);
      }
      if(copied < 50) return false;
   }

   double min_p = DBL_MAX;
   double max_p = -DBL_MAX;
   for(int i = 0; i < copied; i++)
   {
      if(rates[i].low  < min_p) min_p = rates[i].low;
      if(rates[i].high > max_p) max_p = rates[i].high;
   }

   if(max_p <= min_p || InpRows < 10) return false;

   double bin_size = (max_p - min_p) / InpRows;
   double bins[];
   ArrayResize(bins, InpRows);
   ArrayInitialize(bins, 0.0);
   double total_vol = 0.0;

   for(int i = 0; i < copied; i++)
   {
      double v = (double)rates[i].tick_volume;
      total_vol += v;
      int b_start = (int)MathMax(0, MathMin(InpRows - 1, MathFloor((rates[i].low  - min_p) / bin_size)));
      int b_end   = (int)MathMax(0, MathMin(InpRows - 1, MathFloor((rates[i].high - min_p) / bin_size)));
      int n_bins  = b_end - b_start + 1;
      double v_bin = v / n_bins;
      for(int k = b_start; k <= b_end; k++)
         bins[k] += v_bin;
   }

   // Tìm POC
   double max_bin_vol = 0.0;
   int poc_idx = 0;
   for(int k = 0; k < InpRows; k++)
   {
      if(bins[k] > max_bin_vol)
      {
         max_bin_vol = bins[k];
         poc_idx = k;
      }
   }

   // Tính Value Area 70%
   double va_target = total_vol * (InpVaPct / 100.0);
   double va_vol    = bins[poc_idx];
   int up_idx       = poc_idx;
   int dn_idx       = poc_idx;

   while(va_vol < va_target && (up_idx < InpRows - 1 || dn_idx > 0))
   {
      double next_up = (up_idx < InpRows - 1) ? bins[up_idx + 1] : 0.0;
      double next_dn = (dn_idx > 0)           ? bins[dn_idx - 1] : 0.0;

      if(next_up >= next_dn && up_idx < InpRows - 1)
      {
         up_idx++;
         va_vol += bins[up_idx];
      }
      else if(dn_idx > 0)
      {
         dn_idx--;
         va_vol += bins[dn_idx];
      }
      else break;
   }

   yp.day   = yest_start;
   yp.poc   = NormalizeDouble(min_p + (poc_idx + 0.5) * bin_size, _Digits);
   yp.val   = NormalizeDouble(min_p + dn_idx * bin_size, _Digits);
   yp.vah   = NormalizeDouble(min_p + (up_idx + 1) * bin_size, _Digits);
   yp.low   = NormalizeDouble(min_p, _Digits);
   yp.high  = NormalizeDouble(max_p, _Digits);

   // Phân loại hình thái xoay trục
   double d_val_poc = MathAbs(yp.poc - yp.val);
   double d_vah_poc = MathAbs(yp.vah - yp.poc);
   if(d_val_poc < d_vah_poc * 0.75)
      yp.shape = "L-Shape";  // Volume dồn đáy -> Canh Buy
   else if(d_vah_poc < d_val_poc * 0.75)
      yp.shape = "P-Shape";  // Volume dồn đỉnh -> Canh Sell
   else
      yp.shape = "D-Shape";  // Cân bằng

   // Xu hướng ngày hôm trước
   double y_open  = rates[0].open;
   double y_close = rates[copied - 1].close;
   yp.is_bull = (y_close > y_open && y_close > yp.poc);
   yp.is_bear = (y_close < y_open && y_close < yp.poc);
   yp.valid   = true;

   return true;
}

//+------------------------------------------------------------------+
//| Kiểm tra lệnh đang mở và xử lý TP1 (chốt 50% & dời Hoà Vốn)      |
//+------------------------------------------------------------------+
void ManageOpenTrades()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagicNumber) continue;

      long pos_type   = PositionGetInteger(POSITION_TYPE);
      double open_p   = PositionGetDouble(POSITION_PRICE_OPEN);
      double curr_sl  = PositionGetDouble(POSITION_SL);
      double curr_tp  = PositionGetDouble(POSITION_TP);
      double lot      = PositionGetDouble(POSITION_VOLUME);
      string comment  = PositionGetString(POSITION_COMMENT);
      double curr_p   = PositionGetDouble(POSITION_PRICE_CURRENT);

      // Nếu lệnh chưa chốt TP1 (comment không chứa BE_FREE)
      if(StringFind(comment, "FREE_RISK") < 0)
      {
         // 1. Kiểm tra Lệnh BUY
         if(pos_type == POSITION_TYPE_BUY)
         {
            double tp1_level = open_p + (open_p - curr_sl) * (InpRR_TP1 / 1.0);
            if(curr_p >= tp1_level && curr_sl < open_p)
            {
               // Chốt 50% khối lượng
               double half_lot = NormalizeDouble(lot * 0.5, 2);
               if(half_lot >= SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN))
               {
                  ExtTrade.PositionClosePartial(ticket, half_lot);
                  Print("🎯 [TP1 BUY] Đã chốt 50% lot (", half_lot, "). Dời SL về Hoà Vốn: ", open_p);
               }
               // Dời SL về Hoà vốn, bỏ TP cứng nếu bật Gồng Runner M15
               ExtTrade.PositionModify(ticket, open_p, InpUseM15Runner ? 0.0 : curr_tp);
            }
            // Cơ chế Gồng Dài Runner theo CISD M15 (khi đã dời hoà vốn)
            else if(curr_sl >= open_p)
            {
               // Khóa lãi bậc thang: khi giá đạt +1.5R, nâng SL lên +0.8R để tránh bị tuột về hoà vốn
               if(InpUseTrailingLock && curr_sl < open_p + ExtMinSL * InpLockProfitRR)
               {
                  double lock_trigger = open_p + ExtMinSL * InpLockTriggerRR;
                  if(curr_p >= lock_trigger)
                  {
                     double locked_sl = NormalizeDouble(open_p + ExtMinSL * InpLockProfitRR, _Digits);
                     ExtTrade.PositionModify(ticket, locked_sl, curr_tp);
                     Print("🛡️ [TRAILING LOCK BUY] Giá đã đạt +", InpLockTriggerRR, "R. Tự động nâng SL khóa cứng +", InpLockProfitRR, "R tại: ", locked_sl);
                  }
               }

               if(InpUseM15Runner)
               {
                  double cur_rr = (curr_p - open_p) / ExtMinSL;
                  if(cur_rr >= InpMinRunnerRR)
                  {
                     MqlRates m15_rates[];
                     if(CopyRates(_Symbol, PERIOD_M15, 1, 3, m15_rates) >= 2)
                     {
                        int sz = ArraySize(m15_rates);
                        bool is_cisd_bear = (m15_rates[sz - 1].close < m15_rates[sz - 1].open) && 
                                            (m15_rates[sz - 1].close < MathMin(m15_rates[sz - 2].open, m15_rates[sz - 2].close)) && 
                                            (m15_rates[sz - 2].close > m15_rates[sz - 2].open);
                        if(is_cisd_bear)
                        {
                           ExtTrade.PositionClose(ticket);
                           Print("🏁 [M15 CISD BEARISH] Xuất hiện Change in State of Delivery đảo chiều! Đóng toàn bộ phần Runner BUY. Lời: +", DoubleToString(cur_rr, 1), "R");
                        }
                     }
                  }
               }
            }
         }
         // 2. Kiểm tra Lệnh SELL
         else if(pos_type == POSITION_TYPE_SELL)
         {
            double tp1_level = open_p - (curr_sl - open_p) * (InpRR_TP1 / 1.0);
            if(curr_p <= tp1_level && curr_sl > open_p)
            {
               double half_lot = NormalizeDouble(lot * 0.5, 2);
               if(half_lot >= SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN))
               {
                  ExtTrade.PositionClosePartial(ticket, half_lot);
                  Print("🎯 [TP1 SELL] Đã chốt 50% lot (", half_lot, "). Dời SL về Hoà Vốn: ", open_p);
               }
               // Dời SL về Hoà vốn, bỏ TP cứng nếu bật Gồng Runner M15
               ExtTrade.PositionModify(ticket, open_p, InpUseM15Runner ? 0.0 : curr_tp);
            }
            // Cơ chế Gồng Dài Runner theo CISD M15 (khi đã dời hoà vốn)
            else if(curr_sl <= open_p)
            {
               // Khóa lãi bậc thang: khi giá đạt +1.5R, nâng SL lên +0.8R để tránh bị tuột về hoà vốn
               if(InpUseTrailingLock && curr_sl > open_p - ExtMinSL * InpLockProfitRR)
               {
                  double lock_trigger = open_p - ExtMinSL * InpLockTriggerRR;
                  if(curr_p <= lock_trigger)
                  {
                     double locked_sl = NormalizeDouble(open_p - ExtMinSL * InpLockProfitRR, _Digits);
                     ExtTrade.PositionModify(ticket, locked_sl, curr_tp);
                     Print("🛡️ [TRAILING LOCK SELL] Giá đã đạt +", InpLockTriggerRR, "R. Tự động nâng SL khóa cứng +", InpLockProfitRR, "R tại: ", locked_sl);
                  }
               }

               if(InpUseM15Runner)
               {
                  double cur_rr = (open_p - curr_p) / ExtMinSL;
                  if(cur_rr >= InpMinRunnerRR)
                  {
                     MqlRates m15_rates[];
                     if(CopyRates(_Symbol, PERIOD_M15, 1, 3, m15_rates) >= 2)
                     {
                        int sz = ArraySize(m15_rates);
                        bool is_cisd_bull = (m15_rates[sz - 1].close > m15_rates[sz - 1].open) && 
                                            (m15_rates[sz - 1].close > MathMax(m15_rates[sz - 2].open, m15_rates[sz - 2].close)) && 
                                            (m15_rates[sz - 2].close < m15_rates[sz - 2].open);
                        if(is_cisd_bull)
                        {
                           ExtTrade.PositionClose(ticket);
                           Print("🏁 [M15 CISD BULLISH] Xuất hiện Change in State of Delivery đảo chiều! Đóng toàn bộ phần Runner SELL. Lời: +", DoubleToString(cur_rr, 1), "R");
                        }
                     }
                  }
               }
            }
         }
      }
   }
}

//+------------------------------------------------------------------+
//| Đếm số lệnh đang mở thuộc EA                                     |
//+------------------------------------------------------------------+
int CountOpenPositions()
{
   int count = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) == _Symbol &&
         PositionGetInteger(POSITION_MAGIC) == InpMagicNumber)
         count++;
   }
   return count;
}

//+------------------------------------------------------------------+
//| Tính Lot theo tỷ lệ rủi ro (%) hoặc dùng Lot cố định            |
//+------------------------------------------------------------------+
double CalculateLot(double sl_dist)
{
   if(!InpUseAutoLot || sl_dist <= 0) return InpLotSize;
   double balance = AccountInfoDouble(ACCOUNT_BALANCE);
   double risk_usd = balance * (InpRiskPct / 100.0);
   double tick_val = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double tick_size = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   if(tick_val <= 0 || tick_size <= 0) return InpLotSize;

   double points = sl_dist / _Point;
   double lot = risk_usd / (points * (tick_val / (tick_size / _Point)));
   double min_lot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double max_lot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double step    = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);

   lot = MathFloor(lot / step) * step;
   return MathMax(min_lot, MathMin(max_lot, lot));
}

//+------------------------------------------------------------------+
//| OnTick function                                                  |
//+------------------------------------------------------------------+
void OnTick()
{
   // Quản lý dời SL và chốt TP1 theo thời gian thực (mỗi tick)
   ManageOpenTrades();

   if(!InpAutoTrade) return;

   // Chỉ phân tích vào lệnh khi có NẾN M5 MỚI VỪA ĐÓNG CỬA
   datetime current_m5_time = iTime(_Symbol, PERIOD_M5, 0);
   if(current_m5_time == ExtLastBarTime) return;
   ExtLastBarTime = current_m5_time;

   // Cập nhật Profile ngày hôm trước
   if(!CalculateYesterdayProfile(ExtYProfile)) return;

   // Mỗi thời điểm chỉ duy nhất 1 lệnh active để chống gồng lỗ/spam
   if(CountOpenPositions() > 0) return;

   // Lấy nến M5 vừa đóng cửa (chỉ số 1)
   MqlRates rates[];
   if(CopyRates(_Symbol, PERIOD_M5, 1, InpVolLen + 5, rates) < InpVolLen + 1) return;

   // Nến chỉ số 0 trong mảng rates chính là nến index 1 trên chart (nến vừa đóng)
   int last_idx = ArraySize(rates) - 1;
   double o  = rates[last_idx].open;
   double h  = rates[last_idx].high;
   double l  = rates[last_idx].low;
   double cl = rates[last_idx].close;
   double v  = (double)rates[last_idx].tick_volume;
   double rng = h - l;
   if(rng <= 0) return;

   // Tính SMA Volume 20 nến trước
   double sum_vol = 0.0;
   for(int k = 0; k < InpVolLen; k++)
      sum_vol += (double)rates[last_idx - 1 - k].tick_volume;
   double avg_vol = sum_vol / InpVolLen;
   bool is_vol_spike = (v >= InpVolMult * avg_vol);

   // Dung sai tiếp cận vùng cản
   double tol = ExtIsGold ? 1.2 : 70.0;

   // 1. KÈO BUY XOAY TRỤC (L-Shape hoặc D-Shape phản ứng tại yVAL/yPOC)
   double lower_wick = MathMin(o, cl) - l;
   bool rejection_buy = (lower_wick >= InpWickRatio * rng) &&
                        (l <= ExtYProfile.val + tol) &&
                        (cl >= ExtYProfile.val - (ExtIsGold ? 0.6 : 30.0));

   // Bộ lọc xu hướng (không bắt dao rơi nếu ngày hôm trước xả dốc mạnh)
   bool allow_buy = !InpUseTrendFilter || !ExtYProfile.is_bear;

   if(allow_buy && (ExtYProfile.shape == "L-Shape" || ExtYProfile.shape == "D-Shape") && rejection_buy && is_vol_spike)
   {
      double entry = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      double sl_p  = l - ExtBuf;
      double sl_dist = entry - sl_p;

      if(sl_dist < ExtMinSL) sl_p = entry - ExtMinSL;
      else if(sl_dist > ExtMaxSL) sl_p = entry - ExtMaxSL;
      sl_dist = entry - sl_p;

      double tp1 = NormalizeDouble(entry + sl_dist * InpRR_TP1, _Digits);
      double tp2 = NormalizeDouble(MathMin(entry + sl_dist * InpRR_TP2, ExtYProfile.vah), _Digits);
      if(tp2 <= tp1) tp2 = NormalizeDouble(entry + sl_dist * InpRR_TP2, _Digits);

      double lot = CalculateLot(sl_dist);
      ExtTrade.Buy(lot, _Symbol, entry, sl_p, tp2, "FXDream_Buy_VP");
      Print("🚀 [MỞ LỆNH BUY] Entry: ", entry, " | SL: ", sl_p, " | TP1: ", tp1, " | TP2: ", tp2, " (Hình thái: ", ExtYProfile.shape, ")");
      return;
   }

   // 2. KÈO SELL XOAY TRỤC (P-Shape hoặc D-Shape phản ứng tại yVAH/yPOC)
   double upper_wick = h - MathMax(o, cl);
   bool rejection_sell = (upper_wick >= InpWickRatio * rng) &&
                         (h >= ExtYProfile.vah - tol) &&
                         (cl <= ExtYProfile.vah + (ExtIsGold ? 0.6 : 30.0));

   bool allow_sell = !InpUseTrendFilter || !ExtYProfile.is_bull;

   if(allow_sell && (ExtYProfile.shape == "P-Shape" || ExtYProfile.shape == "D-Shape") && rejection_sell && is_vol_spike)
   {
      double entry = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      double sl_p  = h + ExtBuf;
      double sl_dist = sl_p - entry;

      if(sl_dist < ExtMinSL) sl_p = entry + ExtMinSL;
      else if(sl_dist > ExtMaxSL) sl_p = entry + ExtMaxSL;
      sl_dist = sl_p - entry;

      double tp1 = NormalizeDouble(entry - sl_dist * InpRR_TP1, _Digits);
      double tp2 = NormalizeDouble(MathMax(entry - sl_dist * InpRR_TP2, ExtYProfile.val), _Digits);
      if(tp2 >= tp1) tp2 = NormalizeDouble(entry - sl_dist * InpRR_TP2, _Digits);

      double lot = CalculateLot(sl_dist);
      ExtTrade.Sell(lot, _Symbol, entry, sl_p, tp2, "FXDream_Sell_VP");
      Print("🚀 [MỞ LỆNH SELL] Entry: ", entry, " | SL: ", sl_p, " | TP1: ", tp1, " | TP2: ", tp2, " (Hình thái: ", ExtYProfile.shape, ")");
      return;
   }
}
//+------------------------------------------------------------------+

