"""Загрузка переводов из JSON."""
import json
import logging
from pathlib import Path
from core.models import GuestProfile

log = logging.getLogger("gostibot")
LOCALES_DIR = Path(__file__).resolve().parent.parent / "locales"

_TRANSLATIONS = {}


def _load_all():
    global _TRANSLATIONS
    if not LOCALES_DIR.exists():
        log.warning("locales/ не найдена: %s", LOCALES_DIR)
        return
    for lang_file in LOCALES_DIR.glob("*.json"):
        lang = lang_file.stem
        try:
            with lang_file.open(encoding="utf-8") as f:
                _TRANSLATIONS[lang] = json.load(f)
            log.info("Загружена локаль: %s", lang)
        except Exception as exc:
            log.error("Ошибка загрузки %s: %s", lang, exc)


_load_all()


def get_lang(chat_id):
    try:
        profile = GuestProfile.objects.filter(tg_id=chat_id).first()
        return (profile.language if profile and profile.language else "ru")
    except Exception as exc:
        log.error("get_lang error: %s", exc)
        return "ru"


def t(chat_id, key, *args):
    """Перевод для пользователя по chat_id (на ЕГО языке)."""
    lang = get_lang(chat_id)
    return t_lang(lang, key, *args)


def t_lang(lang, key, *args):
    """Перевод по явно указанному языку."""
    text = _TRANSLATIONS.get(lang, _TRANSLATIONS.get("ru", {})).get(key, key)
    if args:
        try:
            return text.format(*args)
        except (IndexError, KeyError):
            return text
    return text