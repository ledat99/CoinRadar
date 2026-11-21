@echo off
chcp 65001 >nul
echo Đang thiết lập bot khởi động cùng Windows...
set TARGET_DIR=%~dp0
set VBS_PATH=%TARGET_DIR%start_bot_hidden.vbs
set STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup

copy /Y "%VBS_PATH%" "%STARTUP_DIR%\" >nul
echo.
echo ========================================================
echo ✅ THÀNH CÔNG! Bot đã được cài đặt tự chạy ngầm cùng máy tính.
echo Từ giờ mỗi khi bật máy tính lên, bot sẽ TỰ ĐỘNG CHẠY NGẦM.
echo Bạn KHÔNG CẦN mở VS Code / Antigravity hay bất kỳ cửa sổ nào,
echo chỉ cần cầm điện thoại bấm Telegram là xong!
echo ========================================================
echo.
pause

