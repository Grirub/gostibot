#!/bin/sh
# Запускает админку (gunicorn) и бота (long polling) в одном сервисе.
cd "$(dirname "$0")" || exit 1
set -a
[ -f .env ] && . ./.env
set +a
export PORT="${PORT:-8000}"

python3 manage.py migrate --noinput || exit 1
python3 manage.py collectstatic --noinput >/dev/null 2>&1

gunicorn gostibot.wsgi:application --bind "0.0.0.0:$PORT" --workers 2 --access-logfile - &
GPID=$!

if [ -n "$BOT_TOKEN" ]; then
  python3 bot.py
  STATUS=$?
else
  echo "[start] BOT_TOKEN не задан — работает только админка, бот выключен"
  wait $GPID
  STATUS=$?
fi

kill $GPID 2>/dev/null
exit $STATUS
