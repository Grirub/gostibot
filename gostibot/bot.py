#!/usr/bin/env python3
"""Telegram-бот записи в гости: long polling + Django ORM.

Запуск: python3 bot.py  (токен берётся из .env или переменной окружения BOT_TOKEN)
"""
import html
import logging
import os
import sys
import time
from datetime import date, datetime, time as dtime, timedelta
from logging.handlers import RotatingFileHandler

import requests

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

import django  # noqa: E402

django.setup()

from django.utils import timezone  # noqa: E402

from core import schedule  # noqa: E402
from core.models import MEAL_CONFIG, Booking, Family  # noqa: E402

TOKEN = (os.environ.get("BOT_TOKEN") or "").strip()
OWNER_CODE = (os.environ.get("OWNER_CODE") or "").strip()
API = f"https://api.telegram.org/bot{TOKEN}/"
BOT_USERNAME = ""

log = logging.getLogger("gostibot")
log.setLevel(logging.INFO)
_fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
_fh = RotatingFileHandler(os.path.join(BASE_DIR, "bot.log"), maxBytes=2_000_000, backupCount=3, encoding="utf-8")
_fh.setFormatter(_fmt)
_sh = logging.StreamHandler(sys.stdout)
_sh.setFormatter(_fmt)
log.addHandler(_fh)
log.addHandler(_sh)

EMPTY_KB = {"inline_keyboard": []}

STATUS_ICON = {
    "pending": "⏳ ожидает подтверждения",
    "confirmed": "✅ подтверждена",
    "declined": "❌ отклонена",
    "cancelled": "🚫 отменена",
}

STATE = {}  # chat_id -> {"step": str, "data": dict}


# ---------------------------------------------------------------- API helpers
def api(method, **params):
    try:
        r = requests.post(API + method, json=params, timeout=60)
        data = r.json()
    except Exception as exc:  # noqa: BLE001
        log.warning("API %s: %s", method, exc)
        return {"ok": False}
    if not data.get("ok"):
        log.warning("API %s: %s", method, data.get("description"))
    return data


def send(chat_id, text, kb=None):
    params = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if kb is not None:
        params["reply_markup"] = kb
    return api("sendMessage", **params)


def edit_msg(chat_id, message_id, text, kb=None):
    params = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
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


# ---------------------------------------------------------------- keyboards
def kb_main():
    return {
        "inline_keyboard": [
            [{"text": "📅 Записаться в гости", "callback_data": "book"}],
            [{"text": "📋 Мои записи", "callback_data": "my"}],
            [{"text": "ℹ️ Как это работает", "callback_data": "info"}],
        ]
    }


def kb_meals(options):
    """Две трапезы: пятница вечером или суббота днём (список ближайших дат)."""
    rows = []
    for day, meal in options:
        label = schedule.meal_label(day, meal)
        rows.append([{"text": label, "callback_data": f"m:{day.isoformat()}|{meal}"}])
    rows.append([{"text": "⬅️ В меню", "callback_data": "menu"}])
    return {"inline_keyboard": rows}


def kb_families(families=None, day=None, meal=None):
    rows = []
    for f in (families if families is not None else Family.objects.filter(is_active=True)):
        label = f.name
        if day and meal:
            left = schedule.family_free(day, meal, f)
            label = f"{f.name} · свободно {schedule.places_text(left)}"
        rows.append([{"text": label, "callback_data": f"f:{f.pk}"}])
    rows.append([{"text": "⬅️ В меню", "callback_data": "menu"}])
    return {"inline_keyboard": rows}


def ask_family(chat_id, message_id=None):
    s = schedule.get_settings()
    st = get_state(chat_id) or {"step": "family", "data": {}}
    d = st["data"]
    day = date.fromisoformat(d["date"]) if d.get("date") else None
    meal = d.get("meal")
    all_families = list(Family.objects.filter(is_active=True))
    if not all_families:
        st["step"] = "name"
        STATE[chat_id] = st
        ask_name(chat_id)
        return
    families = all_families
    if day and meal:
        families = [f for f in all_families if schedule.family_free(day, meal, f) > 0]
        if not families:
            st["step"] = "meal"
            STATE[chat_id] = st
            options = schedule.meal_options(s)
            text = (
                "😔 На эту трапезу мест у семей больше не осталось.\n\n"
                "Выберите другой день:"
            )
            kb = kb_meals(options) if options else kb_main()
            if options:
                d.pop("date", None)
                d.pop("meal", None)
            if message_id:
                edit_msg(chat_id, message_id, text, kb)
            else:
                send(chat_id, text, kb)
            return
    st["step"] = "family"
    STATE[chat_id] = st
    header = "🏡 <b>К кому вы идёте?</b>\n\nВыберите семью."
    if day and meal:
        header = (
            f"Вы выбрали <b>{esc(schedule.meal_title(day, meal))}</b>.\n\n"
            "🏡 <b>К кому вы идёте?</b> Выберите семью — рядом видно, сколько у неё осталось мест:"
        )
    kb = kb_families(families, day, meal)
    if message_id:
        edit_msg(chat_id, message_id, header, kb)
    else:
        send(chat_id, header, kb)


def seats_left(chat_id):
    """Остаток мест у выбранной в диалоге семьи на выбранную трапезу (None — не выбрать ещё)."""
    st = get_state(chat_id)
    if not st:
        return None
    d = st.get("data") or {}
    if not (d.get("date") and d.get("meal") and d.get("family")):
        return None
    fam = Family.objects.filter(pk=d["family"]).first()
    if not fam:
        return None
    return schedule.family_free(date.fromisoformat(d["date"]), d["meal"], fam)


def kb_guests(max_guests):
    rows, row = [], []
    for n in range(1, max_guests + 1):
        row.append({"text": str(n), "callback_data": f"g:{n}"})
        if len(row) == 5:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([{"text": "🏠 Меню", "callback_data": "menu"}])
    return {"inline_keyboard": rows}


def kb_confirm():
    return {
        "inline_keyboard": [
            [{"text": "✅ Отправить заявку", "callback_data": "ok"}],
            [{"text": "✏️ Заполнить заново", "callback_data": "book"}],
            [{"text": "🏠 Меню", "callback_data": "menu"}],
        ]
    }


def kb_phone():
    return {
        "keyboard": [
            [{"text": "📱 Отправить мой номер", "request_contact": True}],
            [{"text": "Пропустить"}],
        ],
        "resize_keyboard": True,
        "one_time_keyboard": True,
    }


def remove_kb():
    return {"remove_keyboard": True}


# ---------------------------------------------------------------- state
def get_state(chat_id):
    return STATE.get(chat_id)


def set_state(chat_id, step, data=None):
    STATE[chat_id] = {"step": step, "data": data or {}}


def clear_state(chat_id):
    STATE.pop(chat_id, None)


def is_owner(chat_id):
    return chat_id in schedule.get_settings().owner_ids()


def is_private(message):
    return (message.get("chat") or {}).get("type") == "private"


# ---------------------------------------------------------------- guest flow
def show_menu(chat_id, message_id=None):
    s = schedule.get_settings()
    text = f"<b>{esc(s.title)}</b>\n\n{esc(s.greeting)}"
    if s.address:
        text += f"\n\n📍 {esc(s.address)}"
    if s.contact:
        text += f"\n☎️ {esc(s.contact)}"
    text += f"\n\n🍽 Запись открыта: {esc(schedule.meals_text())}"
    if message_id:
        edit_msg(chat_id, message_id, text, kb_main())
    else:
        send(chat_id, text, kb_main())


def start_booking(chat_id, message_id=None):
    set_state(chat_id, "meal", {})
    s = schedule.get_settings()
    options = schedule.meal_options(s)
    if not options:
        text = (
            "😔 Ближайших трапез для записи сейчас нет.\n\n"
            "Запись открыта на пятницу (вечерняя трапеза) и субботу (дневная трапеза) — "
            f"загляните позже, в ближайшие {s.days_ahead} дн. подходящих дат не осталось."
        )
        if s.contact:
            text += f"\n\n☎️ Связаться: {esc(s.contact)}"
        if message_id:
            edit_msg(chat_id, message_id, text, kb_main())
        else:
            send(chat_id, text, kb_main())
        return
    text = (
        "🍽 <b>Когда вам удобно прийти?</b>\n\n"
        "Есть два варианта: <b>пятница, вечерняя трапеза</b> или "
        "<b>суббота, дневная трапеза</b>. Выберите подходящий день:"
    )
    if message_id:
        edit_msg(chat_id, message_id, text, kb_meals(options))
    else:
        send(chat_id, text, kb_meals(options))


def ask_name(chat_id):
    set_state(chat_id, "name", (get_state(chat_id) or {}).get("data", {}))
    send(
        chat_id,
        "✍️ Как вас зовут? Напишите имя одним сообщением.",
        remove_kb(),
    )


def ask_phone(chat_id):
    st = get_state(chat_id) or {"step": "phone", "data": {}}
    st["step"] = "phone"
    STATE[chat_id] = st
    send(
        chat_id,
        "📞 Отправьте номер телефона кнопкой ниже — или напишите его текстом.\n"
        "Можно пропустить.",
        kb_phone(),
    )


def ask_guests(chat_id):
    st = get_state(chat_id) or {"step": "guests", "data": {}}
    st["step"] = "guests"
    STATE[chat_id] = st
    s = schedule.get_settings()
    limit = s.max_guests
    left = seats_left(chat_id)
    if left is not None:
        limit = max(1, min(limit, left))
    text = "👥 Сколько вас будет?"
    if left is not None and left < s.max_guests:
        text += f"\n\nУ этой семьи на выбранную трапезу осталось {schedule.places_text(left)}."
    send(chat_id, text, kb_guests(limit))


def ask_confirm(chat_id):
    st = get_state(chat_id)
    if not st:
        send(chat_id, "Начнём заново.", kb_main())
        return
    st["step"] = "confirm"
    d = st["data"]
    day = date.fromisoformat(d["date"])
    lines = [
        "Проверьте заявку:",
        f"🍽 <b>{esc(schedule.meal_title(day, d['meal']))}</b>",
        f"🏡 {esc(schedule.family_name(d.get('family')))}",
        f"👤 {esc(d['name'])}",
    ]
    if d.get("phone"):
        lines.append(f"📞 {esc(d['phone'])}")
    if schedule.get_settings().ask_guests:
        lines.append(f"👥 гостей: {d.get('guests', 1)}")
    lines.append("")
    lines.append("Если всё верно — отправьте заявку, хозяева подтвердят её.")
    send(chat_id, "\n".join(lines), kb_confirm())


def create_booking(chat_id, username, message_id=None):
    st = get_state(chat_id)
    if not st or st.get("step") != "confirm":
        return
    d = st["data"]
    day = date.fromisoformat(d["date"])
    meal = d["meal"]
    s = schedule.get_settings()
    hh, mm = MEAL_CONFIG[meal]["time"]
    family = Family.objects.filter(pk=d.get("family")).first() if d.get("family") else None
    guests = d.get("guests", 1)
    if family:
        left = schedule.family_free(day, meal, family)
        if guests > left:
            if left <= 0:
                st["step"] = "family"
                STATE[chat_id] = st
                ask_family(chat_id, message_id)
                return
            st["step"] = "guests"
            STATE[chat_id] = st
            text = (
                f"😔 У семьи {esc(family.name)} на эту трапезу осталось "
                f"{schedule.places_text(left)}.\n\n"
                "Выберите число поменьше — или вернитесь и выберите другую семью."
            )
            kb = kb_guests(max(1, min(s.max_guests, left)))
            if message_id:
                edit_msg(chat_id, message_id, text, kb)
            else:
                send(chat_id, text, kb)
            return
    booking = Booking.objects.create(
        date=day,
        meal=meal,
        family=family,
        time=dtime(hh, mm),
        name=d["name"][:100],
        phone=(d.get("phone") or "")[:40],
        guests=guests,
        tg_id=chat_id,
        tg_username=(username or "")[:64],
        status="pending",
    )
    clear_state(chat_id)
    log.info("Новая заявка #%s %s %s %s", booking.pk, day, meal, booking.name)
    def notify_owners(booking):
    # Уведомление выбранной семьи по числовому Telegram ID.
    family = booking.family
    if family and family.telegram_chat_id:
        family_text = (
            "🆕 <b>Новая заявка для вашей семьи</b> №" + str(booking.pk) + "\n"
            + booking_line(booking)
            + (f"\n🔗 @{esc(booking.tg_username)}" if booking.tg_username else "")
        )
        result = send(family.telegram_chat_id, family_text)
        if not result.get("ok"):
            log.warning(
                "Не удалось уведомить семью %s (ID %s) о заявке #%s: %s",
                family.name, family.telegram_chat_id, booking.pk,
                result.get("description", "")
            )
    elif family:
        log.info(
            "У семьи %s не указан Telegram ID — заявка #%s сохранена без уведомления семьи",
            family.name, booking.pk
        )

    s = schedule.get_settings()
    if not s.notify_owner:
        return
    owners = s.owner_ids()
    if not owners:
        log.warning("Владельцы не настроены — заявка #%s сохранена без уведомления владельцев", booking.pk)
        return
    text = (
        "🆕 <b>Новая заявка</b> №" + str(booking.pk) + "\n"
        + booking_line(booking)
        + (f"\n🔗 @{esc(booking.tg_username)}" if booking.tg_username else "")
        + f"\n🆔 <code>{booking.tg_id}</code>"
    )
    kb = {
        "inline_keyboard": [
            [
                {"text": "✅ Подтвердить", "callback_data": f"a:{booking.pk}"},
                {"text": "❌ Отклонить", "callback_data": f"r:{booking.pk}"},
            ]
        ]
    }
    for owner in owners:
        send(owner, text, kb)

def booking_line(b):
    when = schedule.meal_title(b.date, b.meal) if b.meal else f"{b.date:%d.%m.%Y}"
    return (
        f"🍽 <b>{esc(when)}</b>\n"
        + (f"🏡 {esc(b.family.name)}\n" if b.family else "")
        + f"👤 {esc(b.name)}"
        + (f"\n📞 {esc(b.phone)}" if b.phone else "")
        + f"\n👥 гостей: {b.guests}"
    )


def notify_owners(booking):
    s = schedule.get_settings()
    if not s.notify_owner:
        return
    owners = s.owner_ids()
    if not owners:
        log.warning("Владельцы не настроены — заявка #%s сохранена без уведомления", booking.pk)
        return
    text = (
        "🆕 <b>Новая заявка</b> №" + str(booking.pk) + "\n\n"
        + booking_line(booking)
        + (f"\n🔗 @{esc(booking.tg_username)}" if booking.tg_username else "")
        + f"\n🆔 <code>{booking.tg_id}</code>"
    )
    kb = {
        "inline_keyboard": [
            [
                {"text": "✅ Подтвердить", "callback_data": f"a:{booking.pk}"},
                {"text": "❌ Отклонить", "callback_data": f"r:{booking.pk}"},
            ]
        ]
    }
    for owner in owners:
        send(owner, text, kb)


def show_my(chat_id, message_id=None):
    today = timezone.localdate()
    qs = (
        Booking.objects.filter(tg_id=chat_id, date__gte=today)
        .exclude(status__in=["declined", "cancelled"])
        .order_by("date", "time")[:10]
    )
    rows = list(qs)
    if not rows:
        text = "У вас пока нет активных записей.\nНажмите «Записаться в гости», чтобы выбрать трапезу."
        kb = {"inline_keyboard": [[{"text": "📅 Записаться в гости", "callback_data": "book"}],
                                  [{"text": "🏠 Меню", "callback_data": "menu"}]]}
    else:
        parts = [f"📋 <b>Ваши записи</b> ({len(rows)})", ""]
        buttons = []
        for b in rows:
            parts.append(
                f"№{b.pk} · <b>{b.date:%d.%m} · {esc(b.meal_label.lower())}</b>"
                + (f" · {esc(b.family.name)}" if b.family else "")
                + f" — {STATUS_ICON[b.status]}"
            )
            buttons.append([{"text": f"❌ Отменить №{b.pk}", "callback_data": f"c:{b.pk}"}])
        parts.append("")
        parts.append("Отменить запись можно кнопкой ниже.")
        text = "\n".join(parts)
        buttons.append([{"text": "📅 Записаться в гости", "callback_data": "book"}])
        buttons.append([{"text": "🏠 Меню", "callback_data": "menu"}])
        kb = {"inline_keyboard": buttons}
    if message_id:
        edit_msg(chat_id, message_id, text, kb)
    else:
        send(chat_id, text, kb)


def info_text():
    s = schedule.get_settings()
    families = schedule.families_text()
    text = (
        "ℹ️ <b>Как это работает</b>\n\n"
        "1. Нажимаете «Записаться в гости» и выбираете день: пятница (вечерняя "
        "трапеза) или суббота (дневная трапеза).\n"
        "2. Выбираете, к какой семье идёте.\n"
        "3. Пишете имя (и телефон, если нужно) и число гостей — заявка уходит хозяевам.\n"
        "4. Хозяева подтверждают запись, вам приходит сообщение.\n\n"
        f"🍽 Варианты: {esc(schedule.meals_text())}.\n"
    )
    if families:
        text += (
            f"🏡 Семьи: {esc(families)}.\n"
            "🪑 Мест у каждой семьи своё — остаток виден на кнопках.\n"
        )
    text += (
        "📋 Свои записи смотрите в «Мои записи», отменить можно там же."
    )
    if s.address:
        text += f"\n\n📍 {esc(s.address)}"
    if s.contact:
        text += f"\n☎️ Вопросы: {esc(s.contact)}"
    return text


# ---------------------------------------------------------------- owner side
def owner_list(chat_id, day=None):
    qs = Booking.objects.exclude(status__in=["declined", "cancelled"])
    if day:
        qs = qs.filter(date=day)
        title = f"📅 Записи на {day:%d.%m.%Y}"
    else:
        qs = qs.filter(date__gte=timezone.localdate())
        title = "📅 Ближайшие записи"
    rows = list(qs.order_by("date", "time")[:25])
    if not rows:
        send(chat_id, title + "\n\nПока пусто.")
        return
    total_guests = sum(b.guests for b in rows)
    parts = [f"<b>{title}</b> — {len(rows)} шт., гостей: {total_guests}", ""]
    for b in rows:
        parts.append(
            f"<b>{b.date:%d.%m} · {esc(b.meal_label.lower())}</b>"
            + (f" · {esc(b.family.name)}" if b.family else "")
            + f" · {esc(b.name)} · 👥{b.guests} · {STATUS_ICON[b.status]}"
            + (f"\n    📞 {esc(b.phone)}" if b.phone else "")
            + (f" · @{esc(b.tg_username)}" if b.tg_username else "")
        )
    send(chat_id, "\n".join(parts))


def decide(booking_id, status, actor_chat_id, message_id, chat_id):
    booking = Booking.objects.filter(pk=booking_id).first()
    if not booking:
        edit_msg(chat_id, message_id, "Заявка не найдена.", EMPTY_KB)
        return
    if booking.status == "cancelled":
        edit_msg(
            chat_id,
            message_id,
            "🚫 Гость отменил эту запись — подтверждать нечего.\n\n" + booking_line(booking),
            EMPTY_KB,
        )
        return
    booking.status = status
    booking.decided_at = timezone.now()
    booking.save(update_fields=["status", "decided_at"])
    verdict = "✅ Подтверждено" if status == "confirmed" else "❌ Отклонено"
    card = f"{verdict}\n\n{booking_line(booking)}"
    if booking.tg_username:
        card += f"\n🔗 @{esc(booking.tg_username)}"
    edit_msg(chat_id, message_id, card, EMPTY_KB)
    if booking.tg_id:
        if status == "confirmed":
            text = (
                "✅ <b>Ваша запись подтверждена!</b>\n\n"
                + booking_line(booking)
                + "\n\nЖдём вас. Если планы изменились — отмените запись в «Мои записи»."
            )
            kb = {"inline_keyboard": [[{"text": "📋 Мои записи", "callback_data": "my"}]]}
        else:
            text = (
                "😔 К сожалению, заявку не удалось подтвердить.\n\n"
                + booking_line(booking)
                + "\n\nПопробуйте выбрать другое время."
            )
            kb = {"inline_keyboard": [[{"text": "📅 Выбрать другое время", "callback_data": "book"}]]}
        send(booking.tg_id, text, kb)


def cancel_by_guest(booking_id, chat_id, message_id):
    booking = Booking.objects.filter(pk=booking_id).first()
    if not booking:
        edit_msg(chat_id, message_id, "Запись не найдена.", EMPTY_KB)
        return
    if booking.tg_id != chat_id:
        edit_msg(chat_id, message_id, "Это не ваша запись.", EMPTY_KB)
        return
    if booking.status in ("cancelled", "declined"):
        edit_msg(chat_id, message_id, "Эта запись уже отменена.\n\n" + booking_line(booking), EMPTY_KB)
        return
    booking.status = "cancelled"
    booking.decided_at = timezone.now()
    booking.save(update_fields=["status", "decided_at"])
    edit_msg(
        chat_id,
        message_id,
        "🚫 Запись отменена.\n\n" + booking_line(booking) + "\n\nМожно выбрать новое время.",
        {"inline_keyboard": [[{"text": "📅 Записаться в гости", "callback_data": "book"}],
                             [{"text": "🏠 Меню", "callback_data": "menu"}]]},
    )
    for owner in schedule.get_settings().owner_ids():
        send(
            owner,
            "🚫 <b>Гость отменил запись</b> №" + str(booking.pk) + "\n\n" + booking_line(booking),
        )


# ---------------------------------------------------------------- update routing
def handle_message(message):
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    if not chat_id:
        return
    text = (message.get("text") or "").strip()
    username = (message.get("from") or {}).get("username") or ""

    if not is_private(message):
        if text.startswith("/start"):
            send(chat_id, "Я работаю в личных сообщениях — напишите мне в личку.")
        return

    if message.get("contact") and (get_state(chat_id) or {}).get("step") == "phone":
        st = get_state(chat_id)
        st["data"]["phone"] = (message["contact"].get("phone_number") or "")[:40]
        send(chat_id, "Записал номер.", remove_kb())
        next_after_phone(chat_id)
        return

    if text.startswith("/"):
        handle_command(chat_id, text, username)
        return

    st = get_state(chat_id)
    if st and st.get("step") == "family":
        send(chat_id, "Выберите семью кнопкой в сообщении выше 👆")
        return

    if st and st.get("step") == "name":
        name = " ".join(text.split())[:100]
        if len(name) < 2:
            send(chat_id, "Напишите, пожалуйста, имя (хотя бы 2 буквы).")
            return
        st["data"]["name"] = name
        STATE[chat_id] = st
        s = schedule.get_settings()
        if s.ask_phone:
            ask_phone(chat_id)
        elif s.ask_guests:
            ask_guests(chat_id)
        else:
            st["data"].setdefault("guests", 1)
            ask_confirm(chat_id)
        return

    if st and st.get("step") == "phone":
        phone = text[:40]
        st["data"]["phone"] = "" if phone.lower() in ("пропустить", "нет", "-", "skip") else phone
        send(chat_id, "Принято.", remove_kb())
        next_after_phone(chat_id)
        return

    if st and st.get("step") == "comment":
        st["data"]["comment"] = text[:300]
        STATE[chat_id] = st
        ask_confirm(chat_id)
        return

    # всё остальное — показать меню
    if st:
        send(chat_id, "Продолжим запись — используйте кнопки в сообщении выше.")
        return
    show_menu(chat_id)


def next_after_phone(chat_id):
    s = schedule.get_settings()
    if s.ask_guests:
        ask_guests(chat_id)
    else:
        st = get_state(chat_id) or {"step": "confirm", "data": {}}
        st["data"].setdefault("guests", 1)
        STATE[chat_id] = st
        ask_confirm(chat_id)


def handle_command(chat_id, text, username):
    cmd, _, args = text.partition(" ")
    cmd = cmd.lower().lstrip("/")
    if "@" in cmd:
        cmd = cmd.split("@", 1)[0]
    args = args.strip()
    owner = is_owner(chat_id)

    if cmd in ("start", "menu"):
        clear_state(chat_id)
        show_menu(chat_id)
    elif cmd == "help":
        send(chat_id, info_text(), kb_main())
    elif cmd in ("my", "mine", "записи"):
        show_my(chat_id)
    elif cmd in ("cancel", "отмена"):
        clear_state(chat_id)
        send(chat_id, "Ок, отменил. Вернуться в меню — /start", remove_kb())
    elif cmd == "id":
        send(chat_id, f"Ваш Telegram ID: <code>{chat_id}</code>")
    elif cmd == "owner":
        claim_owner(chat_id, args)
    elif cmd in ("today", "сегодня"):
        if not owner:
            send(chat_id, "Команда доступна хозяевам.")
            return
        owner_list(chat_id, timezone.localdate())
    elif cmd in ("upcoming", "все"):
        if not owner:
            send(chat_id, "Команда доступна хозяевам.")
            return
        owner_list(chat_id)
    elif cmd == "stats":
        if not owner:
            send(chat_id, "Команда доступна хозяевам.")
            return
        stats(chat_id)
    else:
        send(chat_id, "Не знаю такой команды. /start — меню, /help — как это работает.")


def claim_owner(chat_id, args):
    s = schedule.get_settings()
    if chat_id in s.owner_ids():
        send(chat_id, "Вы уже хозяин этого бота. Команды: /today, /upcoming, /stats")
        return
    if not OWNER_CODE:
        send(chat_id, "Код владельца не настроен. Задайте OWNER_CODE в файле .env.")
        return
    if args != OWNER_CODE:
        send(chat_id, "Неверный код. Использование: /owner КОД")
        return
    ids = s.owner_ids()
    ids.append(chat_id)
    s.owner_chat_ids = ",".join(str(i) for i in ids)
    s.save()
    send(
        chat_id,
        "👑 Готово, теперь вы хозяин бота.\n\n"
        "Сюда будут приходить заявки с кнопками «Подтвердить/Отклонить».\n\n"
        "Команды:\n/today — записи на сегодня\n/upcoming — ближайшие записи\n/stats — сводка",
    )


def stats(chat_id):
    today = timezone.localdate()
    upcoming = Booking.objects.filter(date__gte=today).exclude(status__in=["declined", "cancelled"])
    pending = upcoming.filter(status="pending").count()
    confirmed = upcoming.filter(status="confirmed").count()
    guests = sum(b.guests for b in upcoming)
    week_end = today + timedelta(days=7)
    week = upcoming.filter(date__lt=week_end)
    send(
        chat_id,
        "<b>Сводка</b>\n\n"
        f"Ближайших записей: {upcoming.count()} (гостей: {guests})\n"
        f"⏳ ожидают: {pending}\n✅ подтверждено: {confirmed}\n"
        f"На 7 дней: {week.count()} записей\n\n"
        "Все заявки — в админке.",
    )


def handle_callback(cb):
    data = cb.get("data") or ""
    msg = cb.get("message") or {}
    chat_id = (msg.get("chat") or {}).get("id")
    message_id = msg.get("id")
    cb_id = cb.get("id")
    username = (cb.get("from") or {}).get("username") or ""
    if not chat_id:
        return

    if data == "menu":
        clear_state(chat_id)
        answer_cb(cb_id)
        show_menu(chat_id, message_id)
        return
    if data == "info":
        answer_cb(cb_id)
        edit_msg(chat_id, message_id, info_text(), kb_main())
        return
    if data == "my":
        answer_cb(cb_id)
        show_my(chat_id, message_id)
        return
    if data == "book":
        answer_cb(cb_id)
        start_booking(chat_id, message_id)
        return
    if data.startswith("m:"):
        answer_cb(cb_id)
        payload = data[2:]
        if "|" not in payload:
            return
        day_s, meal = payload.split("|", 1)
        if meal not in MEAL_CONFIG:
            return
        try:
            day = date.fromisoformat(day_s)
        except ValueError:
            return
        st = get_state(chat_id) or {"step": "family", "data": {}}
        st["data"]["date"] = day_s
        st["data"]["meal"] = meal
        st["step"] = "family"
        STATE[chat_id] = st
        ask_family(chat_id, message_id)
        return
    if data.startswith("f:"):
        try:
            fid = int(data[2:])
        except ValueError:
            return
        family = Family.objects.filter(pk=fid, is_active=True).first()
        if not family:
            answer_cb(cb_id)
            return
        st = get_state(chat_id)
        if not st or st.get("step") != "family":
            answer_cb(cb_id)
            return
        d = st["data"]
        left = schedule.family_free(date.fromisoformat(d["date"]), d["meal"], family)
        if left <= 0:
            answer_cb(cb_id, "Мест у этой семьи уже нет")
            ask_family(chat_id, message_id)
            return
        answer_cb(cb_id)
        st["data"]["family"] = family.pk
        st["step"] = "name"
        STATE[chat_id] = st
        when = schedule.meal_title(date.fromisoformat(d["date"]), d["meal"])
        edit_msg(
            chat_id,
            message_id,
            f"🍽 <b>{esc(when)}</b>\n🏡 <b>{esc(family.name)}</b>\n\n"
            "✍️ Как вас зовут? Напишите имя сообщением.",
            remove_kb(),
        )
        return
    if data.startswith("g:"):
        answer_cb(cb_id)
        try:
            n = int(data[2:])
        except ValueError:
            return
        st = get_state(chat_id)
        if not st:
            return
        n = max(1, min(50, n))
        left = seats_left(chat_id)
        if left is not None:
            n = max(1, min(n, left))
        st["data"]["guests"] = n
        STATE[chat_id] = st
        ask_confirm(chat_id)
        return
    if data == "ok":
        answer_cb(cb_id)
        create_booking(chat_id, username, message_id)
        return
    if data.startswith("c:"):
        answer_cb(cb_id)
        try:
            bid = int(data[2:])
        except ValueError:
            return
        cancel_by_guest(bid, chat_id, message_id)
        return
    if data.startswith("a:") or data.startswith("r:"):
        if not is_owner(chat_id):
            answer_cb(cb_id, "Кнопка доступна только хозяевам.")
            return
        answer_cb(cb_id)
        try:
            bid = int(data[2:])
        except ValueError:
            return
        decide(bid, "confirmed" if data[0] == "a" else "declined", chat_id, message_id, chat_id)
        return
    answer_cb(cb_id)


def setup_bot():
    global BOT_USERNAME
    me = api("getMe")
    if me.get("ok"):
        BOT_USERNAME = me["result"].get("username", "")
        log.info("Бот @%s на связи", BOT_USERNAME)
    else:
        log.error("getMe не удался — проверьте BOT_TOKEN: %s", me)
        return False
    api(
        "setMyCommands",
        commands=[
            {"command": "start", "description": "Меню и запись в гости"},
            {"command": "my", "description": "Мои записи"},
            {"command": "help", "description": "Как это работает"},
            {"command": "cancel", "description": "Прервать заполнение"},
        ],
    )
    return True


def main():
    if not TOKEN:
        log.error("BOT_TOKEN не задан — бот не запущен")
        sys.exit(1)
    log.info("Старт бота (часовой пояс %s)", timezone.get_current_timezone())
    if not setup_bot():
        sys.exit(1)
    offset = 0
    while True:
        try:
            r = requests.get(
                API + "getUpdates",
                params={"offset": offset, "timeout": 25, "allowed_updates": '["message","callback_query"]'},
                timeout=40,
            )
            data = r.json()
        except Exception as exc:  # noqa: BLE001
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
            except Exception:  # noqa: BLE001
                log.exception("Ошибка обработки update %s", update.get("update_id"))


if __name__ == "__main__":
    main()
