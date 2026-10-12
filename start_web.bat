@echo off
chcp 65001 >nul
title TradingAgents WebUI
echo ==================================================
echo Starting TradingAgents WebUI (http://127.0.0.1:8888)...
echo ==================================================
python web_ui.py
pause
