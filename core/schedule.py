"""Ближайшие трапезы для записи — общий расчёт для бота и админки."""

from datetime import timedelta

from django.db.models import Sum
from django.utils import timezone

from .models import ACTIVE_STATUSES, MEAL_CHOICES, MEAL_CONFIG, Booking, Settings

WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
WEEKDAYS_FULL = [
    "понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье",
]
MONTHS = [
    "янв", "фев", "мар", "апр", "май", "июн",
    "июл", "авг", "сен", "окт", "ноя", "дек",
]


def get_settings():
    return Settings.load()


def meal_title(day, meal):
    """«Пятница, 6 ноя — вечерняя трапеза»."""
    cfg = MEAL_CONFIG[meal]
    return (
        f"{WEEKDAYS_FULL[day.weekday()].capitalize()}, {day.day} {MONTHS[day.month - 1]}"
        f" — {cfg['short']}"
    )


def meal_label(day, meal):
    """Короткая подпись для кнопки: «Пт 6 ноя · вечерняя трапеза · 2»."""
    return f"{WEEKDAYS[day.weekday()]} {day.day} {MONTHS[day.month - 1]} · {MEAL_CONFIG[meal]['short']}"


def meal_used(day, meal):
    return Booking.objects.filter(
        date=day, meal=meal, status__in=ACTIVE_STATUSES
    ).count()


def family_used(day, meal, family_id):
    """Сколько мест у семьи на эту трапезу уже занято (сумма гостей активных заявок)."""
    total = Booking.objects.filter(
        date=day, meal=meal, family_id=family_id, status__in=ACTIVE_STATUSES
    ).aggregate(total=Sum("guests"))["total"]
    return total or 0


def family_free(day, meal, family):
    """Сколько мест у семьи осталось на эту трапезу."""
    return max(0, family.seats - family_used(day, meal, family.pk))


def places_word(n):
    n = abs(int(n)) % 100
    if 11 <= n <= 14:
        return "мест"
    n %= 10
    if n == 1:
        return "место"
    if 2 <= n <= 4:
        return "места"
    return "мест"


def places_text(n):
    return f"{n} {places_word(n)}"


def meal_passed(day, meal):
    """Сегодняшняя трапеза, время которой уже прошло."""
    now = timezone.localtime()
    hh, mm = MEAL_CONFIG[meal]["time"]
    return day == now.date() and (now.hour, now.minute) >= (hh, mm)


def meal_options(s=None):
    """[(дата, ключ трапезы)] по возрастанию даты. Число заявок не ограничено."""
    s = s or get_settings()
    today = timezone.localdate()
    out = []
    for shift in range(s.days_ahead):
        day = today + timedelta(days=shift)
        for meal, _ in MEAL_CHOICES:
            if MEAL_CONFIG[meal]["weekday"] != day.weekday():
                continue
            if meal_passed(day, meal):
                continue
            out.append((day, meal))
    out.sort(key=lambda item: item[0])
    return out


def meals_text():
    return "пятница (вечерняя трапеза) и суббота (дневная трапеза)"


def family_name(family_id):
    """Название семьи по id (для экрана подтверждения)."""
    from .models import Family

    if not family_id:
        return "—"
    fam = Family.objects.filter(pk=family_id).first()
    return fam.name if fam else "—"


def families_text():
    from .models import Family

    return ", ".join(f.name for f in Family.objects.filter(is_active=True))
