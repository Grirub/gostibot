"""Обработчики гостя."""
import logging
import os
import re
import uuid
from django.core.files import File
from django.utils import timezone
from core.models import GuestProfile, City, District, Settings, Blacklist
from ..api import api, send, download_file
from ..translations import t, get_lang
from ..states import get_state, set_state, clear_state
from ..keyboards import (
    kb_languages, kb_consent, kb_role, kb_jewish_origin, kb_gender,
    kb_phone, kb_cities, kb_districts, kb_meal_choice, kb_main_menu,
    kb_skip_comment, kb_guests
)
from ..config import BASE_DIR, ORIGIN_MAP

log = logging.getLogger("gostibot")


def start_flow(chat_id, message_id=None, username=None):
    """
    Начало флоу гостя.
    ✅ Сохраняем username из Telegram в профиль.
    """
    if Blacklist.is_blocked(chat_id):
        send(chat_id, t(chat_id, "blocked"))
        return
    profile, _ = GuestProfile.objects.get_or_create(tg_id=chat_id)
    # ✅ Сохраняем username, если он есть и отличается от текущего
    if username and profile.tg_username != username:
        profile.tg_username = username
        profile.save(update_fields=["tg_username"])
        log.info("Username сохранён для %s: @%s", chat_id, username)
    set_state(chat_id, "select_language")
    send(chat_id, t(chat_id, "select_language_first"), kb_languages())


def show_menu(chat_id, message_id=None):
    from ..api import edit_msg
    s = Settings.load()
    lang = get_lang(chat_id)
    text = f"<b>{s.get_title(lang)}</b>\n{s.get_greeting(lang)}"
    if s.get_address(lang):
        text += f"\n📍 {s.get_address(lang)}"
    if s.get_contact(lang):
        text += f"\n☎️ {s.get_contact(lang)}"
    if message_id:
        edit_msg(chat_id, message_id, text, kb_main_menu(chat_id))
    else:
        send(chat_id, text, kb_main_menu(chat_id))


def handle_set_language(chat_id, lang):
    from ..translations import _TRANSLATIONS
    if lang not in _TRANSLATIONS:
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


def handle_role(chat_id, role):
    st = get_state(chat_id) or {"data": {}}
    st["data"]["role"] = role
    if role == "family":
        set_state(chat_id, "family_consent", st["data"])
        send(chat_id, t(chat_id, "consent_kashrut"), kb_consent(chat_id))
    else:
        set_state(chat_id, "guest_photo", st["data"])
        send(chat_id, t(chat_id, "send_photo"))


def handle_guest_photo(chat_id, message):
    if not message.get("photo"):
        send(chat_id, t(chat_id, "send_photo_only"))
        return
    photo = message["photo"][-1]
    file_info = api("getFile", file_id=photo["file_id"])
    if not file_info.get("ok"):
        send(chat_id, t(chat_id, "photo_save_failed"))
        return

    file_path = file_info["result"]["file_path"]
    content = download_file(file_path)
    if not content:
        send(chat_id, t(chat_id, "photo_save_failed"))
        return

    if len(content) > 5 * 1024 * 1024:
        send(chat_id, t(chat_id, "photo_too_large"))
        return

    ext = file_path.split(".")[-1] if "." in file_path else "jpg"
    temp_path = os.path.join(BASE_DIR, f"temp_{uuid.uuid4()}.{ext}")

    try:
        with open(temp_path, "wb") as f:
            f.write(content)
        st = get_state(chat_id) or {"data": {}}
        st["data"]["photo_path"] = temp_path
        set_state(chat_id, "guest_name", st["data"])
        send(chat_id, t(chat_id, "enter_name"))
    except Exception as exc:
        log.error("handle_guest_photo: %s", exc)
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
        send(chat_id, t(chat_id, "photo_save_failed"))


def handle_guest_name(chat_id, text):
    name = " ".join(text.split())[:100]
    if len(name) < 2:
        send(chat_id, t(chat_id, "short_name"))
        return
    st = get_state(chat_id) or {"data": {}}
    st["data"]["name"] = name
    set_state(chat_id, "guest_phone", st["data"])
    send(chat_id, t(chat_id, "send_phone"), kb_phone(chat_id))


def handle_guest_phone(chat_id, message):
    phone = message.get("contact", {}).get("phone_number") or message.get("text", "")[:40]
    if not phone or not re.match(r"^\+?[\d\s\-()]{7,20}$", phone):
        send(chat_id, t(chat_id, "phone_invalid"))
        return
    st = get_state(chat_id) or {"data": {}}
    st["data"]["phone"] = phone
    api("sendMessage", chat_id=chat_id, text="📞", reply_markup={"remove_keyboard": True})
    set_state(chat_id, "guest_origin", st["data"])
    send(chat_id, t(chat_id, "select_origin"), kb_jewish_origin(chat_id))


def handle_guest_origin(chat_id, data):
    st = get_state(chat_id)
    if not st or st["step"] != "guest_origin":
        return
    value = data.split(":")[1]
    if value not in ORIGIN_MAP:
        return
    st["data"]["jewish_origin"] = value
    set_state(chat_id, "guest_gender", st["data"])
    send(chat_id, t(chat_id, "select_gender"), kb_gender(chat_id))


def handle_guest_gender(chat_id, data):
    st = get_state(chat_id)
    if not st or st["step"] != "guest_gender":
        return
    st["data"]["gender"] = data.split(":")[1]

    profile = GuestProfile.objects.get(tg_id=chat_id)
    profile.name = st["data"]["name"]
    profile.phone = st["data"]["phone"]
    profile.jewish_origin = st["data"]["jewish_origin"]
    profile.gender = st["data"]["gender"]

    if st["data"].get("photo_path") and os.path.exists(st["data"]["photo_path"]):
        try:
            with open(st["data"]["photo_path"], "rb") as f:
                profile.photo.save(f"guest_{chat_id}.jpg", File(f), save=True)
        finally:
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
    set_state(chat_id, "select_city", st["data"])
    send(chat_id, t(chat_id, "select_city_guest"), kb_cities(chat_id))


def handle_select_city(chat_id, city_id):
    st = get_state(chat_id)
    if not st:
        return
    st["data"]["city_id"] = city_id
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
    try:
        d = District.objects.get(pk=district_id)
        GuestProfile.objects.filter(tg_id=chat_id).update(city=d.city, district=d)
    except District.DoesNotExist:
        pass
    next_week = bool(st["data"].get("next_week"))
    set_state(chat_id, "select_meal", st["data"])
    send(chat_id, t(chat_id, "select_meal"), kb_meal_choice(chat_id, district_id, next_week))


def handle_meal_choice(chat_id, data):
    parts = data.split(":")
    if len(parts) < 4:
        return
    meal_mode = parts[1]
    try:
        district_id = int(parts[2])
    except ValueError:
        district_id = 0
    next_week = parts[3] == "1"

    if not district_id:
        profile = GuestProfile.objects.filter(tg_id=chat_id).first()
        if profile and profile.name:
            set_state(chat_id, "select_city", {
                "name": profile.name, "phone": profile.phone,
                "meal_mode": meal_mode, "next_week": next_week, "redo": True
            })
            send(chat_id, t(chat_id, "select_city_guest"), kb_cities(chat_id))
        return

    st = get_state(chat_id)
    if not st or st["step"] != "select_meal":
        return
    st["data"]["meal_mode"] = meal_mode
    st["data"]["district_id"] = district_id
    st["data"]["next_week"] = next_week

    s = Settings.load()
    if s.ask_guests:
        set_state(chat_id, "guest_guests", st["data"])
        send(chat_id, t(chat_id, "ask_guests_count"), kb_guests(chat_id, s.max_guests))
    else:
        set_state(chat_id, "guest_comment", st["data"])
        send(chat_id, t(chat_id, "enter_comment"), kb_skip_comment(chat_id))


def handle_guest_guests_cb(chat_id, n):
    st = get_state(chat_id) or {"data": {}}
    st["data"]["guests"] = n
    set_state(chat_id, "guest_comment", st["data"])
    send(chat_id, t(chat_id, "enter_comment"), kb_skip_comment(chat_id))


def handle_guest_comment(chat_id, text):
    st = get_state(chat_id) or {"data": {}}
    st["data"]["comment"] = text.strip()[:500]
    from .booking import create_bookings_and_notify
    create_bookings_and_notify(chat_id, st["data"])