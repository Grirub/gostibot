"""Обработчики записи с учётом дедлайнов."""
import logging
from core.models import GuestProfile, Booking, District, Settings
from ..api import send
from ..translations import t, get_lang
from ..states import get_state, set_state, clear_state
from ..keyboards import (
    kb_main_menu, kb_cities, kb_meal_choice, kb_skip_comment, kb_guests,
    is_booking_deadline_passed
)
from ..services.booking_service import (
    create_booking, get_active_meals, cancel_all_old_bookings
)
from ..services.notifications import send_booking_to_group

log = logging.getLogger("gostibot")


def handle_book_click(chat_id, message_id=None):
    # Проверка дедлайна: до четверга 21:00
    if is_booking_deadline_passed():
        kb = {"inline_keyboard": [
            [{"text": t(chat_id, "book_next_week"), "callback_data": "book_next_week"}],
            [{"text": t(chat_id, "my_bookings"), "callback_data": "my"}],
            [{"text": t(chat_id, "menu"), "callback_data": "menu"}],
        ]}
        send(chat_id, t(chat_id, "booking_deadline_passed"), kb)
        return

    profile = GuestProfile.objects.filter(tg_id=chat_id).first()
    if not profile or not profile.name or not profile.phone \
       or not profile.jewish_origin or not profile.gender:
        from .guest import start_flow
        start_flow(chat_id, message_id)
        return

    active = get_active_meals(chat_id)
    has_fri = "fri_evening" in active
    has_sat = "sat_day" in active

    if has_fri and has_sat:
        kb = {"inline_keyboard": [
            [{"text": t(chat_id, "book_next_week"), "callback_data": "book_next_week"}],
            [{"text": t(chat_id, "my_bookings"), "callback_data": "my"}],
            [{"text": t(chat_id, "cancel_old_bookings"), "callback_data": "cancel_old"}],
            [{"text": t(chat_id, "menu"), "callback_data": "menu"}],
        ]}
        send(chat_id, t(chat_id, "already_has_both_next"), kb)
        return

    if has_fri or has_sat:
        existing_text = t(chat_id, "meal_fri") if has_fri else t(chat_id, "meal_sat")
        missing_mode = "sat_day" if has_fri else "fri_evening"
        missing_text = t(chat_id, "meal_sat") if has_fri else t(chat_id, "meal_fri")
        kb = {"inline_keyboard": [
            [{"text": t(chat_id, "add_second_meal", missing_text),
              "callback_data": f"add_meal:{missing_mode}"}],
            [{"text": t(chat_id, "my_bookings"), "callback_data": "my"}],
            [{"text": t(chat_id, "menu"), "callback_data": "menu"}],
        ]}
        send(chat_id, t(chat_id, "already_has_second_meal", existing_text, missing_text), kb)
        return

    _start_full_booking(chat_id, profile)


def _start_full_booking(chat_id, profile):
    if profile.city_id and profile.district_id:
        set_state(chat_id, "select_meal", {
            "district_id": profile.district_id,
            "meal_mode": "both", "next_week": False,
            "name": profile.name, "phone": profile.phone,
        })
        send(chat_id, t(chat_id, "select_meal"),
             kb_meal_choice(chat_id, profile.district_id, False))
    else:
        set_state(chat_id, "select_city", {
            "name": profile.name, "phone": profile.phone,
            "meal_mode": "both", "redo": True
        })
        send(chat_id, t(chat_id, "select_city_guest"), kb_cities(chat_id))


def handle_book_next_week(chat_id, message_id=None):
    profile = GuestProfile.objects.filter(tg_id=chat_id).first()
    if not profile or not profile.name:
        from .guest import start_flow
        start_flow(chat_id, message_id)
        return

    active = get_active_meals(chat_id)
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


# ============================================================================
# ДОЗАПИСЬ НА ВТОРУЮ ТРАПЕЗУ
# ============================================================================

def handle_add_meal_click(chat_id, meal_mode):
    if is_booking_deadline_passed():
        send(chat_id, t(chat_id, "booking_deadline_passed"))
        return
    profile = GuestProfile.objects.filter(tg_id=chat_id).first()
    if not profile or not profile.district_id:
        send(chat_id, t(chat_id, "no_access"))
        return
    set_state(chat_id, "add_meal_comment", {
        "meal_mode": meal_mode,
        "district_id": profile.district_id,
        "next_week": False,
    })
    send(chat_id, t(chat_id, "enter_comment"), kb_skip_comment(chat_id))


def handle_add_meal_comment(chat_id, text):
    st = get_state(chat_id)
    if not st or st["step"] != "add_meal_comment":
        return
    st["data"]["comment"] = text.strip()[:500]
    s = Settings.load()
    if s.ask_guests:
        set_state(chat_id, "add_meal_guests", st["data"])
        send(chat_id, t(chat_id, "ask_guests_count"), kb_guests(chat_id, s.max_guests))
    else:
        st["data"]["guests"] = 1
        _finalize_add_meal(chat_id, st["data"])


def handle_add_meal_guests(chat_id, n):
    st = get_state(chat_id)
    if not st or st["step"] != "add_meal_guests":
        return
    st["data"]["guests"] = n
    _finalize_add_meal(chat_id, st["data"])


def _finalize_add_meal(chat_id, data):
    clear_state(chat_id)
    booking = create_booking(chat_id, data, data["meal_mode"])
    if not booking:
        send(chat_id, t(chat_id, "district_not_found"))
        return

    meal_text = t(chat_id, "meal_fri") if data["meal_mode"] == "fri_evening" else t(chat_id, "meal_sat")
    send(chat_id, t(chat_id, "requests_sent", "—", "—", meal_text),
         {"inline_keyboard": [
             [{"text": t(chat_id, "my_bookings"), "callback_data": "my"}],
             [{"text": t(chat_id, "menu"), "callback_data": "menu"}],
         ]})
    send_booking_to_group(booking, is_additional=True)


# ============================================================================
# Полное создание бронирований
# ============================================================================

def create_bookings_and_notify(chat_id, data):
    profile = GuestProfile.objects.get(tg_id=chat_id)
    if not data.get("district_id"):
        set_state(chat_id, "select_city", data)
        send(chat_id, t(chat_id, "select_city_guest"), kb_cities(chat_id))
        return

    try:
        district = District.objects.get(pk=data["district_id"])
        city = district.city
    except District.DoesNotExist:
        send(chat_id, t(chat_id, "district_not_found"))
        clear_state(chat_id)
        return

    meal_mode = data.get("meal_mode", "both")
    next_week = bool(data.get("next_week"))
    guests = int(data.get("guests") or 1)
    comment = data.get("comment") or ""

    if next_week:
        has_fri, has_sat = False, False
    else:
        active = get_active_meals(chat_id)
        has_fri = "fri_evening" in active
        has_sat = "sat_day" in active

    bookings_created = []
    if meal_mode in ("fri_evening", "both") and not has_fri:
        b = create_booking(chat_id, {**data, "guests": guests, "comment": comment}, "fri_evening")
        if b:
            bookings_created.append(b)
    if meal_mode in ("sat_day", "both") and not has_sat:
        b = create_booking(chat_id, {**data, "guests": guests, "comment": comment}, "sat_day")
        if b:
            bookings_created.append(b)

    if not bookings_created:
        kb = {"inline_keyboard": [
            [{"text": t(chat_id, "my_bookings"), "callback_data": "my"}],
            [{"text": t(chat_id, "cancel_old_bookings"), "callback_data": "cancel_old"}],
            [{"text": t(chat_id, "menu"), "callback_data": "menu"}],
        ]}
        send(chat_id, t(chat_id, "already_has_both"), kb)
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
                    city.get_name(lang), district.get_name(lang), meal_text),
         {"inline_keyboard": [
             [{"text": t(chat_id, "my_bookings"), "callback_data": "my"}],
             [{"text": t(chat_id, "menu"), "callback_data": "menu"}]
         ]})

    for b in bookings_created:
        send_booking_to_group(b, is_additional=False)