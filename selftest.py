"""Оффлайн-проверка сценариев бота без Telegram: подменяем Bot API на заглушку.

Работает на КОПИИ базы (/tmp/selftest.sqlite3), рабочую базу не трогает.
"""
import os
import shutil
import sys
from datetime import date

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

for suffix in ("", "-wal", "-shm"):
    dst = "/tmp/selftest.sqlite3" + suffix
    if os.path.exists(dst):
        os.remove(dst)
shutil.copy(os.path.join(BASE, "db.sqlite3"), "/tmp/selftest.sqlite3")
for suffix in ("-wal", "-shm"):
    src = os.path.join(BASE, "db.sqlite3" + suffix)
    if os.path.exists(src):
        shutil.copy(src, "/tmp/selftest.sqlite3" + suffix)

os.environ["BOT_TOKEN"] = "test:token"
os.environ["DJANGO_SETTINGS_MODULE"] = "selftest_settings"

import bot  # noqa: E402
from core import schedule  # noqa: E402
from core.models import MEAL_CONFIG, Booking, Family, Settings  # noqa: E402

CALLS = []


def fake_api(method, **params):
    CALLS.append((method, params))
    return {"ok": True, "result": {"message_id": 1}}


bot.api = fake_api

s = Settings.load()
guests_before = [b for b in Booking.objects.all()]
print("0) настройки:", s.days_ahead, "дн. вперёд | владелец:", s.owner_chat_ids)
print("   заявки в базе до теста:", [(b.date.strftime('%d.%m'), b.meal, b.status) for b in guests_before])

s.owner_chat_ids = "999"
s.save()

GUEST = 555


def last_text():
    for method, params in reversed(CALLS):
        if method in ("sendMessage", "editMessageText"):
            return params.get("text", ""), params.get("reply_markup")
    return "", None


def msg(text=None, contact=None):
    m = {"chat": {"id": GUEST, "type": "private"}, "from": {"id": GUEST, "username": "guest_test"}}
    if text:
        m["text"] = text
    if contact:
        m["contact"] = {"phone_number": contact}
    return m


def cb(data):
    return {
        "id": "cb1",
        "data": data,
        "from": {"id": GUEST, "username": "guest_test"},
        "message": {"id": 10, "chat": {"id": GUEST, "type": "private"}},
    }


print("1) /start")
bot.handle_message(msg("/start"))
text, kb = last_text()
assert "Записаться" in str(kb)
assert "пятница" in text and "суббота" in text, text
print("   меню:", [t for t in text.splitlines() if "Запись открыта" in t][0])

print("2) выбор трапезы — только два варианта")
bot.handle_callback(cb("book"))
text, kb = last_text()
opts = [b for row in kb["inline_keyboard"] for b in row if b["callback_data"].startswith("m:")]
for b in opts:
    d = date.fromisoformat(b["callback_data"].split(":")[1].split("|")[0])
    meal = b["callback_data"].split("|")[1]
    assert meal in MEAL_CONFIG, meal
    assert d.weekday() == MEAL_CONFIG[meal]["weekday"], (d, meal)
print("   кнопки:", [b["text"] for b in opts])
assert all(":" not in b["text"] for b in opts), "в подписи не должно быть времени"

options = schedule.meal_options(s)
day, meal = options[0]
print("   расчёт: ", schedule.meal_title(day, meal), "| заявок уже:", schedule.meal_used(day, meal))

print("3) выбор варианта -> выбор семьи")
bot.handle_callback(cb(f"m:{day.isoformat()}|{meal}"))
assert bot.get_state(GUEST)["step"] == "family", bot.get_state(GUEST)
text, kb = last_text()
fams = [b for row in kb["inline_keyboard"] for b in row if b["callback_data"].startswith("f:")]
print("   семьи в кнопках:", [b["text"] for b in fams])
assert [b["text"].split(" · ")[0] for b in fams] == [f.name for f in Family.objects.filter(is_active=True)]
family = Family.objects.filter(is_active=True).first()
bot.handle_message(msg("бла-бла"))          # текстом на шаге семьи — только подсказка
assert bot.get_state(GUEST)["step"] == "family"
bot.handle_callback(cb(f"f:{family.pk}"))
assert bot.get_state(GUEST)["step"] == "name", bot.get_state(GUEST)
assert bot.get_state(GUEST)["data"]["family"] == family.pk
bot.handle_message(msg("Иван Петров"))
assert bot.get_state(GUEST)["step"] == "phone"
bot.handle_message(msg(contact="+79990001122"))
assert bot.get_state(GUEST)["step"] == "guests"
bot.handle_callback(cb("g:2"))

print("4) экран подтверждения — без времени, но с семьёй")
text, _ = last_text()
assert ":" not in text.split("Проверьте заявку:\n")[1].split("👤")[0], text
print("   ", [t for t in text.splitlines() if t.startswith("🍽")][0])
assert f"🏡 {family.name}" in text, text

print("5) отправка заявки")
bot.handle_callback(cb("ok"))
b = Booking.objects.order_by("-pk").first()
assert b.meal == meal, (b.meal, meal)
assert b.family_id == family.pk, (b.family_id, family.pk)
assert b.date == day
assert b.name == "Иван Петров" and b.phone == "+79990001122" and b.guests == 2
assert b.status == "pending"
print("   заявка:", b, "| time:", b.time, "| статус:", b.status)
owner_msgs = [p for m, p in CALLS if m == "sendMessage" and p.get("chat_id") == 999]
assert owner_msgs and "трапеза" in owner_msgs[-1]["text"]
assert family.name in owner_msgs[-1]["text"]
print("   владельцу:", owner_msgs[-1]["text"].splitlines()[2])

print("6) подтверждение хозяином")
bot.handle_callback({
    "id": "cb2", "data": f"a:{b.pk}",
    "from": {"id": 999, "username": "host"},
    "message": {"id": 11, "chat": {"id": 999, "type": "private"}},
})
b.refresh_from_db()
assert b.status == "confirmed"
guest_msgs = [p for m, p in CALLS if m == "sendMessage" and p.get("chat_id") == GUEST]
assert "подтверждена" in guest_msgs[-1]["text"].lower()
print("   статус:", b.status)

print("7) «мои записи» и отмена")
bot.handle_callback(cb("my"))
text, _ = last_text()
assert "трапеза" in text
line = [t for t in text.splitlines() if t.startswith(f"№{b.pk}")][0]
assert family.name in line, line
print("   ", line)
bot.handle_callback(cb(f"c:{b.pk}"))
b.refresh_from_db()
assert b.status == "cancelled"
print("   отменено")

print("8) мест на трапезу не ограничено")
for extra in range(25):
    Booking.objects.create(date=day, time=None, meal=meal, name=f"Гость {extra}", guests=1,
                           tg_id=900 + extra, status="confirmed")
used = schedule.meal_used(day, meal)
opts_after = [(d, m) for d, m in schedule.meal_options(s)]
print("   заявок на трапезу:", used, "| вариант всё ещё в списке:", (day, meal) in opts_after)
assert used >= 25
assert (day, meal) in opts_after

print("9) мест на семью — свой лимит у каждой")
Booking.objects.filter(date=day, meal=meal).delete()   # чистая трапеза в копии базы
fam_a = family
fam_b = Family.objects.filter(is_active=True).exclude(pk=fam_a.pk).first()
fam_b.seats = 5
fam_b.save()
left_a = schedule.family_free(day, meal, fam_a)
print("   у", fam_a.name, "мест:", fam_a.seats, "| свободно:", left_a)
assert left_a == fam_a.seats
Booking.objects.create(date=day, meal=meal, family=fam_a, name="Заполнил", guests=left_a,
                       status="confirmed", tg_id=1)
print("   после заполнения осталось:", schedule.family_free(day, meal, fam_a))
assert schedule.family_free(day, meal, fam_a) == 0
bot.handle_callback(cb(f"m:{day.isoformat()}|{meal}"))
text, kb = last_text()
labels = [b["text"] for row in kb["inline_keyboard"] for b in row
          if b["callback_data"].startswith("f:")]
print("   кнопки семей:", labels)
assert not any(t.startswith(fam_a.name) for t in labels)
assert any(t.startswith(fam_b.name) for t in labels)

Booking.objects.create(date=day, meal=meal, family=fam_b, name="Заполнил-2",
                       guests=fam_b.seats - 3, status="confirmed", tg_id=2)
left_b = schedule.family_free(day, meal, fam_b)
print("   у", fam_b.name, "лимит:", fam_b.seats, "| осталось мест:", left_b)
assert left_b == 3
bot.handle_callback(cb(f"f:{fam_b.pk}"))
assert bot.get_state(GUEST)["step"] == "name"
bot.handle_message(msg("Тест Лимит"))
bot.handle_message(msg(contact="+79990000000"))
text, kb = last_text()
nums = [b["text"] for row in kb["inline_keyboard"] for b in row
        if b["callback_data"].startswith("g:")]
print("   кнопки числа гостей:", nums, "| текст:", text.splitlines()[-1])
assert nums == [str(i) for i in range(1, left_b + 1)], nums
bot.handle_callback(cb("g:3"))
bot.get_state(GUEST)["data"]["guests"] = 5
bot.get_state(GUEST)["step"] = "confirm"
bot.handle_callback(cb("ok"))
assert Booking.objects.filter(name="Тест Лимит").count() == 0
print("   сверх лимита не записалось, шаг:", bot.get_state(GUEST)["step"])
assert bot.get_state(GUEST)["step"] == "guests"
bot.clear_state(GUEST)

for f in Family.objects.filter(is_active=True):
    left = schedule.family_free(day, meal, f)
    if left:
        Booking.objects.create(date=day, meal=meal, family=f, name="Заполнил-3",
                               guests=left, status="confirmed", tg_id=3)
bot.handle_callback(cb(f"m:{day.isoformat()}|{meal}"))
text, kb = last_text()
print("   все семьи заняты:", text.splitlines()[0])
assert "не осталось" in text, text
assert any(b["callback_data"].startswith("m:") for row in kb["inline_keyboard"] for b in row)
print("   бот вернул к выбору дня")
bot.clear_state(GUEST)

print("10) мусор в callback не ломает бота")
bot.handle_callback(cb("m:2026-11-06|bogus_meal"))
bot.handle_callback(cb("m:не-дата|sat_day"))
bot.handle_callback(cb("t:2026-11-06|15:00"))
print("   ок, состояния нет:", bot.get_state(GUEST))

print("11) чужой не подтверждает")
bot.handle_callback({
    "id": "cb3", "data": f"a:{b.pk}",
    "from": {"id": 5, "username": "stranger"},
    "message": {"id": 12, "chat": {"id": 5, "type": "private"}},
})
print("   ", [p for m, p in CALLS if m == "answerCallbackQuery"][-1].get("text"))

print("\nВСЁ ОК — рабочая база не тронута")
