#!/usr/bin/env python3
"""Telegram-бот записи в гости: long polling + Django ORM."""
import html
import json
import logging
import os
import sys
import time
import uuid
from datetime import date, datetime, time as dtime, timedelta
from logging.handlers import RotatingFileHandler
import requests
from django.core.files import File

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gostibot.settings")

def load_env(path):
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

load_env(os.path.join(BASE_DIR, ".env"))

import django
django.setup()

from django.utils import timezone
from core.models import (
    MEAL_CONFIG, Booking, Family, City, District, GuestProfile, Settings, Blacklist
)

TOKEN = (os.environ.get("BOT_TOKEN") or "").strip()
OWNER_CODE = (os.environ.get("OWNER_CODE") or "").strip()
API = f"https://api.telegram.org/bot{TOKEN}/"

# === ПОДДЕРЖКА ПРОКСИ ===
PROXY_URL = os.environ.get("HTTPS_PROXY") or os.environ.get("http_proxy")
PROXIES = {"http": PROXY_URL, "https": PROXY_URL} if PROXY_URL else None
# ========================

log = logging.getLogger("gostibot")
log.setLevel(logging.INFO)
_fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
_fh = RotatingFileHandler(
    os.path.join(BASE_DIR, "bot.log"), maxBytes=2_000_000, backupCount=3, encoding="utf-8"
)
_fh.setFormatter(_fmt)
_sh = logging.StreamHandler(sys.stdout)
_sh.setFormatter(_fmt)
log.addHandler(_fh)
log.addHandler(_sh)
if PROXIES:
    log.info("Прокси: %s", PROXY_URL)

EMPTY_KB = {"inline_keyboard": []}
STATE = {}  # chat_id -> {"step": str, "data": dict}

# Словари для преобразования кодов в читаемый текст
ORIGIN_MAP = {
    "maternal": "Еврей по материнской линии",
    "paternal": "Еврей по отцовской линии",
    "ger": "Я гер (прошедший или в процессе)",
    "unknown": "Не знаю, что ответить",
}
GENDER_MAP = {
    "male": "Мужчина",
    "female": "Женщина",
}

# ============================================================================
# МУЛЬТИЯЗЫЧНОСТЬ
# ============================================================================
TRANSLATIONS = {
    "ru": {
        "select_language_first": "🌐 <b>Выберите язык / Choose language / בחר שפה</b>",
        "consent_text": "Пользуясь нашим телеграм ботом, вы соглашаетесь на обработку персональных данных.",
        "welcome_after_consent": (
            "🕊 <b>Шалом! Добро пожаловать в чат бота Гостеприимство Авраама.</b>\n\n"
            "👤 Если вы <b>гость</b> — нажмите на кнопку «Гость», заполните обязательную анкету и ожидайте подтверждения от семьи.\n\n"
            "🏡 Если вы <b>семья</b> — нажмите на кнопку «Семья» и пройдите в чат-группу для получения заявок в гости.\n\n"
            "📩 По всем вопросам обращайтесь к разработчику и администратору чата @gog98bin"
        ),
        "who_are_you": "Кто вы?",
        "guest": "👤 Я Гость",
        "family": "🏡 Я Семья",
        "consent_kashrut": "Отлично! Вы согласны принимать гостей по всем правилам кашрута?",
        "enter_family_name": "Введите название вашей семьи:",
        "yes": "✅ Да, согласен",
        "no": "❌ Нет",
        "family_registered_with_group": (
            "✅ Отлично! Семья <b>{}</b> успешно зарегистрирована!\n"
            "👉 Теперь перейдите в нашу общую группу для получения заявок от гостей:\n"
            "{}"
        ),
        "cannot_accept": "К сожалению, вы не можете принимать гостей.\nВозвращайтесь, когда будете готовы соблюдать правила кашрута.",
        "bot_not_available": "Ой вей, к сожалению наш бот не доступен для вас.",
        "blocked": "⛔ Вы заблокированы в системе. Обратитесь к администратору.",
        "send_photo": "📸 <b>Шаг 1/7:</b>\nПожалуйста, отправьте вашу фотографию.",
        "enter_name": "✍️ <b>Шаг 2/7:</b>\nКак вас зовут?",
        "send_phone": "📞 <b>Шаг 3/7:</b>\nОтправьте номер телефона.",
        "send_phone_button": "📱 Отправить мой номер",
        "select_origin": "📜 <b>Шаг 4/7:</b>\nВыберите вариант:",
        "origin_maternal": "Еврей по материнской линии",
        "origin_paternal": "Еврей по отцовской линии",
        "origin_ger": "Я гер (прошедший или в процессе)",
        "origin_unknown": "Не знаю, что ответить",
        "select_gender": "⚧️ <b>Шаг 5/7:</b>\nВыберите ваш пол:",
        "gender_male": "Мужчина",
        "gender_female": "Женщина",
        "select_city_guest": "🏙 <b>Шаг 6/7:</b>\nВыберите город, куда вы хотите прийти:",
        "select_district_guest": "🗺 <b>Шаг 7/7:</b>\nВыберите район:",
        "select_meal": "🍽 <b>Выберите трапезу:</b>",
        "only_fri": "🕯 Только вечерняя пятница",
        "only_sat": "🍲 Только дневная суббота",
        "both_meals": "🕯🍲 Обе трапезы (пятница + суббота)",
        "requests_sent": (
            "🎉 <b>Заявка отправлена в общую группу!</b>\n"
            "🏙 Город: {}\n"
            "🗺 Район: {}\n"
            "🍽 Трапеза: {}\n"
            "Ожидайте, пока одна из семей примет вас."
        ),
        "no_active_bookings": "У вас нет активных записей.",
        "your_bookings": "📋 <b>Ваши записи</b>",
        "past_bookings": "📜 <b>История записей</b>",
        "no_past_bookings": "У вас нет завершённых записей.",
        "cancel_booking": "❌ Отменить {} ({})",
        "booking_cancelled": "Вы отменили запись",
        "booking_already_cancelled": "Заявка уже отменена",
        "guest_cancelled": "❌ Гость {} отменил запись на {} ({})",
        "family_cancelled": "❌ <b>Семья отменила вашу запись</b>\n{} ({})",
        "accept_guest": "✅ Принять гостя ({})",
        "new_request": "🆕 Новая заявка",
        "accepted_by_family": "✅ <b>Принято семьёй: {}</b>",
        "successfully_booked": (
            "✅ <b>Вы успешно записаны!</b>\n"
            "Семья: {}\n"
            "Дата: {}\n"
            "Трапеза: {}\n"
            "Ждём вас!"
        ),
        "menu": "⬅️ В меню",
        "back": "⬅️ Назад",
        "book": "📅 Записаться в гости",
        "my_bookings": "📋 Мои записи",
        "past_bookings_btn": "📜 История записей",
        "edit_profile": "✏️ Редактировать анкету",
        "change_language": "🌐 Сменить язык",
        "edit_menu_title": "✏️ <b>Редактирование анкеты</b>\nЧто вы хотите изменить?",
        "edit_name": "✍️ Изменить имя",
        "edit_phone": "📞 Изменить телефон",
        "edit_photo": "📸 Изменить фото",
        "enter_new_name": "Введите новое имя:",
        "enter_new_phone": "Отправьте новый номер телефона:",
        "send_new_photo": "Отправьте новую фотографию:",
        "name_changed": "✅ Имя успешно изменено на: <b>{}</b>",
        "phone_changed": "✅ Телефон успешно изменен на: <b>{}</b>",
        "photo_changed": "✅ Фото успешно обновлено",
        "language_changed": "✅ Язык успешно изменён",
        "waiting_confirmation": "Ожидает подтверждения",
        "already_accepted": "Уже принято семьёй: {}",
        "not_registered_family": "Вы не зарегистрированы как семья.",
        "request_not_found": "Заявка не найдена",
        "no_access": "Нет доступа",
        "you_accepted": "✅ Вы приняли гостя {}!",
        "you_cancelled_family": "Вы отменили запись гостя",
        "empty_name": "Название не может быть пустым.",
        "family_exists": "Семья с таким именем уже существует.",
        "no_cities": "Пока нет городов в базе.",
        "no_districts": "В этом городе пока нет районов.",
        "send_photo_only": "Пожалуйста, отправьте именно фотографию.",
        "photo_save_failed": "Не удалось сохранить фото.",
        "short_name": "Напишите имя (хотя бы 2 буквы).",
        "phone_required": "Номер телефона обязателен.",
        "district_not_found": "Район не найден.",
        "meal_fri": "вечерняя пятница",
        "meal_sat": "дневная суббота",
        "meal_both": "вечерняя пятница + дневная суббота",
        "profile_reset": "✅ Профиль сброшен. Напишите /start для начала.",
        "group_not_configured": "⚠️ Группа для заявок не настроена. Обратитесь к администратору.",
        "already_has_both": "⚠️ У вас уже есть записи на обе трапезы (пятница и суббота).",
        "book_next_week": "📅 Записаться на следующую неделю",
        "already_has_both_next": (
            "⚠️ У вас уже есть записи на обе трапезы на эту неделю.\n"
            "Хотите записаться на следующую?"
        ),
    },
    "en": {
        "select_language_first": "🌐 <b>Choose language / Выберите язык / בחר שפה</b>",
        "consent_text": "By using our Telegram bot, you agree to the processing of personal data.",
        "welcome_after_consent": (
            "🕊 <b>Shalom! Welcome to the Avraham's Hospitality bot chat.</b>\n\n"
            "👤 If you are a <b>guest</b> — tap the «Guest» button, fill out the required questionnaire and wait for confirmation from a family.\n\n"
            "🏡 If you are a <b>family</b> — tap the «Family» button and join the chat group to receive guest requests.\n\n"
            "📩 For any questions, contact the developer and chat administrator @gog98bin"
        ),
        "who_are_you": "Who are you?",
        "guest": "👤 I am a Guest",
        "family": "🏡 I am a Family",
        "consent_kashrut": "Great! Do you agree to host guests according to all kashrut rules?",
        "enter_family_name": "Enter your family name:",
        "yes": "✅ Yes, I agree",
        "no": "❌ No",
        "family_registered_with_group": (
            "✅ Great! Family <b>{}</b> successfully registered!\n"
            "👉 Now join our common group to receive guest requests:\n"
            "{}"
        ),
        "cannot_accept": "Unfortunately, you cannot host guests.\nCome back when you are ready to follow kashrut rules.",
        "bot_not_available": "Sorry, our bot is not available for you.",
        "blocked": "⛔ You are blocked in the system.",
        "send_photo": "📸 <b>Step 1/7:</b>\nPlease send your photo.",
        "enter_name": "✍️ <b>Step 2/7:</b>\nWhat is your name?",
        "send_phone": "📞 <b>Step 3/7:</b>\nSend your phone number.",
        "send_phone_button": "📱 Share my phone number",
        "select_origin": "📜 <b>Step 4/7:</b>\nSelect an option:",
        "origin_maternal": "Jewish on maternal line",
        "origin_paternal": "Jewish on paternal line",
        "origin_ger": "I am a ger (converted or in process)",
        "origin_unknown": "I don't know what to answer",
        "select_gender": "⚧️ <b>Step 5/7:</b>\nSelect your gender:",
        "gender_male": "Male",
        "gender_female": "Female",
        "select_city_guest": "🏙 <b>Step 6/7:</b>\nSelect the city you want to visit:",
        "select_district_guest": "🗺 <b>Step 7/7:</b>\nSelect the district:",
        "select_meal": "🍽 <b>Select a meal:</b>",
        "only_fri": "🕯 Friday evening only",
        "only_sat": "🍲 Saturday day only",
        "both_meals": "🕯🍲 Both meals (Friday + Saturday)",
        "requests_sent": (
            "🎉 <b>Request sent to the common group!</b>\n"
            "🏙 City: {}\n"
            "🗺 District: {}\n"
            "🍽 Meal: {}\n"
            "Wait for a family to accept you."
        ),
        "no_active_bookings": "You have no active bookings.",
        "your_bookings": "📋 <b>Your bookings</b>",
        "past_bookings": "📜 <b>Booking history</b>",
        "no_past_bookings": "You have no completed bookings.",
        "cancel_booking": "❌ Cancel {} ({})",
        "booking_cancelled": "You cancelled the booking",
        "booking_already_cancelled": "Booking already cancelled",
        "guest_cancelled": "❌ Guest {} cancelled the booking for {} ({})",
        "family_cancelled": "❌ <b>Family cancelled your booking</b>\n{} ({})",
        "accept_guest": "✅ Accept guest ({})",
        "new_request": "🆕 New request",
        "accepted_by_family": "✅ <b>Accepted by family: {}</b>",
        "successfully_booked": (
            "✅ <b>You are successfully booked!</b>\n"
            "Family: {}\n"
            "Date: {}\n"
            "Meal: {}\n"
            "We are waiting for you!"
        ),
        "menu": "⬅️ To menu",
        "back": "⬅️ Back",
        "book": "📅 Book a visit",
        "my_bookings": "📋 My bookings",
        "past_bookings_btn": "📜 Booking history",
        "edit_profile": "✏️ Edit profile",
        "change_language": "🌐 Change language",
        "edit_menu_title": "✏️ <b>Profile editing</b>\nWhat would you like to change?",
        "edit_name": "✍️ Change name",
        "edit_phone": "📞 Change phone",
        "edit_photo": "📸 Change photo",
        "enter_new_name": "Enter new name:",
        "enter_new_phone": "Send new phone number:",
        "send_new_photo": "Send new photo:",
        "name_changed": "✅ Name successfully changed to: <b>{}</b>",
        "phone_changed": "✅ Phone successfully changed to: <b>{}</b>",
        "photo_changed": "✅ Photo successfully updated",
        "language_changed": "✅ Language changed",
        "waiting_confirmation": "Waiting for confirmation",
        "already_accepted": "Already accepted by family: {}",
        "not_registered_family": "You are not registered as a family.",
        "request_not_found": "Request not found",
        "no_access": "No access",
        "you_accepted": "✅ You accepted guest {}!",
        "you_cancelled_family": "You cancelled the guest's booking",
        "empty_name": "Name cannot be empty.",
        "family_exists": "A family with this name already exists.",
        "no_cities": "No cities in the database yet.",
        "no_districts": "No districts in this city yet.",
        "send_photo_only": "Please send exactly a photo.",
        "photo_save_failed": "Could not save photo.",
        "short_name": "Write a name (at least 2 letters).",
        "phone_required": "Phone number is required.",
        "district_not_found": "District not found.",
        "meal_fri": "Friday evening",
        "meal_sat": "Saturday day",
        "meal_both": "Friday evening + Saturday day",
        "profile_reset": "✅ Profile reset. Type /start to begin.",
        "group_not_configured": "⚠️ Notification group is not configured. Contact admin.",
        "already_has_both": "⚠️ You already have bookings for both meals (Friday and Saturday).",
        "book_next_week": "📅 Book for next week",
        "already_has_both_next": (
            "⚠️ You already have bookings for both meals this week.\n"
            "Would you like to book for next week?"
        ),
    },
    "he": {
        "select_language_first": "🌐 <b>בחר שפה / Choose language / Выберите язык</b>",
        "consent_text": "בעצם השימוש בבוט, אתה מסכים לעיבוד נתונים אישיים.",
        "welcome_after_consent": (
            "🕊 <b>שלום! ברוכים הבאים לצ'אט הבוט של הכנסת אורחים אברהם.</b>\n\n"
            "👤 אם אתה <b>אורח</b> — לחץ על כפתור «אורח», מלא את השאלון החובה והמתן לאישור ממשפחה.\n\n"
            "🏡 אם אתה <b>משפחה</b> — לחץ על כפתור «משפחה» והצטרף לקבוצת הצ'אט לקבלת בקשות אירוח.\n\n"
            "📩 לכל שאלה פנה למפתח ומנהל הצ'אט @gog98bin"
        ),
        "who_are_you": "?מי אתה",
        "guest": "👤 אני אורח",
        "family": "🏡 אני משפחה",
        "consent_kashrut": "?מצוין! האם אתה מסכים לארח אורחים לפי כל כללי הכשרות",
        "enter_family_name": ":הכנס את שם המשפחה שלך",
        "yes": "✅ כן, אני מסכים",
        "no": "❌ לא",
        "family_registered_with_group": (
            "✅ מצוין! המשפחה <b>{}</b> נרשמה בהצלחה!\n"
            "👉 עכשיו הצטרף לקבוצה המשותפת שלנו לקבלת בקשות מאורחים:\n"
            "{}"
        ),
        "cannot_accept": "לצערנו, אינך יכול לארח אורחים.\nחזור כשתהיה מוכן לשמור על כללי הכשרות.",
        "bot_not_available": "מצטערים, הבוט שלנו אינו זמין עבורך.",
        "blocked": "⛔ אתה חסום במערכת.",
        "send_photo": "📸 <b>שלב 1/7:</b>\nאנא שלח את התמונה שלך.",
        "enter_name": "✍️ <b>שלב 2/7:</b>\n?מה שמך",
        "send_phone": "📞 <b>שלב 3/7:</b>\nשלח את מספר הטלפון שלך.",
        "send_phone_button": "📱 שתף את מספר הטלפון שלי",
        "select_origin": "📜 <b>שלב 4/7:</b>\nבחר אפשרות:",
        "origin_maternal": "יהודי מצד האם",
        "origin_paternal": "יהודי מצד האב",
        "origin_ger": "אני גר (התגיירתי או בתהליך)",
        "origin_unknown": "אני לא יודע מה לענות",
        "select_gender": "⚧️ <b>שלב 5/7:</b>\nבחר את המין שלך:",
        "gender_male": "זכר",
        "gender_female": "נקבה",
        "select_city_guest": "🏙 <b>שלב 6/7:</b>\n:בחר את העיר שבה אתה רוצה לבקר",
        "select_district_guest": "🗺 <b>שלב 7/7:</b>\n:בחר את הרובע",
        "select_meal": "🍽 <b>בחר ארוחה:</b>",
        "only_fri": "🕯 ערב שישי בלבד",
        "only_sat": "🍲 יום שבת בלבד",
        "both_meals": "🕯🍲 שתי ארוחות (שישי + שבת)",
        "requests_sent": (
            "🎉 <b>הבקשה נשלחה לקבוצה המשותפת!</b>\n"
            "🏙 עיר: {}\n"
            "🗺 רובע: {}\n"
            "🍽 ארוחה: {}\n"
            "המתן עד שמשפחה תקבל אותך."
        ),
        "no_active_bookings": ".אין לך הזמנות פעילות",
        "your_bookings": "📋 <b>ההזמנות שלך</b>",
        "past_bookings": "📜 <b>היסטוריית הזמנות</b>",
        "no_past_bookings": ".אין לך הזמנות שהושלמו",
        "cancel_booking": "❌ בטל {} ({})",
        "booking_cancelled": "ביטלת את ההזמנה",
        "booking_already_cancelled": "ההזמנה כבר בוטלה",
        "guest_cancelled": "❌ האורח {} ביטל את ההזמנה ל-{} ({})",
        "family_cancelled": "❌ <b>המשפחה ביטלה את ההזמנה שלך</b>\n{} ({})",
        "accept_guest": "✅ קבל אורח ({})",
        "new_request": "🆕 בקשה חדשה",
        "accepted_by_family": "✅ <b>התקבל על ידי משפחה: {}</b>",
        "successfully_booked": (
            "✅ <b>נרשמת בהצלחה!</b>\n"
            "משפחה: {}\n"
            "תאריך: {}\n"
            "ארוחה: {}\n"
            "אנחנו מחכים לך!"
        ),
        "menu": "⬅️ לתפריט",
        "back": "⬅️ חזרה",
        "book": "📅 הזמן ביקור",
        "my_bookings": "📋 ההזמנות שלי",
        "past_bookings_btn": "📜 היסטוריית הזמנות",
        "edit_profile": "✏️ ערוך פרופיל",
        "change_language": "🌐 שנה שפה",
        "edit_menu_title": "✏️ <b>עריכת פרופיל</b>\n?מה תרצה לשנות",
        "edit_name": "✍️ שנה שם",
        "edit_phone": "📞 שנה טלפון",
        "edit_photo": "📸 שנה תמונה",
        "enter_new_name": ":הכנס שם חדש",
        "enter_new_phone": ":שלח מספר טלפון חדש",
        "send_new_photo": ":שלח תמונה חדשה",
        "name_changed": "✅ <b>{}</b> :השם שונה בהצלחה ל",
        "phone_changed": "✅ <b>{}</b> :הטלפון שונה בהצלחה ל",
        "photo_changed": "✅ התמונה עודכנה בהצלחה",
        "language_changed": "✅ השפה שונתה",
        "waiting_confirmation": "ממתין לאישור",
        "already_accepted": "{} :כבר התקבל על ידי משפחה",
        "not_registered_family": "אינך רשום כמשפחה.",
        "request_not_found": "הבקשה לא נמצאה",
        "no_access": "אין גישה",
        "you_accepted": "!{} קיבלת את האורח ✅",
        "you_cancelled_family": "ביטלת את הזמנת האורח",
        "empty_name": ":השם לא יכול להיות ריק",
        "family_exists": "משפחה עם שם זה כבר קיימת.",
        "no_cities": "אין ערים במאגר הנתונים עדיין.",
        "no_districts": "אין רבעים בעיר זו עדיין.",
        "send_photo_only": "אנא שלח בדיוק תמונה.",
        "photo_save_failed": "לא ניתן לשמור את התמונה.",
        "short_name": ".כתוב שם (לפחות 2 אותיות)",
        "phone_required": "מספר טלפון נדרש.",
        "district_not_found": "הרובע לא נמצא.",
        "meal_fri": "ערב שישי",
        "meal_sat": "יום שבת",
        "meal_both": "ערב שישי + יום שבת",
        "profile_reset": ".✅ הפרופיל אופס. הקלד /start להתחלה",
        "group_not_configured": "⚠️ קבוצת ההתראות לא מוגדרת. פנה למנהל.",
        "already_has_both": "⚠️ כבר יש לך הזמנות לשתי הארוחות (שישי ושבת).",
        "book_next_week": "📅 הזמן לשבוע הבא",
        "already_has_both_next": (
            "⚠️ כבר יש לך הזמנות לשתי הארוחות השבוע.\n"
            "?תרצה להזמין לשבוע הבא"
        ),
    },
}

def get_lang(chat_id):
    try:
        profile = GuestProfile.objects.filter(tg_id=chat_id).first()
        return profile.language if profile and profile.language else "ru"
    except Exception:
        return "ru"

def t(chat_id, key, *args):
    lang = get_lang(chat_id)
    text = TRANSLATIONS.get(lang, TRANSLATIONS["ru"]).get(key, key)
    if args:
        try:
            return text.format(*args)
        except (IndexError, KeyError):
            return text
    return text

def t_lang(lang, key, *args):
    """Перевод на конкретном языке (не зависит от chat_id)."""
    text = TRANSLATIONS.get(lang, TRANSLATIONS["ru"]).get(key, key)
    if args:
        try:
            return text.format(*args)
        except (IndexError, KeyError):
            return text
    return text

# ============================================================================
# ЧЁРНЫЙ СПИСОК
# ============================================================================
def is_blocked(chat_id):
    try:
        return Blacklist.is_blocked(chat_id)
    except Exception:
        return False

# ---------------------------------------------------------------- API helpers
def api(method, **params):
    try:
        r = requests.post(API + method, json=params, timeout=60, proxies=PROXIES)
        return r.json()
    except Exception as exc:
        log.warning("API %s: %s", method, exc)
        return {"ok": False}

def send(chat_id, text, kb=None):
    params = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    if kb is not None:
        params["reply_markup"] = kb
    return api("sendMessage", **params)

def send_photo_msg(chat_id, photo_path, caption, kb=None):
    params = {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"}
    if kb is not None:
        params["reply_markup"] = json.dumps(kb)
    try:
        with open(photo_path, "rb") as f:
            r = requests.post(API + "sendPhoto", data=params, files={"photo": f}, timeout=60, proxies=PROXIES)
            res = r.json()
            if not res.get("ok"):
                log.warning("API sendPhoto error: %s", res.get("description"))
            return res
    except Exception as exc:
        log.warning("API sendPhoto exception: %s", exc)
        return {"ok": False, "description": str(exc)}

def edit_msg(chat_id, message_id, text, kb=None):
    params = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    if kb is not None:
        params["reply_markup"] = kb
    res = api("editMessageText", **params)
    if not res.get("ok") and "not modified" not in str(res.get("description", "")):
        send(chat_id, text, kb)
    return res

def answer_cb(cb_id, text=None):
    params = {"callback_query_id": cb_id}
    if text:
        params["text"] = text
    params["show_alert"] = False
    api("answerCallbackQuery", **params)

def esc(value):
    return html.escape(str(value or ""), quote=False)

def get_state(chat_id):
    return STATE.get(chat_id)

def set_state(chat_id, step, data=None):
    STATE[chat_id] = {"step": step, "data": data or {}}

def clear_state(chat_id):
    STATE.pop(chat_id, None)

def is_private(message):
    return (message.get("chat") or {}).get("type") == "private"

# ---------------------------------------------------------------- keyboards
def kb_languages():
    return {
        "inline_keyboard": [
            [{"text": "🇷🇺 Русский", "callback_data": "setlang:ru"}],
            [{"text": "🇬🇧 English", "callback_data": "setlang:en"}],
            [{"text": "🇮🇱 עברית", "callback_data": "setlang:he"}],
        ]
    }

def kb_consent(chat_id):
    return {"inline_keyboard": [[
        {"text": t(chat_id, "yes"), "callback_data": "consent:yes"},
        {"text": t(chat_id, "no"), "callback_data": "consent:no"}
    ]]}

def kb_role(chat_id):
    return {"inline_keyboard": [
        [{"text": t(chat_id, "guest"), "callback_data": "role:guest"},
         {"text": t(chat_id, "family"), "callback_data": "role:family"}]
    ]}

def kb_jewish_origin(chat_id):
    """Ровно 4 варианта, по одному в строке — выбор только одного."""
    return {"inline_keyboard": [
        [{"text": t(chat_id, "origin_maternal"), "callback_data": "jo:maternal"}],
        [{"text": t(chat_id, "origin_paternal"), "callback_data": "jo:paternal"}],
        [{"text": t(chat_id, "origin_ger"), "callback_data": "jo:ger"}],
        [{"text": t(chat_id, "origin_unknown"), "callback_data": "jo:unknown"}],
    ]}

def kb_gender(chat_id):
    return {"inline_keyboard": [
        [{"text": t(chat_id, "gender_male"), "callback_data": "gen:male"},
         {"text": t(chat_id, "gender_female"), "callback_data": "gen:female"}]
    ]}

def kb_meal_choice(chat_id):
    return {"inline_keyboard": [
        [{"text": t(chat_id, "only_fri"), "callback_data": "meal:fri_evening"}],
        [{"text": t(chat_id, "only_sat"), "callback_data": "meal:sat_day"}],
        [{"text": t(chat_id, "both_meals"), "callback_data": "meal:both"}]
    ]}

def kb_main_menu(chat_id):
    """Главное меню. Кнопка 'Записаться' ВСЕГДА активна."""
    return {"inline_keyboard": [
        [{"text": t(chat_id, "book"), "callback_data": "book"}],
        [{"text": t(chat_id, "my_bookings"), "callback_data": "my"}],
        [{"text": t(chat_id, "past_bookings_btn"), "callback_data": "past"}],
        [{"text": t(chat_id, "edit_profile"), "callback_data": "edit"}],
        [{"text": t(chat_id, "change_language"), "callback_data": "lang"}],
    ]}

def kb_edit_profile(chat_id):
    return {"inline_keyboard": [
        [{"text": t(chat_id, "edit_name"), "callback_data": "edit:name"}],
        [{"text": t(chat_id, "edit_phone"), "callback_data": "edit:phone"}],
        [{"text": t(chat_id, "edit_photo"), "callback_data": "edit:photo"}],
        [{"text": t(chat_id, "back"), "callback_data": "menu"}]
    ]}

def kb_cities(chat_id):
    """Клавиатура выбора города.
    'Назад' ведёт к выбору трапезы только если это режим дозаписи (redo=True),
    иначе — в главное меню."""
    lang = get_lang(chat_id)
    cities = City.objects.filter(districts__isnull=False).distinct().order_by("order", "name")
    rows = [[{"text": c.get_name(lang), "callback_data": f"city:{c.pk}"}] for c in cities]
    st = get_state(chat_id)
    if st and st["data"].get("redo"):
        rows.append([{"text": t(chat_id, "back"), "callback_data": "back_to_meal"}])
    else:
        rows.append([{"text": t(chat_id, "menu"), "callback_data": "menu"}])
    return {"inline_keyboard": rows}

def kb_districts(chat_id, city_id):
    """Клавиатура выбора района. 'Назад' — к списку городов."""
    lang = get_lang(chat_id)
    districts = District.objects.filter(city_id=city_id).order_by("order", "name")
    rows = [[{"text": d.get_name(lang), "callback_data": f"dist:{d.pk}"}] for d in districts]
    rows.append([{"text": t(chat_id, "back"), "callback_data": "cities"}])
    return {"inline_keyboard": rows}

def kb_phone(chat_id):
    return {"keyboard": [[{"text": t(chat_id, "send_phone_button"), "request_contact": True}]], "resize_keyboard": True, "one_time_keyboard": True}

# ---------------------------------------------------------------- helpers
def get_next_weekday(weekday_num):
    today = timezone.localdate()
    days_ahead = weekday_num - today.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    return today + timedelta(days=days_ahead)

def send_to_notification_group(text, photo_path=None, kb=None):
    """Отправка заявки в общую группу. Если фото не ушло — отправляется текст."""
    try:
        s = Settings.load()
        group_id = s.notification_group_id
        if not group_id:
            log.warning("notification_group_id не задан — заявка не отправлена")
            return False

        sent = False
        if photo_path and os.path.exists(photo_path):
            res = send_photo_msg(group_id, photo_path, text, kb)
            if res.get("ok"):
                sent = True
            else:
                log.warning("Фото не ушло (%s). Пробуем отправить только текст.", res.get("description"))

        if not sent:
            res_text = send(group_id, text, kb)
            if not res_text.get("ok"):
                log.error("Текст тоже не ушёл: %s", res_text.get("description"))
                return False
        return True
    except Exception as exc:
        log.error("send_to_notification_group: %s", exc)
        return False

# ---------------------------------------------------------------- main flow
def show_menu(chat_id, message_id=None):
    s = Settings.load()
    text = f"<b>{esc(s.title)}</b>\n{esc(s.greeting)}"
    if s.address:
        text += f"\n📍 {esc(s.address)}"
    if s.contact:
        text += f"\n☎️ {esc(s.contact)}"
    if message_id:
        edit_msg(chat_id, message_id, text, kb_main_menu(chat_id))
    else:
        send(chat_id, text, kb_main_menu(chat_id))

def start_flow(chat_id, message_id=None):
    if is_blocked(chat_id):
        send(chat_id, t(chat_id, "blocked"))
        return
    GuestProfile.objects.get_or_create(tg_id=chat_id)
    set_state(chat_id, "select_language")
    send(chat_id, t(chat_id, "select_language_first"), kb_languages())

def handle_set_language(chat_id, lang):
    if lang not in TRANSLATIONS:
        return
    profile, _ = GuestProfile.objects.get_or_create(tg_id=chat_id)
    profile.language = lang
    profile.save()
    if not profile.consented_at:
        set_state(chat_id, "consent")
        send(chat_id, t(chat_id, "consent_text"), kb_consent(chat_id))
    else:
        clear_state(chat_id)
        show_menu(chat_id)

def handle_consent(chat_id, answer):
    if answer == "no":
        clear_state(chat_id)
        send(chat_id, t(chat_id, "bot_not_available"))
    else:
        profile = GuestProfile.objects.get(tg_id=chat_id)
        profile.consented_at = timezone.now()
        profile.save()
        send(chat_id, t(chat_id, "welcome_after_consent"))
        set_state(chat_id, "role")
        send(chat_id, t(chat_id, "who_are_you"), kb_role(chat_id))

# ============================================================================
# СЕМЬЯ
# ============================================================================
def handle_role(chat_id, role):
    st = get_state(chat_id) or {"data": {}}
    st["data"]["role"] = role
    STATE[chat_id] = st
    if role == "family":
        set_state(chat_id, "family_consent", st["data"])
        send(chat_id, t(chat_id, "consent_kashrut"), kb_consent(chat_id))
    else:
        set_state(chat_id, "guest_photo", st["data"])
        send(chat_id, t(chat_id, "send_photo"))

def handle_family_consent(chat_id, answer):
    st = get_state(chat_id)
    if not st:
        return
    if answer == "no":
        clear_state(chat_id)
        send(chat_id, t(chat_id, "cannot_accept"))
    else:
        set_state(chat_id, "family_name", st["data"])
        send(chat_id, t(chat_id, "enter_family_name"))

def handle_family_reg(chat_id, text):
    name = text.strip()[:100]
    if not name:
        send(chat_id, t(chat_id, "empty_name"))
        return
    if Family.objects.filter(name__iexact=name).exists():
        send(chat_id, t(chat_id, "family_exists"))
        return
    Family.objects.create(
        name=name,
        is_active=True,
        telegram_chat_id=chat_id,
        consented_at=timezone.now(),
    )
    clear_state(chat_id)
    s = Settings.load()
    group_link = s.notification_group_link or ""
    if group_link:
        send(chat_id, t(chat_id, "family_registered_with_group", esc(name), esc(group_link)))
    else:
        send(chat_id, t(chat_id, "family_registered_with_group", esc(name), "(ссылка не настроена)"))

# ============================================================================
# ГОСТЬ: 7 шагов
# ============================================================================
def handle_guest_photo(chat_id, message):
    if not message.get("photo"):
        send(chat_id, t(chat_id, "send_photo_only"))
        return
    photo = message["photo"][-1]
    file_info = api("getFile", file_id=photo["file_id"])
    if file_info.get("ok"):
        file_path = file_info["result"]["file_path"]
        try:
            r = requests.get(f"https://api.telegram.org/file/bot{TOKEN}/{file_path}", timeout=60, proxies=PROXIES)
        except Exception as exc:
            log.warning("download: %s", exc)
            send(chat_id, t(chat_id, "photo_save_failed"))
            return
        if r.status_code == 200:
            ext = file_path.split(".")[-1] if "." in file_path else "jpg"
            temp_path = os.path.join(BASE_DIR, f"temp_{uuid.uuid4()}.{ext}")
            with open(temp_path, "wb") as f:
                f.write(r.content)
            st = get_state(chat_id) or {"data": {}}
            st["data"]["photo_path"] = temp_path
            STATE[chat_id] = st
            set_state(chat_id, "guest_name", st["data"])
            send(chat_id, t(chat_id, "enter_name"))
            return
    send(chat_id, t(chat_id, "photo_save_failed"))

def handle_guest_name(chat_id, text):
    name = " ".join(text.split())[:100]
    if len(name) < 2:
        send(chat_id, t(chat_id, "short_name"))
        return
    st = get_state(chat_id) or {"data": {}}
    st["data"]["name"] = name
    STATE[chat_id] = st
    set_state(chat_id, "guest_phone", st["data"])
    send(chat_id, t(chat_id, "send_phone"), kb_phone(chat_id))

def handle_guest_phone(chat_id, message):
    phone = message.get("contact", {}).get("phone_number") or message.get("text", "")[:40]
    if not phone:
        send(chat_id, t(chat_id, "phone_required"))
        return
    st = get_state(chat_id) or {"data": {}}
    st["data"]["phone"] = phone
    STATE[chat_id] = st
    set_state(chat_id, "guest_origin", st["data"])
    send(chat_id, t(chat_id, "select_origin"), kb_jewish_origin(chat_id))

def handle_guest_origin(chat_id, data):
    """Выбор ТОЛЬКО одного варианта из 4. Если шаг уже не guest_origin — игнорируем."""
    st = get_state(chat_id)
    if not st or st["step"] != "guest_origin":
        log.info("ORIGIN ignored: step=%s", st and st["step"])
        return
    value = data.split(":")[1]
    if value not in ORIGIN_MAP:
        return
    st["data"]["jewish_origin"] = value
    STATE[chat_id] = st
    set_state(chat_id, "guest_gender", st["data"])
    send(chat_id, t(chat_id, "select_gender"), kb_gender(chat_id))

def handle_guest_gender(chat_id, data):
    st = get_state(chat_id)
    if not st or st["step"] != "guest_gender":
        log.info("GENDER ignored: step=%s", st and st["step"])
        return
    st["data"]["gender"] = data.split(":")[1]
    STATE[chat_id] = st
    profile = GuestProfile.objects.get(tg_id=chat_id)
    profile.name = st["data"]["name"]
    profile.phone = st["data"]["phone"]
    profile.jewish_origin = st["data"]["jewish_origin"]
    profile.gender = st["data"]["gender"]
    if st["data"].get("photo_path") and os.path.exists(st["data"]["photo_path"]):
        with open(st["data"]["photo_path"], "rb") as f:
            profile.photo.save(f"guest_{chat_id}.jpg", File(f), save=True)
        try:
            os.remove(st["data"]["photo_path"])
        except OSError:
            pass
    profile.save()
    cities = City.objects.filter(districts__isnull=False).distinct().order_by("order", "name")
    if not cities:
        send(chat_id, t(chat_id, "no_cities"))
        clear_state(chat_id)
        return
    # Первичная анкета — redo не ставим
    set_state(chat_id, "select_city", st["data"])
    send(chat_id, t(chat_id, "select_city_guest"), kb_cities(chat_id))

def handle_select_city(chat_id, city_id):
    st = get_state(chat_id)
    if not st:
        return
    st["data"]["city_id"] = city_id
    STATE[chat_id] = st
    districts = District.objects.filter(city_id=city_id).order_by("order", "name")
    if not districts:
        send(chat_id, t(chat_id, "no_districts"))
        return
    set_state(chat_id, "select_district", st["data"])
    send(chat_id, t(chat_id, "select_district_guest"), kb_districts(chat_id, city_id))

def handle_select_district(chat_id, district_id):
    st = get_state(chat_id)
    if not st:
        return
    st["data"]["district_id"] = district_id
    STATE[chat_id] = st
    set_state(chat_id, "select_meal", st["data"])
    send(chat_id, t(chat_id, "select_meal"), kb_meal_choice(chat_id))

def handle_meal_choice(chat_id, meal_mode):
    st = get_state(chat_id)
    if not st or st["step"] != "select_meal":
        log.info("MEAL ignored: step=%s", st and st["step"])
        return
    st["data"]["meal_mode"] = meal_mode
    STATE[chat_id] = st
    create_bookings_and_notify(chat_id, st["data"])

def create_bookings_and_notify(chat_id, data):
    """Создаёт заявки. Поддерживает next_week=True — запись на следующую неделю."""
    profile = GuestProfile.objects.get(tg_id=chat_id)
    try:
        district = District.objects.get(pk=data["district_id"])
        city = district.city
    except District.DoesNotExist:
        send(chat_id, t(chat_id, "district_not_found"))
        clear_state(chat_id)
        return

    meal_mode = data.get("meal_mode", "both")
    next_week = bool(data.get("next_week"))

    if next_week:
        has_fri = False
        has_sat = False
    else:
        active = list(Booking.objects.filter(
            tg_id=chat_id, status__in=["pending", "confirmed"]
        ).values_list("meal", flat=True))
        has_fri = "fri_evening" in active
        has_sat = "sat_day" in active

    shift = timedelta(days=7) if next_week else timedelta(0)
    bookings_created = []
    if meal_mode in ("fri_evening", "both") and not has_fri:
        bookings_created.append(Booking.objects.create(
            date=get_next_weekday(4) + shift, meal="fri_evening", time=dtime(18, 0),
            name=profile.name, phone=profile.phone, guests=1,
            tg_id=chat_id, tg_username=profile.tg_username, photo=profile.photo,
            jewish_origin=profile.jewish_origin, gender=profile.gender,
            city=city, district=district, status="pending"
        ))
    if meal_mode in ("sat_day", "both") and not has_sat:
        bookings_created.append(Booking.objects.create(
            date=get_next_weekday(5) + shift, meal="sat_day", time=dtime(13, 0),
            name=profile.name, phone=profile.phone, guests=1,
            tg_id=chat_id, tg_username=profile.tg_username, photo=profile.photo,
            jewish_origin=profile.jewish_origin, gender=profile.gender,
            city=city, district=district, status="pending"
        ))

    if not bookings_created:
        send(chat_id, t(chat_id, "already_has_both"))
        clear_state(chat_id)
        return

    clear_state(chat_id)
    lang = get_lang(chat_id)
    meal_text = {
        "fri_evening": t(chat_id, "meal_fri"),
        "sat_day": t(chat_id, "meal_sat"),
        "both": t(chat_id, "meal_both"),
    }.get(meal_mode, meal_mode)

    send(chat_id, t(chat_id, "requests_sent",
                    esc(city.get_name(lang)), esc(district.get_name(lang)), meal_text))

    origin_text = ORIGIN_MAP.get(profile.jewish_origin, "")
    gender_text = GENDER_MAP.get(profile.gender, "")

    photo_path = profile.photo.path if profile.photo else None
    for b in bookings_created:
        kb = {"inline_keyboard": [[
            {"text": f"✅ {t(chat_id, 'accept_guest', b.meal_label)}", "callback_data": f"claim:{b.pk}"}
        ]]}
        text = (
            f"🆕 <b>{t(chat_id, 'new_request')}</b>\n"
            f"🏙 {esc(city.get_name(lang))} | 🗺 {esc(district.get_name(lang))}\n"
            f"🍽 {b.meal_label}\n"
            f"👤 {esc(profile.name)}\n"
            f"📞 {esc(profile.phone)}\n"
            f"📜 {origin_text} | ⚧️ {gender_text}\n"
            f"🆔 <code>{chat_id}</code>"
        )
        send_to_notification_group(text, photo_path, kb)

# ============================================================================
# РЕДАКТИРОВАНИЕ АНКЕТЫ
# ============================================================================
def show_edit_menu(chat_id, message_id=None):
    if message_id:
        edit_msg(chat_id, message_id, t(chat_id, "edit_menu_title"), kb_edit_profile(chat_id))
    else:
        send(chat_id, t(chat_id, "edit_menu_title"), kb_edit_profile(chat_id))

def handle_edit_name_start(chat_id, message_id=None):
    set_state(chat_id, "edit_name_input")
    kb = {"inline_keyboard": [[{"text": t(chat_id, "back"), "callback_data": "edit"}]]}
    if message_id:
        edit_msg(chat_id, message_id, t(chat_id, "enter_new_name"), kb)
    else:
        send(chat_id, t(chat_id, "enter_new_name"), kb)

def handle_edit_phone_start(chat_id, message_id=None):
    set_state(chat_id, "edit_phone_input")
    kb = {"inline_keyboard": [[{"text": t(chat_id, "back"), "callback_data": "edit"}]]}
    if message_id:
        edit_msg(chat_id, message_id, t(chat_id, "enter_new_phone"), kb)
    else:
        send(chat_id, t(chat_id, "enter_new_phone"), kb)

def handle_edit_photo_start(chat_id, message_id=None):
    set_state(chat_id, "edit_photo_input")
    kb = {"inline_keyboard": [[{"text": t(chat_id, "back"), "callback_data": "edit"}]]}
    if message_id:
        edit_msg(chat_id, message_id, t(chat_id, "send_new_photo"), kb)
    else:
        send(chat_id, t(chat_id, "send_new_photo"), kb)

def handle_edit_name_input(chat_id, text):
    name = " ".join(text.split())[:100]
    if len(name) < 2:
        send(chat_id, t(chat_id, "short_name"))
        return
    profile = GuestProfile.objects.get(tg_id=chat_id)
    profile.name = name
    profile.save()
    Booking.objects.filter(tg_id=chat_id, status__in=["pending", "confirmed"]).update(name=name)
    clear_state(chat_id)
    send(chat_id, t(chat_id, "name_changed", name), kb_edit_profile(chat_id))

def handle_edit_phone_input(chat_id, message):
    phone = message.get("contact", {}).get("phone_number") or message.get("text", "")[:40]
    if not phone:
        send(chat_id, t(chat_id, "phone_required"))
        return
    profile = GuestProfile.objects.get(tg_id=chat_id)
    profile.phone = phone
    profile.save()
    Booking.objects.filter(tg_id=chat_id, status__in=["pending", "confirmed"]).update(phone=phone)
    clear_state(chat_id)
    send(chat_id, t(chat_id, "phone_changed", phone), kb_edit_profile(chat_id))

def handle_edit_photo_input(chat_id, message):
    if not message.get("photo"):
        send(chat_id, t(chat_id, "send_photo_only"))
        return
    photo = message["photo"][-1]
    file_info = api("getFile", file_id=photo["file_id"])
    if file_info.get("ok"):
        file_path = file_info["result"]["file_path"]
        try:
            r = requests.get(f"https://api.telegram.org/file/bot{TOKEN}/{file_path}", timeout=60, proxies=PROXIES)
        except Exception as exc:
            log.warning("download: %s", exc)
            send(chat_id, t(chat_id, "photo_save_failed"))
            return
        if r.status_code == 200:
            ext = file_path.split(".")[-1] if "." in file_path else "jpg"
            temp_path = os.path.join(BASE_DIR, f"temp_{uuid.uuid4()}.{ext}")
            with open(temp_path, "wb") as f:
                f.write(r.content)
            profile = GuestProfile.objects.get(tg_id=chat_id)
            if profile.photo:
                try:
                    profile.photo.delete(save=False)
                except Exception:
                    pass
            with open(temp_path, "rb") as f:
                profile.photo.save(f"guest_{chat_id}.jpg", File(f), save=True)
            try:
                os.remove(temp_path)
            except OSError:
                pass
            Booking.objects.filter(tg_id=chat_id, status__in=["pending", "confirmed"]).update(photo=profile.photo)
            clear_state(chat_id)
            send(chat_id, t(chat_id, "photo_changed"), kb_edit_profile(chat_id))
            return
    send(chat_id, t(chat_id, "photo_save_failed"))

# ---------------------------------------------------------------- update routing
def handle_message(message):
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    if not chat_id or not is_private(message):
        return
    if is_blocked(chat_id):
        send(chat_id, t(chat_id, "blocked"))
        return
    text = (message.get("text") or "").strip()
    if text == "/reset":
        clear_state(chat_id)
        profile = GuestProfile.objects.filter(tg_id=chat_id).first()
        if profile:
            profile.language = ""
            profile.consented_at = None
            profile.save()
        send(chat_id, t(chat_id, "profile_reset"), kb_languages())
        return
    if text.startswith("/start"):
        clear_state(chat_id)
        start_flow(chat_id)
        return
    if text == "/id":
        send(chat_id, f"Ваш Telegram ID: <code>{chat_id}</code>")
        return
    if text == "/lang":
        send(chat_id, t(chat_id, "select_language_first"), kb_languages())
        return
    st = get_state(chat_id)
    if not st:
        return
    step = st["step"]
    if step == "family_name":
        handle_family_reg(chat_id, text)
    elif step == "guest_photo":
        handle_guest_photo(chat_id, message)
    elif step == "guest_name":
        handle_guest_name(chat_id, text)
    elif step == "guest_phone":
        handle_guest_phone(chat_id, message)
    elif step == "edit_name_input":
        handle_edit_name_input(chat_id, text)
    elif step == "edit_phone_input":
        handle_edit_phone_input(chat_id, message)
    elif step == "edit_photo_input":
        handle_edit_photo_input(chat_id, message)

def handle_callback(cb):
    data = cb.get("data") or ""
    msg = cb.get("message") or {}
    chat_id = (msg.get("chat") or {}).get("id")
    message_id = msg.get("id")
    cb_id = cb.get("id")
    user_id = (cb.get("from") or {}).get("id")
    if not chat_id:
        return
    log.info("CB data=%s chat=%s user=%s", data, chat_id, user_id)
    if is_blocked(chat_id) and not data.startswith("menu"):
        answer_cb(cb_id, t(chat_id, "blocked"))
        send(chat_id, t(chat_id, "blocked"))
        return
    try:
        if data == "menu":
            clear_state(chat_id)
            answer_cb(cb_id)
            show_menu(chat_id, message_id)
            return
        if data == "edit":
            answer_cb(cb_id)
            show_edit_menu(chat_id, message_id)
            return
        if data == "edit:name":
            answer_cb(cb_id)
            handle_edit_name_start(chat_id, message_id)
            return
        if data == "edit:phone":
            answer_cb(cb_id)
            handle_edit_phone_start(chat_id, message_id)
            return
        if data == "edit:photo":
            answer_cb(cb_id)
            handle_edit_photo_start(chat_id, message_id)
            return
        if data == "lang":
            answer_cb(cb_id)
            send(chat_id, t(chat_id, "select_language_first"), kb_languages())
            return
        if data.startswith("setlang:"):
            answer_cb(cb_id)
            handle_set_language(chat_id, data.split(":")[1])
            return
        if data == "past":
            answer_cb(cb_id)
            qs = Booking.objects.filter(tg_id=chat_id).filter(
                status__in=["confirmed", "cancelled", "declined"]).order_by("-date")[:10]
            if not qs:
                send(chat_id, t(chat_id, "no_past_bookings"),
                     {"inline_keyboard": [[{"text": t(chat_id, "menu"), "callback_data": "menu"}]]})
            else:
                parts = [t(chat_id, "past_bookings")]
                status_map = {"confirmed": "✅", "cancelled": "❌", "declined": "🚫"}
                for b in qs:
                    who = b.assigned_family.name if b.assigned_family else "—"
                    parts.append(f"• {status_map.get(b.status, '')} {b.date:%d.%m} ({b.meal_label}) — {esc(who)}")
                send(chat_id, "\n".join(parts),
                     {"inline_keyboard": [[{"text": t(chat_id, "menu"), "callback_data": "menu"}]]})
            return
        if data == "my":
            answer_cb(cb_id)
            qs = Booking.objects.filter(tg_id=chat_id).exclude(
                status__in=["declined", "cancelled"]).order_by("date")[:5]
            if not qs:
                send(chat_id, t(chat_id, "no_active_bookings"),
                     {"inline_keyboard": [[{"text": t(chat_id, "menu"), "callback_data": "menu"}]]})
            else:
                parts = [t(chat_id, "your_bookings")]
                kb_rows = []
                for b in qs:
                    who = b.assigned_family.name if b.assigned_family else t(chat_id, "waiting_confirmation")
                    parts.append(f"• {b.date:%d.%m} ({b.meal_label}) — {esc(who)}")
                    if b.status in ["pending", "confirmed"]:
                        kb_rows.append([{
                            "text": t(chat_id, "cancel_booking", b.date.strftime("%d.%m"), b.meal_label),
                            "callback_data": f"cancel_guest:{b.pk}"
                        }])
                kb_rows.append([{"text": t(chat_id, "menu"), "callback_data": "menu"}])
                send(chat_id, "\n".join(parts), {"inline_keyboard": kb_rows})
            return

        # === УМНАЯ КНОПКА "ЗАПИСАТЬСЯ" ===
        if data == "book":
            answer_cb(cb_id)
            profile = GuestProfile.objects.filter(tg_id=chat_id).first()
            if not profile or not profile.name or not profile.phone or not profile.jewish_origin or not profile.gender:
                start_flow(chat_id, message_id)
                return
            active = list(Booking.objects.filter(
                tg_id=chat_id, status__in=["pending", "confirmed"]
            ).values_list("meal", flat=True))
            has_fri = "fri_evening" in active
            has_sat = "sat_day" in active
            if has_fri and has_sat:
                kb = {"inline_keyboard": [
                    [{"text": t(chat_id, "book_next_week"), "callback_data": "book_next_week"}],
                    [{"text": t(chat_id, "menu"), "callback_data": "menu"}],
                ]}
                send(chat_id, t(chat_id, "already_has_both_next"), kb)
                return
            set_state(chat_id, "select_meal", {"name": profile.name, "phone": profile.phone, "redo": True})
            send(chat_id, t(chat_id, "select_meal"), kb_meal_choice(chat_id))
            return

        if data == "book_next_week":
            answer_cb(cb_id)
            profile = GuestProfile.objects.filter(tg_id=chat_id).first()
            if not profile or not profile.name:
                start_flow(chat_id, message_id)
                return
            active = list(Booking.objects.filter(
                tg_id=chat_id, status__in=["pending", "confirmed"]
            ).values_list("meal", flat=True))
            has_fri = "fri_evening" in active
            has_sat = "sat_day" in active
            if has_fri and has_sat:
                meal_mode = "both"
            elif has_fri:
                meal_mode = "fri_evening"
            else:
                meal_mode = "sat_day"
            set_state(chat_id, "select_city", {
                "name": profile.name, "phone": profile.phone,
                "meal_mode": meal_mode, "next_week": True, "redo": True
            })
            send(chat_id, t(chat_id, "select_city_guest"), kb_cities(chat_id))
            return

        if data == "back_to_meal":
            answer_cb(cb_id)
            st = get_state(chat_id)
            if st:
                set_state(chat_id, "select_meal", st["data"])
                send(chat_id, t(chat_id, "select_meal"), kb_meal_choice(chat_id))
            return

        if data == "cities":
            answer_cb(cb_id)
            st = get_state(chat_id)
            if st:
                set_state(chat_id, "select_city", st["data"])
                send(chat_id, t(chat_id, "select_city_guest"), kb_cities(chat_id))
            return

        if data.startswith("consent:"):
            answer_cb(cb_id)
            st = get_state(chat_id)
            if st and st["step"] == "family_consent":
                handle_family_consent(chat_id, data.split(":")[1])
            else:
                handle_consent(chat_id, data.split(":")[1])
            return
        if data.startswith("role:"):
            answer_cb(cb_id)
            handle_role(chat_id, data.split(":")[1])
            return
        if data.startswith("jo:"):
            answer_cb(cb_id)
            handle_guest_origin(chat_id, data)
            return
        if data.startswith("gen:"):
            answer_cb(cb_id)
            handle_guest_gender(chat_id, data)
            return
        if data.startswith("city:"):
            answer_cb(cb_id)
            handle_select_city(chat_id, int(data.split(":")[1]))
            return
        if data.startswith("dist:"):
            answer_cb(cb_id)
            handle_select_district(chat_id, int(data.split(":")[1]))
            return
        if data.startswith("meal:"):
            answer_cb(cb_id)
            handle_meal_choice(chat_id, data.split(":")[1])
            return

        # === ПРИНЯТЬ ГОСТЯ (из общей группы) ===
        if data.startswith("claim:"):
            bid = int(data.split(":")[1])
            booking = Booking.objects.filter(pk=bid).first()
            if not booking:
                answer_cb(cb_id, t(chat_id, "request_not_found"))
                return
            if booking.assigned_family:
                answer_cb(cb_id, t(chat_id, "already_accepted", booking.assigned_family.name))
                return
            pressing_family = Family.objects.filter(telegram_chat_id=user_id).first() if user_id else None
            if not pressing_family:
                answer_cb(cb_id, t(chat_id, "not_registered_family"))
                return
            booking.assigned_family = pressing_family
            booking.status = "confirmed"
            booking.decided_at = timezone.now()
            booking.save(update_fields=["assigned_family", "status", "decided_at"])
            answer_cb(cb_id, t(chat_id, "you_accepted", booking.name))
            kb = {"inline_keyboard": [[{"text": "❌ Отменить запись", "callback_data": f"cancel_family:{booking.pk}"}]]}
            new_text = (msg.get("text") or "") + "\n" + t(chat_id, "accepted_by_family", pressing_family.name)
            edit_msg(chat_id, message_id, new_text, kb)
            if booking.tg_id:
                gl = get_lang(booking.tg_id)
                ml = t_lang(gl, "meal_fri") if booking.meal == "fri_evening" else t_lang(gl, "meal_sat")
                send(
                    booking.tg_id,
                    t_lang(gl, "successfully_booked", pressing_family.name,
                           booking.date.strftime("%d.%m.%Y"), ml),
                    {"inline_keyboard": [[{"text": t_lang(gl, "my_bookings"), "callback_data": "my"}]]}
                )
            return

        if data.startswith("cancel_guest:"):
            bid = int(data.split(":")[1])
            booking = Booking.objects.filter(pk=bid, tg_id=chat_id).first()
            if not booking or booking.status in ["cancelled", "declined"]:
                answer_cb(cb_id, t(chat_id, "booking_already_cancelled"))
                return
            old_status = booking.status
            booking.status = "cancelled"
            booking.decided_at = timezone.now()
            booking.save(update_fields=["status", "decided_at"])
            answer_cb(cb_id, t(chat_id, "booking_cancelled"))
            if old_status == "confirmed" and booking.assigned_family and booking.assigned_family.telegram_chat_id:
                send(booking.assigned_family.telegram_chat_id,
                     t(booking.assigned_family.telegram_chat_id, "guest_cancelled",
                       booking.name, booking.date.strftime("%d.%m"), booking.meal_label))
            if msg.get("text"):
                edit_msg(chat_id, message_id, (msg.get("text") or "") + "\n❌ <b>Отменено вами</b>", EMPTY_KB)
            return

        if data.startswith("cancel_family:"):
            bid = int(data.split(":")[1])
            booking = Booking.objects.filter(pk=bid).first()
            pressing_family = Family.objects.filter(telegram_chat_id=user_id).first() if user_id else None
            if not booking or not pressing_family or booking.assigned_family != pressing_family or booking.status in ["cancelled", "declined"]:
                answer_cb(cb_id, t(chat_id, "no_access") if not booking or not pressing_family or booking.assigned_family != pressing_family else t(chat_id, "booking_already_cancelled"))
                return
            booking.status = "cancelled"
            booking.decided_at = timezone.now()
            booking.save(update_fields=["status", "decided_at"])
            answer_cb(cb_id, t(chat_id, "you_cancelled_family"))
            if booking.tg_id:
                send(booking.tg_id, t(booking.tg_id, "family_cancelled",
                                      booking.date.strftime("%d.%m"), booking.meal_label))
            if msg.get("text"):
                edit_msg(chat_id, message_id, (msg.get("text") or "") + "\n❌ <b>Отменено вами</b>", EMPTY_KB)
            return
    except Exception as e:
        log.exception("Ошибка в handle_callback: %s", e)
        answer_cb(cb_id, "Произошла ошибка.")
        return
    answer_cb(cb_id)

def main():
    if not TOKEN:
        log.error("BOT_TOKEN не задан — бот не запущен")
        sys.exit(1)
    log.info("Старт бота (часовой пояс %s)", timezone.get_current_timezone())
    offset = 0
    while True:
        try:
            r = requests.get(API + "getUpdates",
                             params={"offset": offset, "timeout": 25, "allowed_updates": '["message","callback_query"]'},
                             timeout=40, proxies=PROXIES)
            data = r.json()
        except Exception as exc:
            log.warning("poll: %s", exc)
            time.sleep(3)
            continue
        if not data.get("ok"):
            log.warning("getUpdates: %s", data.get("description"))
            time.sleep(3)
            continue
        for update in data.get("result", []):
            offset = max(offset, update.get("update_id", 0) + 1)
            try:
                if "message" in update:
                    handle_message(update["message"])
                elif "callback_query" in update:
                    handle_callback(update["callback_query"])
            except Exception:
                log.exception("Ошибка обработки update %s", update.get("update_id"))

if __name__ == "__main__":
    main()