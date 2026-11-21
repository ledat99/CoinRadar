@echo off
taskkill /F /IM pyw.exe /T 2>nul
taskkill /F /FI "WINDOWTITLE eq *telegram_bot*" 2>nul
echo Da tat bot chay ngam.
pause

