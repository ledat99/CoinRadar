@echo off
REM Backtest 1 coin - kiem tra ty le thang lich su
REM Cach dung: run_backtest VANRY/USDT
if "%~1"=="" (
    echo Su dung: run_backtest SYMBOL  - vi du: run_backtest VANRY/USDT
    exit /b 1
)
"C:\Users\vivas\AppData\Local\Python\bin\python.exe" "%~dp0backtest.py" %*
pause
