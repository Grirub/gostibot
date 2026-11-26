from django.db import models
from django.utils import timezone

SLOT_CHOICES = [(15, "15 минут"), (30, "30 минут"), (60, "1 час"), (90, "1,5 часа"), (120, "2 часа")]
WEEKDAY_NAMES = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
MEAL_CHOICES = [
    ("fri_evening", "Пятница — вечерняя трапеза"),
    ("sat_day", "Суббота — дневная трапеза"),
]
MEAL_CONFIG = {
    "fri_evening": {"weekday": 4, "time": (18, 0), "short": "вечерняя трапеза"},
    "sat_day": {"weekday": 5, "time": (13, 0), "short": "дневная трапеза"},
}
STATUSES = [
    ("pending", "Ожидает подтверждения"),
    ("confirmed", "Подтверждена"),
    ("declined", "Отклонена"),
    ("cancelled", "Отменена гостем"),
]
ACTIVE_STATUSES = ("pending", "confirmed")

JEWISH_ORIGIN_CHOICES = [
    ("maternal", "Еврей по материнской линии"),
    ("paternal", "Еврей по отцовской линии"),
    ("ger", "Я гер (прошедший или в процессе)"),
    ("unknown", "Не знаю, что ответить"),
]
GENDER_CHOICES = [
    ("male", "Мужчина"),
    ("female", "Женщина"),
]
NOTIFY_MODE_CHOICES = [
    ("group", "В общую группу"),
    ("all", "Всем семьям сразу"),
]


class Settings(models.Model):
    """Единственная запись с настройками бота (pk всегда = 1)."""
    title = models.CharField("Название", max_length=100, default="Запись в гости")
    greeting = models.TextField(
        "Приветствие",
        default="Здравствуйте! Здесь можно записаться в гости — на пятницу, вечернюю трапезу, "
                "или на субботу, дневную. Выберите день, а я передам заявку хозяевам.",
    )
    address = models.CharField("Адрес / место", max_length=200, blank=True, default="")
    contact = models.CharField("Контакт для вопросов", max_length=200, blank=True, default="")
    work_start = models.PositiveSmallIntegerField("Приём с (час)", default=10)
    work_end = models.PositiveSmallIntegerField("Приём до (час)", default=20)
    slot_minutes = models.PositiveSmallIntegerField("Длина интервала", default=60, choices=SLOT_CHOICES)
    days_ahead = models.PositiveSmallIntegerField(
        "Показывать дней вперёд", default=14,
        help_text="Сколько календарных дней вперёд открыта запись"
    )
    allowed_weekdays = models.CharField(
        "Дни недели для записи", max_length=20, default="4,5",
        help_text="Номера дней через запятую, 0 — понедельник, 6 — воскресенье"
    )
    max_guests = models.PositiveSmallIntegerField("Максимум гостей в заявке", default=6)
    ask_guests = models.BooleanField("Спрашивать число гостей", default=True)
    ask_phone = models.BooleanField("Спрашивать телефон", default=True)
    owner_chat_ids = models.CharField(
        "Telegram ID владельцев", max_length=300, blank=True, default="",
        help_text="Через запятую. Владельцу бот присылает заявки и команды /today, /upcoming"
    )
    notify_owner = models.BooleanField("Уведомлять владельцев о новых заявках", default=True)
    notification_group_id = models.BigIntegerField(
        "ID группы для уведомлений", null=True, blank=True,
        help_text="Числовой ID группы (начинается с -100...). Нужно, если выбран режим «В общую группу»."
    )
    notify_mode = models.CharField(
        "Режим уведомлений", max_length=10, choices=NOTIFY_MODE_CHOICES, default="group",
        help_text="Куда отправлять новые заявки: в общую группу или всем семьям сразу."
    )

    class Meta:
        verbose_name = "Настройки бота"
        verbose_name_plural = "Настройки бота"

    def save(self, *args, **kwargs):
        self.pk = 1
        self.work_start = max(0, min(23, self.work_start))
        self.work_end = max(1, min(24, self.work_end))
        if self.work_end <= self.work_start:
            self.work_end = min(24, self.work_start + 1)
        self.days_ahead = max(1, min(60, self.days_ahead))
        self.max_guests = max(1, min(50, self.max_guests))
        super().save(*args, **kwargs)

    def __str__(self):
        return "Настройки бота"

    @classmethod
    def load(cls):
        obj = cls.objects.filter(pk=1).first()
        return obj or cls.objects.create(pk=1)

    @property
    def allowed_weekdays_set(self):
        days = set()
        for part in (self.allowed_weekdays or "").replace(";", ",").split(","):
            part = part.strip()
            if part.isdigit() and 0 <= int(part) <= 6:
                days.add(int(part))
        return days or set(range(7))

    def owner_ids(self):
        out = []
        for part in (self.owner_chat_ids or "").replace(";", ",").split(","):
            part = part.strip()
            if part.lstrip("-").isdigit():
                out.append(int(part))
        return out


class City(models.Model):
    """Город, в котором находятся районы и семьи."""
    name = models.CharField("Название города", max_length=100, unique=True)
    order = models.PositiveSmallIntegerField("Порядок в списке", default=0)

    class Meta:
        verbose_name = "Город"
        verbose_name_plural = "Города"
        ordering = ["order", "name"]

    def __str__(self):
        return self.name


class District(models.Model):
    """Район, привязанный к конкретному городу."""
    name = models.CharField("Название района", max_length=100)
    city = models.ForeignKey(
        City, verbose_name="Город", on_delete=models.CASCADE,
        related_name="districts", null=True, blank=True,
        help_text="Город, к которому относится этот район"
    )
    order = models.PositiveSmallIntegerField("Порядок в списке", default=0)

    class Meta:
        verbose_name = "Район"
        verbose_name_plural = "Районы"
        ordering = ["city", "order", "name"]
        unique_together = ("name", "city")

    def __str__(self):
        return f"{self.name} ({self.city.name})" if self.city else self.name


class GuestProfile(models.Model):
    """Профиль гостя: согласие на ПД и данные анкеты."""
    tg_id = models.BigIntegerField("Telegram ID", unique=True, db_index=True)
    tg_username = models.CharField("Telegram username", max_length=64, blank=True)
    consented_at = models.DateTimeField("Дата согласия на ПД", null=True, blank=True)

    photo = models.ImageField("Фото гостя", upload_to="guest_photos/", null=True, blank=True)
    name = models.CharField("Имя", max_length=100, blank=True)
    phone = models.CharField("Телефон", max_length=40, blank=True)
    jewish_origin = models.CharField(
        "Происхождение", max_length=20, choices=JEWISH_ORIGIN_CHOICES, default="unknown"
    )
    gender = models.CharField("Пол", max_length=10, choices=GENDER_CHOICES, default="unknown")

    class Meta:
        verbose_name = "Профиль гостя"
        verbose_name_plural = "Профили гостей"

    def __str__(self):
        return f"{self.name or 'Без имени'} (ID: {self.tg_id})"

    @property
    def has_consented(self):
        return self.consented_at is not None


class Family(models.Model):
    """Семья, к которой идёт гость (выбор в боте)."""
    name = models.CharField("Семья", max_length=100, unique=True)
    seats = models.PositiveSmallIntegerField(
        "Мест за трапезу", default=10,
        help_text="Сколько гостей эта семья принимает за одну трапезу"
    )
    order = models.PositiveSmallIntegerField("Порядок в списке", default=0)
    is_active = models.BooleanField("Показывать в боте", default=True)

    district = models.ForeignKey(
        District, verbose_name="Район", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="families",
        help_text="Район, к которому относится эта семья"
    )

    photo = models.ImageField(
        "Фото семьи", upload_to="family_photos/", blank=True, null=True,
        help_text="Необязательно. Будет показано гостю при выборе семьи."
    )
    active_fri_evening = models.BooleanField(
        "Активна в пятницу (вечерняя)", default=True,
        help_text="Если выключено — семья не будет видна при выборе пятницы"
    )
    active_sat_day = models.BooleanField(
        "Активна в субботу (дневная)", default=True,
        help_text="Если выключено — семья не будет видна при выборе субботы"
    )
    telegram_chat_id = models.BigIntegerField(
        "Telegram ID получателя", null=True, blank=True,
        help_text="Числовой ID. Узнать командой /id в боте."
    )

    class Meta:
        verbose_name = "Семья"
        verbose_name_plural = "Семьи"
        ordering = ["order", "name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.seats = max(1, min(500, self.seats))
        super().save(*args, **kwargs)

    def is_active_on_meal(self, meal):
        if not self.is_active:
            return False
        if meal == "fri_evening":
            return self.active_fri_evening
        if meal == "sat_day":
            return self.active_sat_day
        return True


class Booking(models.Model):
    date = models.DateField("Дата")
    family = models.ForeignKey(
        Family, verbose_name="Семья", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="bookings"
    )
    meal = models.CharField(
        "Трапеза", max_length=20, choices=MEAL_CHOICES, blank=True, default="", db_index=True
    )
    time = models.TimeField("Время", null=True, blank=True)

    name = models.CharField("Имя", max_length=100)
    phone = models.CharField("Телефон", max_length=40, blank=True)
    guests = models.PositiveSmallIntegerField("Гостей", default=1)
    comment = models.CharField("Комментарий", max_length=300, blank=True)
    tg_id = models.BigIntegerField("Telegram ID", null=True, blank=True, db_index=True)
    tg_username = models.CharField("Telegram", max_length=64, blank=True)

    photo = models.ImageField(
        "Фото гостя", upload_to="guest_photos/", null=True, blank=True,
        help_text="Обязательно для новых заявок. Загружается через бота."
    )
    jewish_origin = models.CharField(
        "Происхождение", max_length=20, choices=JEWISH_ORIGIN_CHOICES, default="unknown",
        help_text="Обязательно для новых заявок."
    )
    gender = models.CharField(
        "Пол", max_length=10, choices=GENDER_CHOICES, default="unknown",
        help_text="Обязательно для новых заявок."
    )

    assigned_family = models.ForeignKey(
        Family, verbose_name="Записан в семью", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="assigned_bookings",
        help_text="Семья, которая подтвердила заявку (кнопкой в группе/чате)."
    )

    status = models.CharField(
        "Статус", max_length=12, choices=STATUSES, default="pending", db_index=True
    )
    created_at = models.DateTimeField("Создана", auto_now_add=True)
    decided_at = models.DateTimeField("Обработана", null=True, blank=True)

    class Meta:
        verbose_name = "Запись"
        verbose_name_plural = "Записи"
        ordering = ["date", "time", "id"]

    def __str__(self):
        who = self.assigned_family.name if self.assigned_family else (self.family.name if self.family else "")
        return f"{self.date:%d.%m.%Y} {self.meal_label} — {who} ({self.name})"

    @property
    def meal_label(self):
        cfg = MEAL_CONFIG.get(self.meal)
        if cfg:
            return cfg["short"].capitalize()
        return self.time.strftime("%H:%M") if self.time else "без времени"

    @property
    def is_active(self):
        return self.status in ACTIVE_STATUSES