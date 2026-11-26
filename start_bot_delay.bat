
@echo off
chcp 65001 >nul

echo Ожидание 2 минуты перед запуском бота...
timeout /t 120 /nobreak >nul

cd /d "C:\Users\Asus\Desktop\бот\gostibot"

echo Запуск Telegram-бота...
py bot.py

pause
