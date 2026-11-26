@echo off
chcp 65001
cd /d "C:\Users\Asus\Desktop\бот\gostibot"
python --version
python bot.py
echo.
echo Код завершения: %errorlevel%
pause