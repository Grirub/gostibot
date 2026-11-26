
@echo off
chcp 65001 >nul
title GostiAvram - Автозапуск
echo =====================================
echo       ЗАПУСК СИСТЕМЫ GOSTIAVRAM
echo =====================================
echo.
echo 1. Запуск Kosher VPN...
start "" "C:\Users\Asus\AppData\Local\Programs\Kosher VPN\Kosher VPN.exe"
echo.
echo 2. Ожидание подключения VPN (60 секунд)...
timeout /t 60 /nobreak >nul
echo.
echo 3. Запуск Django-админки...
start "Django Admin" cmd /k "cd /d C:\Users\Asus\Desktop\бот\gostibot && py manage.py runserver 127.0.0.1:8000"
timeout /t 5 /nobreak >nul
echo.
echo 4. Запуск Telegram-бота...
start "GostiAvram Bot" cmd /k "cd /d C:\Users\Asus\Desktop\бот\gostibot && py bot.py"
echo.
echo Все команды запуска отправлены.
pause