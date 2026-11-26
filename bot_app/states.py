"""FSM только в БД."""
import json
import logging
from core.models import GuestProfile

log = logging.getLogger("gostibot")


def get_state(chat_id):
    try:
        p = GuestProfile.objects.filter(tg_id=chat_id).first()
        if p and p.state_json:
            return json.loads(p.state_json)
    except Exception as exc:
        log.error("get_state error: %s", exc)
    return None


def set_state(chat_id, step, data=None):
    state = {"step": step, "data": data or {}}
    try:
        GuestProfile.objects.filter(tg_id=chat_id).update(
            state_json=json.dumps(state, ensure_ascii=False)
        )
    except Exception as exc:
        log.error("set_state error: %s", exc)


def clear_state(chat_id):
    try:
        GuestProfile.objects.filter(tg_id=chat_id).update(state_json="")
    except Exception as exc:
        log.error("clear_state error: %s", exc)