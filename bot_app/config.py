"""Конфигурация бота."""
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")

TOKEN = (os.environ.get("BOT_TOKEN") or "").strip()
OWNER_CODE = (os.environ.get("OWNER_CODE") or "").strip()

PROXY_URL = os.environ.get("HTTPS_PROXY") or os.environ.get("http_proxy")
PROXIES = {"http": PROXY_URL, "https": PROXY_URL} if PROXY_URL else None

API_BASE = f"https://api.telegram.org/bot{TOKEN}/"
FILES_BASE = f"https://api.telegram.org/file/bot{TOKEN}/"

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gostibot.settings")
import django
django.setup()

EMPTY_KB = {"inline_keyboard": []}

ORIGIN_MAP = {
    "maternal": "Еврей по материнской линии",
    "paternal": "Еврей по отцовской линии",
    "ger": "Я гер (прошедший или в процессе)",
    "unknown": "Не знаю, что ответить",
}

GENDER_MAP = {"male": "Мужчина", "female": "Женщина"}
WEEKDAYS_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]