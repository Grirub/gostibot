"""Telegram API через сессию requests."""
import json
import logging
import requests
from .config import API_BASE, FILES_BASE, PROXIES

log = logging.getLogger("gostibot")

SESSION = requests.Session()
if PROXIES:
    SESSION.proxies.update(PROXIES)


def api(method, **params):
    try:
        r = SESSION.post(f"{API_BASE}{method}", json=params, timeout=60)
        return r.json()
    except requests.RequestException as exc:
        log.error("API %s failed: %s", method, exc)
        return {"ok": False, "description": str(exc)}


def download_file(file_path):
    try:
        r = SESSION.get(f"{FILES_BASE}{file_path}", timeout=60)
        r.raise_for_status()
        return r.content
    except requests.RequestException as exc:
        log.error("Download failed %s: %s", file_path, exc)
        return None


def send(chat_id, text, kb=None):
    params = {
        "chat_id": chat_id, "text": text,
        "parse_mode": "HTML", "disable_web_page_preview": True
    }
    if kb is not None:
        params["reply_markup"] = kb
    return api("sendMessage", **params)


def send_photo_msg(chat_id, photo_path, caption, kb=None):
    params = {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"}
    if kb is not None:
        params["reply_markup"] = json.dumps(kb, ensure_ascii=False)
    try:
        with open(photo_path, "rb") as f:
            r = SESSION.post(
                f"{API_BASE}sendPhoto",
                data=params, files={"photo": f}, timeout=60
            )
            res = r.json()
            if not res.get("ok"):
                log.warning("sendPhoto error: %s", res.get("description"))
            return res
    except Exception as exc:
        log.error("sendPhoto exception: %s", exc)
        return {"ok": False, "description": str(exc)}


def edit_msg(chat_id, message_id, text, kb=None):
    params = {
        "chat_id": chat_id, "message_id": message_id,
        "text": text, "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    if kb is not None:
        params["reply_markup"] = kb
    res = api("editMessageText", **params)
    if not res.get("ok") and "not modified" not in str(res.get("description", "")):
        send(chat_id, text, kb)
    return res


def answer_cb(cb_id, text=None):
    params = {"callback_query_id": cb_id, "show_alert": False}
    if text:
        params["text"] = text
    api("answerCallbackQuery", **params)