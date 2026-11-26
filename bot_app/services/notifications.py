"""Мультиязычные уведомления."""
import html
import logging
import os
import json
from ..api import send, send_photo_msg, SESSION
from ..translations import t_lang, get_lang
from ..config import ORIGIN_MAP, GENDER_MAP, WEEKDAYS_RU, API_BASE

log = logging.getLogger("gostibot")


def _esc(value):
    return html.escape(str(value or ""), quote=False)


def _weekday_localized(booking, lang):
    wd = booking.date.weekday()
    if lang == "ru":
        return ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][wd]
    elif lang == "he":
        return ["ב׳", "ג׳", "ד׳", "ה׳", "ו׳", "ש׳", "א׳"][wd]
    return ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][wd]


def _build_booking_text(booking, profile, lang, is_additional=False, is_requeue=False):
    try:
        district = booking.district
        city = booking.city or (district.city if district else None)
    except Exception:
        city, district = None, None

    city_name = city.get_name(lang) if city else "—"
    district_name = district.get_name(lang) if district else "—"
    meal_text = t_lang(lang, "meal_fri") if booking.meal == "fri_evening" else t_lang(lang, "meal_sat")

    if is_requeue:
        title = t_lang(lang, "request_again_available")
    elif is_additional:
        title = t_lang(lang, "additional_request")
    else:
        title = t_lang(lang, "new_request")

    origin_text = ORIGIN_MAP.get(profile.jewish_origin, "")
    gender_text = GENDER_MAP.get(profile.gender, "")
    weekday = _weekday_localized(booking, lang)

    # ✅ Username гостя
    username_str = f"@{_esc(profile.tg_username)}" if profile.tg_username else "—"

    return (
        f"{title}\n"
        f"🏙 {_esc(city_name)} | 🗺 {_esc(district_name)}\n"
        f"🍽 {meal_text}\n"
        f"📅 {booking.date.strftime('%d.%m.%Y')} ({weekday})\n"
        f"👤 {_esc(profile.name)} | 🆔 {username_str} | 👥 {booking.guests}\n"
        f"📞 {_esc(profile.phone)}\n"
        f"📜 {origin_text} | ⚧️ {gender_text}\n"
        f"💬 {_esc(booking.comment) if booking.comment else '—'}\n"
        f"🆔 <code>{booking.tg_id}</code>"
    )


def _build_claim_keyboard(booking, lang):
    meal_text = t_lang(lang, "meal_fri") if booking.meal == "fri_evening" else t_lang(lang, "meal_sat")
    accept_text = t_lang(lang, "accept_guest", meal_text)
    return {
        "inline_keyboard": [[
            {"text": accept_text, "callback_data": f"claim:{booking.pk}"}
        ]]
    }


def _send_photo_to_group(group_id, photo_path, caption, kb):
    params = {
        "chat_id": group_id,
        "caption": caption,
        "parse_mode": "HTML",
        "reply_markup": json.dumps(kb, ensure_ascii=False),
    }
    try:
        with open(photo_path, "rb") as f:
            r = SESSION.post(
                f"{API_BASE}sendPhoto",
                data=params, files={"photo": f}, timeout=60
            )
            return r.json()
    except Exception as exc:
        log.warning("sendPhoto failed: %s", exc)
        return {"ok": False}


def send_booking_to_group(booking, is_additional=False, is_requeue=False):
    """Отправить заявку в группу уведомлений на ЯЗЫКЕ ГРУППЫ."""
    try:
        from core.models import Settings, GuestProfile
        settings = Settings.load()
        group_id = settings.notification_group_id
        if not group_id:
            log.warning("notification_group_id не задан")
            return False

        profile = GuestProfile.objects.filter(tg_id=booking.tg_id).first()
        if not profile:
            log.warning("Профиль не найден для %s", booking.tg_id)
            return False

        group_lang = getattr(settings, "language", "ru") or "ru"

        text = _build_booking_text(
            booking, profile, group_lang,
            is_additional=is_additional, is_requeue=is_requeue
        )
        kb = _build_claim_keyboard(booking, group_lang)

        photo_path = None
        if profile.photo and os.path.exists(profile.photo.path):
            photo_path = profile.photo.path

        if photo_path:
            res = _send_photo_to_group(group_id, photo_path, text, kb)
            if res.get("ok"):
                return True
            log.warning("Фото не ушло: %s", res.get("description"))

        res = send(group_id, text, kb)
        return res.get("ok", False)
    except Exception as exc:
        log.exception("send_booking_to_group: %s", exc)
        return False


def notify_guest(booking, family, lang):
    """Уведомить гостя на ЕГО ЯЗЫКЕ."""
    meal_text = t_lang(lang, "meal_fri") if booking.meal == "fri_evening" else t_lang(lang, "meal_sat")
    text = t_lang(
        lang, "successfully_booked",
        family.name,
        booking.date.strftime("%d.%m.%Y"),
        meal_text,
    )
    send(
        booking.tg_id, text,
        {"inline_keyboard": [[{"text": t_lang(lang, "my_bookings"), "callback_data": "my"}]]}
    )


def notify_guest_cancelled_by_family(booking, family_name, lang, is_requeue=False):
    if is_requeue:
        text = t_lang(lang, "family_cancelled_requeue", family_name)
    else:
        meal_text = t_lang(lang, "meal_fri") if booking.meal == "fri_evening" else t_lang(lang, "meal_sat")
        text = t_lang(lang, "family_cancelled",
                      booking.date.strftime("%d.%m"), meal_text)
    send(booking.tg_id, text,
         {"inline_keyboard": [[{"text": t_lang(lang, "my_bookings"), "callback_data": "my"}]]})


def notify_family_about_guest_cancel(family_chat_id, booking, fam_lang):
    meal_text = t_lang(fam_lang, "meal_fri") if booking.meal == "fri_evening" else t_lang(fam_lang, "meal_sat")
    send(family_chat_id,
         t_lang(fam_lang, "guest_cancelled",
                booking.name, booking.date.strftime("%d.%m"), meal_text))