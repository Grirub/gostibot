"""Все клавиатуры бота."""
from django.utils import timezone
from datetime import timedelta
from core.models import City, District, Settings, Booking
from .translations import t, get_lang
from .states import get_state


def can_guest_cancel(booking):
    if booking.status not in ("pending", "confirmed"):
        return False
    deadline = _get_friday_10am(booking.date)
    return timezone.now() < deadline


def can_family_cancel(booking):
    if booking.status != "confirmed":
        return False
    deadline = _get_friday_1pm(booking.date)
    return timezone.now() < deadline


def _get_friday_10am(booking_date):
    days_to_friday = 4 - booking_date.weekday()
    if days_to_friday < 0:
        days_to_friday += 7
    friday = booking_date + timedelta(days=days_to_friday)
    return timezone.make_aware(
        timezone.datetime(friday.year, friday.month, friday.day, 10, 0)
    )


def _get_friday_1pm(booking_date):
    days_to_friday = 4 - booking_date.weekday()
    if days_to_friday < 0:
        days_to_friday += 7
    friday = booking_date + timedelta(days=days_to_friday)
    return timezone.make_aware(
        timezone.datetime(friday.year, friday.month, friday.day, 13, 0)
    )


def is_booking_deadline_passed():
    now = timezone.now()
    weekday = now.weekday()
    if weekday > 3:
        return True
    if weekday == 3 and now.hour >= 21:
        return True
    return False


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


def kb_meal_choice(chat_id, district_id=0, next_week=False):
    nw = "1" if next_week else "0"
    return {"inline_keyboard": [
        [{"text": t(chat_id, "only_fri"), "callback_data": f"meal:fri_evening:{district_id}:{nw}"}],
        [{"text": t(chat_id, "only_sat"), "callback_data": f"meal:sat_day:{district_id}:{nw}"}],
        [{"text": t(chat_id, "both_meals"), "callback_data": f"meal:both:{district_id}:{nw}"}]
    ]}


def kb_main_menu(chat_id):
    return {"inline_keyboard": [
        [{"text": t(chat_id, "book"), "callback_data": "book"}],
        [{"text": t(chat_id, "my_bookings"), "callback_data": "my"}],
        [{"text": t(chat_id, "edit_profile"), "callback_data": "edit"}],
    ]}


def kb_edit_profile(chat_id):
    return {"inline_keyboard": [
        [{"text": t(chat_id, "edit_name"), "callback_data": "edit:name"}],
        [{"text": t(chat_id, "edit_phone"), "callback_data": "edit:phone"}],
        [{"text": t(chat_id, "edit_photo"), "callback_data": "edit:photo"}],
        [{"text": t(chat_id, "back"), "callback_data": "menu"}]
    ]}


def kb_cities(chat_id):
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
    lang = get_lang(chat_id)
    districts = District.objects.filter(city_id=city_id).order_by("order", "name")
    rows = [[{"text": d.get_name(lang), "callback_data": f"dist:{d.pk}"}] for d in districts]
    rows.append([{"text": t(chat_id, "back"), "callback_data": "cities"}])
    return {"inline_keyboard": rows}


def kb_phone(chat_id):
    return {
        "keyboard": [[{"text": t(chat_id, "send_phone_button"), "request_contact": True}]],
        "resize_keyboard": True, "one_time_keyboard": True
    }


def kb_skip_comment(chat_id):
    return {"inline_keyboard": [[{"text": t(chat_id, "skip"), "callback_data": "skip_comment"}]]}


def kb_guests(chat_id, max_n):
    rows = [[{"text": str(i), "callback_data": f"guests:{i}"}] for i in range(1, max_n + 1)]
    return {"inline_keyboard": rows}


def kb_my_bookings(chat_id, bookings):
    lang = get_lang(chat_id)
    parts = [t(chat_id, "your_bookings")]
    kb_rows = []
    for b in bookings:
        who = b.assigned_family.name if b.assigned_family else t(chat_id, "waiting_confirmation")
        meal_text = t(chat_id, "meal_fri") if b.meal == "fri_evening" else t(chat_id, "meal_sat")
        parts.append(f"• {b.date:%d.%m} ({meal_text}) — {who}")
        if b.status in ("pending", "confirmed") and can_guest_cancel(b):
            kb_rows.append([{
                "text": t(chat_id, "cancel_booking", b.date.strftime("%d.%m"), meal_text),
                "callback_data": f"cancel_guest:{b.pk}"
            }])
    kb_rows.append([{"text": t(chat_id, "menu"), "callback_data": "menu"}])
    return "\n".join(parts), {"inline_keyboard": kb_rows}


def kb_menu_only(chat_id):
    return {"inline_keyboard": [[{"text": t(chat_id, "menu"), "callback_data": "menu"}]]}