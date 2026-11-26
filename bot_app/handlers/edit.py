"""Редактирование анкеты гостя."""
import logging
import os
import re
import uuid
from django.core.files import File
from core.models import GuestProfile, Booking
from ..api import api, send, edit_msg, download_file
from ..translations import t
from ..states import set_state, clear_state
from ..keyboards import kb_edit_profile, kb_phone
from ..config import BASE_DIR

log = logging.getLogger("gostibot")


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
    send(chat_id, t(chat_id, "send_phone"), kb_phone(chat_id))


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
    if not phone or not re.match(r"^\+?[\d\s\-()]{7,20}$", phone):
        send(chat_id, t(chat_id, "phone_invalid"))
        return
    profile = GuestProfile.objects.get(tg_id=chat_id)
    profile.phone = phone
    profile.save()
    Booking.objects.filter(tg_id=chat_id, status__in=["pending", "confirmed"]).update(phone=phone)
    clear_state(chat_id)
    api("sendMessage", chat_id=chat_id, text="📞", reply_markup={"remove_keyboard": True})
    send(chat_id, t(chat_id, "phone_changed", phone), kb_edit_profile(chat_id))


def handle_edit_photo_input(chat_id, message):
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

        profile = GuestProfile.objects.get(tg_id=chat_id)
        if profile.photo:
            try:
                profile.photo.delete(save=False)
            except Exception:
                pass
        with open(temp_path, "rb") as f:
            profile.photo.save(f"guest_{chat_id}.jpg", File(f), save=True)

        Booking.objects.filter(tg_id=chat_id, status__in=["pending", "confirmed"]).update(photo=profile.photo)
        clear_state(chat_id)
        send(chat_id, t(chat_id, "photo_changed"), kb_edit_profile(chat_id))
    except Exception as exc:
        log.error("handle_edit_photo_input: %s", exc)
        send(chat_id, t(chat_id, "photo_save_failed"))
    finally:
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except OSError:
            pass


def route(chat_id, data, message_id=None):
    if data == "edit":
        show_edit_menu(chat_id, message_id)
    elif data == "edit:name":
        handle_edit_name_start(chat_id, message_id)
    elif data == "edit:phone":
        handle_edit_phone_start(chat_id, message_id)
    elif data == "edit:photo":
        handle_edit_photo_start(chat_id, message_id)