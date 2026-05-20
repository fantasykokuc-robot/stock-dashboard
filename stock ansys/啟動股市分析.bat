@echo off
:: 1. 切換至您的專案目錄
cd /d "C:\Users\user\Desktop\stock ansys"

:: 2. 自動嘗試安裝缺失套件 (選用)
python -m pip install streamlit pandas yfinance plotly requests

:: 3. 啟動程式
python -m streamlit run appV3.py

pause