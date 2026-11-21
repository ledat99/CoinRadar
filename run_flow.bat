@echo off
REM Xem bang dong tien 1 coin (CoinGlass-style)
REM Cach dung: run_flow BTC/USDT    hoac    run_flow IMX/USDT
if "%~1"=="" (
    echo Su dung: run_flow SYMBOL  - vi du: run_flow BTC/USDT
    exit /b 1
)
"C:\Users\vivas\AppData\Local\Python\bin\python.exe" "%~dp0flow_filter.py" %*
pause
