"""Обработчики семьи."""
import logging
import html
from django.utils import timezone
from core.models import Family, Settings
from ..api import send
from ..translations import t
from ..states import get_state, set_state, clear_state

log = logging.getLogger("gostibot")


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
        name=name, is_active=True,
        telegram_chat_id=chat_id,
        consented_at=timezone.now(),
    )
    clear_state(chat_id)
    s = Settings.load()
    group_link = s.notification_group_link or ""
    if group_link:
        send(chat_id, t(chat_id, "family_registered_with_group",
                        html.escape(name), html.escape(group_link)))
    else:
        send(chat_id, t(chat_id, "family_registered_with_group",
                        html.escape(name), "(ссылка не настроена)"))