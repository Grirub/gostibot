#!/usr/bin/env python3
"""Главный роутер бота."""
import html
import logging
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Настройка логирования
BASE_DIR = Path(__file__).resolve().parent
log = logging.getLogger("gostibot")
log.setLevel(logging.INFO)
fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
fh = RotatingFileHandler(BASE_DIR / "bot.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
fh.setFormatter(fmt)
sh = logging.StreamHandler(sys.stdout)
sh.setFormatter(fmt)
log.addHandler(fh)
log.addHandler(sh)

# Инициализация
from bot_app.config import TOKEN, PROXIES  # noqa: E402
from bot_app.api import api, send, edit_msg, answer_cb  # noqa: E402
from bot_app.translations import t, t_lang, get_lang  # noqa: E402
from bot_app.states import get_state, clear_state, set_state  # noqa: E402
from bot_app.handlers import guest, family, booking, edit  # noqa: E402
from bot_app.services.booking_service import (  # noqa: E402
    claim_booking, cancel_booking_by_guest, cancel_booking_by_family,
    cancel_all_old_bookings
)
from bot_app.services.notifications import (  # noqa: E402
    send_booking_to_group, notify_guest, notify_guest_cancelled_by_family,
    notify_family_about_guest_cancel
)
from bot_app.keyboards import (  # noqa: E402
    kb_languages, kb_my_bookings, kb_main_menu, kb_menu_only,
    can_guest_cancel, can_family_cancel, is_booking_deadline_passed
)
from core.models import GuestProfile, Family, Booking, Blacklist  # noqa: E402
from django.utils import timezone  # noqa: E402


def is_blocked(chat_id):
    try:
        return Blacklist.is_blocked(chat_id)
    except Exception as exc:
        log.error("is_blocked error: %s", exc)
        return False


def handle_message(message):
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    if not chat_id or chat.get("type") != "private":
        return
    if is_blocked(chat_id):
        send(chat_id, t(chat_id, "blocked"))
        return

    text = (message.get("text") or "").strip()

    # ✅ ИЗВЛЕКАЕМ username из сообщения (нужен для /start)
    from_user = message.get("from") or {}
    username = from_user.get("username") or ""

    if text == "/reset":
        clear_state(chat_id)
        profile = GuestProfile.objects.filter(tg_id=chat_id).first()
        if profile:
            profile.language = ""
            profile.consented_at = None
            profile.save()
        send(chat_id, t(chat_id, "profile_reset"))
        return
    if text.startswith("/start"):
        clear_state(chat_id)
        # ✅ ПЕРЕДАЁМ username в start_flow
        guest.start_flow(chat_id, username=username)
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
    try:
        if step == "family_name":
            family.handle_family_reg(chat_id, text)
        elif step == "guest_photo":
            guest.handle_guest_photo(chat_id, message)
        elif step == "guest_name":
            guest.handle_guest_name(chat_id, text)
        elif step == "guest_phone":
            guest.handle_guest_phone(chat_id, message)
        elif step == "guest_origin":
            pass  # callback only
        elif step == "guest_gender":
            pass  # callback only
        elif step == "guest_comment":
            guest.handle_guest_comment(chat_id, text)
        elif step == "add_meal_comment":
            booking.handle_add_meal_comment(chat_id, text)
        elif step == "edit_name_input":
            edit.handle_edit_name_input(chat_id, text)
        elif step == "edit_phone_input":
            edit.handle_edit_phone_input(chat_id, message)
        elif step == "edit_photo_input":
            edit.handle_edit_photo_input(chat_id, message)
    except Exception as exc:
        log.exception("Message error: %s", exc)


def handle_callback(cb):
    data = cb.get("data") or ""
    msg = cb.get("message") or {}
    chat_id = (msg.get("chat") or {}).get("id")
    message_id = msg.get("id")
    cb_id = cb.get("id")
    user_id = (cb.get("from") or {}).get("id")
    if not chat_id:
        return

    if is_blocked(chat_id) and not data.startswith("menu"):
        answer_cb(cb_id, t(chat_id, "blocked"))
        send(chat_id, t(chat_id, "blocked"))
        return

    try:
        # Меню
        if data == "menu":
            clear_state(chat_id)
            answer_cb(cb_id)
            guest.show_menu(chat_id, message_id)
            return

        # Редактирование
        if data.startswith("edit"):
            answer_cb(cb_id)
            edit.route(chat_id, data, message_id)
            return

        # Язык
        if data.startswith("setlang:"):
            answer_cb(cb_id)
            guest.handle_set_language(chat_id, data.split(":")[1])
            return

        # Согласие
        if data.startswith("consent:"):
            answer_cb(cb_id)
            st = get_state(chat_id)
            if st and st["step"] == "family_consent":
                family.handle_family_consent(chat_id, data.split(":")[1])
            else:
                guest.handle_consent(chat_id, data.split(":")[1])
            return

        # Роль
        if data.startswith("role:"):
            answer_cb(cb_id)
            guest.handle_role(chat_id, data.split(":")[1])
            return

        # Происхождение и пол
        if data.startswith("jo:"):
            answer_cb(cb_id)
            guest.handle_guest_origin(chat_id, data)
            return
        if data.startswith("gen:"):
            answer_cb(cb_id)
            guest.handle_guest_gender(chat_id, data)
            return

        # Города и районы
        if data.startswith("city:"):
            answer_cb(cb_id)
            guest.handle_select_city(chat_id, int(data.split(":")[1]))
            return
        if data.startswith("dist:"):
            answer_cb(cb_id)
            guest.handle_select_district(chat_id, int(data.split(":")[1]))
            return
        if data == "cities":
            answer_cb(cb_id)
            st = get_state(chat_id)
            if st:
                set_state(chat_id, "select_city", st["data"])
                from bot_app.keyboards import kb_cities
                send(chat_id, t(chat_id, "select_city_guest"), kb_cities(chat_id))
            return
        if data == "back_to_meal":
            answer_cb(cb_id)
            st = get_state(chat_id)
            if st:
                set_state(chat_id, "select_meal", st["data"])
                from bot_app.keyboards import kb_meal_choice
                send(chat_id, t(chat_id, "select_meal"), kb_meal_choice(chat_id))
            return

        # Трапеза
        if data.startswith("meal:"):
            answer_cb(cb_id)
            guest.handle_meal_choice(chat_id, data)
            return

        # Количество гостей
        if data.startswith("guests:"):
            answer_cb(cb_id)
            st = get_state(chat_id)
            if st and st["step"] == "add_meal_guests":
                booking.handle_add_meal_guests(chat_id, int(data.split(":")[1]))
            else:
                guest.handle_guest_guests_cb(chat_id, int(data.split(":")[1]))
            return

        # Пропуск комментария
        if data == "skip_comment":
            answer_cb(cb_id)
            st = get_state(chat_id)
            if st:
                if st["step"] == "add_meal_comment":
                    booking.handle_add_meal_comment(chat_id, "")
                else:
                    guest.handle_guest_comment(chat_id, "")
            return

        # История
        if data == "past":
            answer_cb(cb_id)
            qs = Booking.objects.filter(tg_id=chat_id).filter(
                status__in=["confirmed", "cancelled", "declined"]
            ).order_by("-date")[:10]
            if not qs:
                send(chat_id, t(chat_id, "no_past_bookings"),
                     {"inline_keyboard": [[{"text": t(chat_id, "menu"), "callback_data": "menu"}]]})
            else:
                lang = get_lang(chat_id)
                parts = [t(chat_id, "past_bookings")]
                status_map = {"confirmed": "✅", "cancelled": "❌", "declined": "🚫"}
                for b in qs:
                    who = b.assigned_family.name if b.assigned_family else "—"
                    meal_text = t_lang(lang, "meal_fri") if b.meal == "fri_evening" else t_lang(lang, "meal_sat")
                    parts.append(f"• {status_map.get(b.status, '')} {b.date:%d.%m} ({meal_text}) — {html.escape(who)}")
                send(chat_id, "\n".join(parts),
                     {"inline_keyboard": [[{"text": t(chat_id, "menu"), "callback_data": "menu"}]]})
            return

        # Мои записи
        if data == "my":
            answer_cb(cb_id)
            qs = Booking.objects.filter(tg_id=chat_id).exclude(
                status__in=["declined", "cancelled", "expired"]
            ).order_by("date")[:5]
            if not qs:
                send(chat_id, t(chat_id, "no_active_bookings"),
                     {"inline_keyboard": [[{"text": t(chat_id, "menu"), "callback_data": "menu"}]]})
            else:
                text, kb = kb_my_bookings(chat_id, qs)
                send(chat_id, text, kb)
            return

        # Записаться
        if data == "book":
            answer_cb(cb_id)
            booking.handle_book_click(chat_id, message_id)
            return

        # Дозапись на вторую трапезу
        if data.startswith("add_meal:"):
            answer_cb(cb_id)
            meal_mode = data.split(":")[1]
            booking.handle_add_meal_click(chat_id, meal_mode)
            return

        # Записаться на следующую неделю
        if data == "book_next_week":
            answer_cb(cb_id)
            booking.handle_book_next_week(chat_id, message_id)
            return

        # Отмена старых
        if data == "cancel_old":
            answer_cb(cb_id)
            old = cancel_all_old_bookings(chat_id)
            for b in old:
                if b.assigned_family and b.assigned_family.telegram_chat_id:
                    fam_lang = getattr(b.assigned_family, "language", "ru") or "ru"
                    notify_family_about_guest_cancel(
                        b.assigned_family.telegram_chat_id, b, fam_lang
                    )
            send(chat_id, t(chat_id, "old_bookings_cancelled"), kb_main_menu(chat_id))
            return

        # ✅ ПРИНЯТЬ ГОСТЯ
        if data.startswith("claim:"):
            bid = int(data.split(":")[1])
            pressing_family = Family.objects.filter(telegram_chat_id=user_id).first() if user_id else None
            if not pressing_family:
                answer_cb(cb_id, t(chat_id, "not_registered_family"))
                return

            booking_obj, status = claim_booking(bid, pressing_family)
            if status == "not_found":
                answer_cb(cb_id, t(chat_id, "request_not_found"))
                return
            if status == "already_accepted":
                answer_cb(cb_id, t(chat_id, "already_accepted", booking_obj.assigned_family.name))
                return

            answer_cb(cb_id, t(chat_id, "you_accepted", booking_obj.name))

            # ✅ Уведомляем гостя на ЕГО ЯЗЫКЕ
            guest_lang = get_lang(booking_obj.tg_id)
            notify_guest(booking_obj, pressing_family, guest_lang)

            # ✅ Сообщение в группе на языке семьи
            fam_lang = pressing_family.language or "ru"
            meal_text_fam = t_lang(fam_lang, "meal_fri") if booking_obj.meal == "fri_evening" else t_lang(fam_lang, "meal_sat")
            cancel_text = t_lang(fam_lang, "cancel_booking", booking_obj.date.strftime("%d.%m"), meal_text_fam)
            kb = {"inline_keyboard": [[
                {"text": "❌ " + cancel_text, "callback_data": f"cancel_family:{booking_obj.pk}"}
            ]]}
            new_text = (msg.get("text") or "") + "\n" + t_lang(fam_lang, "accepted_by_family_group", html.escape(pressing_family.name))
            edit_msg(chat_id, message_id, new_text, kb)
            return

        # ❌ ОТМЕНА ГОСТЕМ
        if data.startswith("cancel_guest:"):
            bid = int(data.split(":")[1])
            booking_obj, status = cancel_booking_by_guest(bid, chat_id)

            if status == "already_cancelled" or not booking_obj:
                answer_cb(cb_id, t(chat_id, "booking_already_cancelled"))
                return

            if status == "deadline_passed":
                answer_cb(cb_id, t(chat_id, "cancel_deadline_passed_guest"))
                return

            answer_cb(cb_id, t(chat_id, "booking_cancelled"))

            if status == "confirmed" and booking_obj.assigned_family \
               and booking_obj.assigned_family.telegram_chat_id:
                fam_lang = getattr(booking_obj.assigned_family, "language", "ru") or "ru"
                notify_family_about_guest_cancel(
                    booking_obj.assigned_family.telegram_chat_id,
                    booking_obj, fam_lang
                )

            # ✅ Сообщение на ЯЗЫКЕ ГОСТЯ + кнопка меню
            if msg.get("text"):
                edit_msg(
                    chat_id, message_id,
                    (msg.get("text") or "") + "\n" + t(chat_id, "cancelled_by_you"),
                    kb_menu_only(chat_id)
                )
            return

        # ❌ ОТМЕНА СЕМЬЁЙ
        if data.startswith("cancel_family:"):
            bid = int(data.split(":")[1])
            pressing_family = Family.objects.filter(telegram_chat_id=user_id).first() if user_id else None

            booking_obj, status = cancel_booking_by_family(bid, pressing_family)

            if status == "no_access" or not booking_obj:
                answer_cb(cb_id, t(chat_id, "no_access"))
                return
            if status == "already_cancelled":
                answer_cb(cb_id, t(chat_id, "booking_already_cancelled"))
                return
            if status == "deadline_passed":
                answer_cb(cb_id, t(chat_id, "cancel_deadline_passed_family"))
                return

            fam_name = pressing_family.name
            answer_cb(cb_id, t(chat_id, "you_cancelled_family"))

            # ✅ Язык семьи
            fam_lang = pressing_family.language or "ru"

            if status == "cancelled_past":
                if booking_obj.tg_id:
                    guest_lang = get_lang(booking_obj.tg_id)
                    meal_text = t_lang(guest_lang, "meal_fri") if booking_obj.meal == "fri_evening" else t_lang(guest_lang, "meal_sat")
                    send(booking_obj.tg_id,
                         t_lang(guest_lang, "family_cancelled",
                                booking_obj.date.strftime("%d.%m"), meal_text))
                if msg.get("text"):
                    edit_msg(chat_id, message_id,
                             (msg.get("text") or "") + "\n" + t_lang(fam_lang, "cancelled_by_you"),
                             kb_menu_only(chat_id))
                return

            if status == "requeued":
                if booking_obj.tg_id:
                    guest_lang = get_lang(booking_obj.tg_id)
                    notify_guest_cancelled_by_family(
                        booking_obj, fam_name, guest_lang, is_requeue=True
                    )
                send_booking_to_group(booking_obj, is_requeue=True)
                if msg.get("text"):
                    edit_msg(
                        chat_id, message_id,
                        (msg.get("text") or "") + "\n" + t_lang(fam_lang, "booking_requeued_by_family", html.escape(fam_name)),
                        kb_menu_only(chat_id)
                    )
                return

        answer_cb(cb_id)

    except Exception as exc:
        log.exception("Callback error: %s", exc)
        answer_cb(cb_id, "Ошибка")


def main():
    if not TOKEN:
        log.error("BOT_TOKEN не задан")
        sys.exit(1)

    log.info("Старт бота (TZ: %s)", timezone.get_current_timezone())
    offset = 0
    from bot_app.api import SESSION
    from bot_app.config import API_BASE
    while True:
        try:
            r = SESSION.get(
                f"{API_BASE}getUpdates",
                params={"offset": offset, "timeout": 25,
                        "allowed_updates": '["message","callback_query"]'},
                timeout=40
            )
            data = r.json()
        except Exception as exc:
            log.warning("poll: %s", exc)
            time.sleep(3)
            continue

        if not data.get("ok"):
            desc = str(data.get("description", ""))
            log.warning("getUpdates: %s", desc)
            if "Conflict" in desc:
                log.error("Другой экземпляр бота запущен. Убейте его.")
                sys.exit(1)
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
                log.exception("Update error %s", update.get("update_id"))


if __name__ == "__main__":
    main()