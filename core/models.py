from django.db import models
from django.utils import timezone


class City(models.Model):
    name = models.CharField("Название (русский)", max_length=100)
    name_en = models.CharField("Название (English)", max_length=100, blank=True, default="")
    name_he = models.CharField("Название (עברית)", max_length=100, blank=True, default="")
    order = models.IntegerField("Порядок сортировки", default=0)

    class Meta:
        verbose_name = "Город"
        verbose_name_plural = "Города"
        ordering = ("order", "name")

    def __str__(self):
        return self.name

    def get_name(self, lang="ru"):
        if lang == "en" and self.name_en:
            return self.name_en
        elif lang == "he" and self.name_he:
            return self.name_he
        return self.name


class District(models.Model):
    city = models.ForeignKey(
        City, on_delete=models.CASCADE, related_name="districts", verbose_name="Город"
    )
    name = models.CharField("Название (русский)", max_length=100)
    name_en = models.CharField("Название (English)", max_length=100, blank=True, default="")
    name_he = models.CharField("Название (עברית)", max_length=100, blank=True, default="")
    order = models.IntegerField("Порядок сортировки", default=0)

    class Meta:
        verbose_name = "Район"
        verbose_name_plural = "Районы"
        ordering = ("city", "order", "name")

    def __str__(self):
        return f"{self.city.name} — {self.name}"

    def get_name(self, lang="ru"):
        if lang == "en" and self.name_en:
            return self.name_en
        elif lang == "he" and self.name_he:
            return self.name_he
        return self.name


# ============================================================================
# ЛОКАЛИЗАЦИЯ ТРАПЕЗ (для отображения в админке и боте)
# ============================================================================
MEAL_LABELS = {
    "ru": {
        "fri_evening": "Вечерняя пятница",
        "sat_day": "Дневная суббота",
    },
    "en": {
        "fri_evening": "Friday evening",
        "sat_day": "Saturday day",
    },
    "he": {
        "fri_evening": "ערב שישי",
        "sat_day": "יום שבת",
    },
}

# Оставляем MEAL_CONFIG для обратной совместимости (используется в боте для времени)
MEAL_CONFIG = {
    "fri_evening": {"label": "Вечерняя пятница", "time": "18:00"},
    "sat_day": {"label": "Дневная суббота", "time": "13:00"},
}


class Family(models.Model):
    name = models.CharField("Название семьи", max_length=100, unique=True)
    district = models.ForeignKey(
        District, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="families", verbose_name="Район (опционально)"
    )
    photo = models.ImageField("Фото семьи", upload_to="families/", blank=True, null=True)
    seats = models.PositiveIntegerField("Количество мест", default=4)
    order = models.IntegerField("Порядок сортировки", default=0)
    is_active = models.BooleanField("Активна", default=True)
    active_fri_evening = models.BooleanField("Принимает в пятницу вечером", default=True)
    active_sat_day = models.BooleanField("Принимает в субботу днём", default=True)
    telegram_chat_id = models.BigIntegerField("Telegram Chat ID", null=True, blank=True)
    consented_at = models.DateTimeField("Дата согласия на кашрут", null=True, blank=True)
    language = models.CharField("Язык уведомлений", max_length=2, default="ru")
    created_at = models.DateTimeField("Создана", auto_now_add=True)

    class Meta:
        verbose_name = "Семья"
        verbose_name_plural = "Семьи"
        ordering = ("order", "name")

    def __str__(self):
        return self.name

    def is_active_on_meal(self, meal):
        if meal == "fri_evening":
            return self.active_fri_evening
        elif meal == "sat_day":
            return self.active_sat_day
        return self.is_active

    def available_seats_for_date(self, date, meal):
        booked = Booking.objects.filter(
            assigned_family=self, date=date, meal=meal, status="confirmed"
        ).count()
        return max(0, self.seats - booked)


class GuestProfile(models.Model):
    ORIGIN_CHOICES = [
        ("maternal", "Еврей по материнской линии / Jewish on maternal line / יהודי מצד האם"),
        ("paternal", "Еврей по отцовской линии / Jewish on paternal line / יהודי מצד האב"),
        ("ger", "Я гер / I am a ger / אני גר"),
        ("unknown", "Не знаю / I don't know / אני לא יודע"),
    ]
    GENDER_CHOICES = [
        ("male", "Мужчина / Male / זכר"),
        ("female", "Женщина / Female / נקבה"),
    ]
    LANGUAGE_CHOICES = [
        ("ru", "Русский"),
        ("en", "English"),
        ("he", "עברית"),
    ]

    tg_id = models.BigIntegerField("Telegram ID", unique=True)
    tg_username = models.CharField("Telegram username", max_length=100, blank=True)
    name = models.CharField("Имя", max_length=100, blank=True)
    phone = models.CharField("Телефон", max_length=40, blank=True)
    photo = models.ImageField("Фото", upload_to="guests/", blank=True, null=True)
    jewish_origin = models.CharField("Еврейское происхождение", max_length=20, choices=ORIGIN_CHOICES, blank=True)
    gender = models.CharField("Пол", max_length=10, choices=GENDER_CHOICES, blank=True)
    consented_at = models.DateTimeField("Дата согласия на обработку ПДн", null=True, blank=True)
    language = models.CharField("Язык интерфейса", max_length=10, default="ru", choices=LANGUAGE_CHOICES)
    city = models.ForeignKey(City, on_delete=models.SET_NULL, null=True, blank=True, related_name="+", verbose_name="Город")
    district = models.ForeignKey(District, on_delete=models.SET_NULL, null=True, blank=True, related_name="+", verbose_name="Район")
    state_json = models.TextField("Состояние диалога (JSON)", blank=True, default="")
    created_at = models.DateTimeField("Создан", auto_now_add=True)

    class Meta:
        verbose_name = "Профиль гостя"
        verbose_name_plural = "Профили гостей"

    def __str__(self):
        return f"{self.name or 'Без имени'} (TG: {self.tg_id})"


class Blacklist(models.Model):
    tg_id = models.BigIntegerField("Telegram ID", unique=True)
    reason = models.TextField("Причина блокировки", blank=True)
    blocked_at = models.DateTimeField("Дата блокировки", auto_now_add=True)
    blocked_by = models.CharField("Заблокировал", max_length=100, blank=True)

    class Meta:
        verbose_name = "Чёрный список"
        verbose_name_plural = "Чёрный список"
        ordering = ("-blocked_at",)

    def __str__(self):
        return f"TG: {self.tg_id} — {self.reason[:50] if self.reason else 'без причины'}"

    @classmethod
    def is_blocked(cls, tg_id):
        return cls.objects.filter(tg_id=tg_id).exists()


class Booking(models.Model):
    STATUS_CHOICES = [
        ("pending", "Ожидает подтверждения / Pending / ממתין"),
        ("confirmed", "Подтверждена / Confirmed / אושר"),
        ("declined", "Отклонена / Declined / נדחה"),
        ("cancelled", "Отменена / Cancelled / בוטל"),
        ("expired", "Просрочена / Expired / פג תוקף"),
    ]

    date = models.DateField("Дата")
    meal = models.CharField(
        "Трапеза",
        max_length=20,
        choices=[(k, v) for k, v in MEAL_CONFIG.items()],
    )
    time = models.TimeField("Время")
    family = models.ForeignKey(Family, on_delete=models.SET_NULL, null=True, blank=True, related_name="bookings", verbose_name="Семья (выбранная)")
    assigned_family = models.ForeignKey(Family, on_delete=models.SET_NULL, null=True, blank=True, related_name="assigned_bookings", verbose_name="Принявшая семья")
    name = models.CharField("Имя гостя", max_length=100)
    phone = models.CharField("Телефон", max_length=40)
    guests = models.PositiveIntegerField("Количество гостей", default=1)
    tg_id = models.BigIntegerField("Telegram ID гостя", null=True, blank=True)
    tg_username = models.CharField("Telegram username гостя", max_length=100, blank=True)
    photo = models.ImageField("Фото гостя", upload_to="bookings/", blank=True, null=True)
    jewish_origin = models.CharField("Еврейское происхождение", max_length=20, blank=True)
    gender = models.CharField("Пол", max_length=10, blank=True)
    city = models.ForeignKey(City, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Город гостя")
    district = models.ForeignKey(District, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Район гостя")
    comment = models.TextField("Комментарий", blank=True)
    status = models.CharField("Статус", max_length=20, choices=STATUS_CHOICES, default="pending")
    rating = models.PositiveSmallIntegerField("Оценка (1–5)", null=True, blank=True)
    reminder_sent = models.BooleanField("Напоминание отправлено", default=False)
    created_at = models.DateTimeField("Создана", auto_now_add=True)
    decided_at = models.DateTimeField("Дата решения", null=True, blank=True)

    class Meta:
        verbose_name = "Заявка"
        verbose_name_plural = "Заявки"
        ordering = ("date", "time")

    def __str__(self):
        return f"{self.date:%d.%m.%Y} {self.meal_label} — {self.name}"

    @property
    def meal_label(self):
        """Локализованное название трапезы (по умолчанию русский)."""
        return MEAL_LABELS.get("ru", {}).get(self.meal, self.meal)

    def meal_label_lang(self, lang="ru"):
        return MEAL_LABELS.get(lang, MEAL_LABELS["ru"]).get(self.meal, self.meal)


class Settings(models.Model):
    NOTIFY_MODE_CHOICES = [
        ("all", "Все"),
        ("important", "Важные"),
    ]

    title = models.CharField("Название бота (RU)", max_length=200, default="Запись в гости")
    title_en = models.CharField("Название бота (EN)", max_length=200, blank=True, default="")
    title_he = models.CharField("Название бота (HE)", max_length=200, blank=True, default="")
    greeting = models.TextField("Приветствие (RU)", default="Добро пожаловать!")
    greeting_en = models.TextField("Приветствие (EN)", blank=True, default="")
    greeting_he = models.TextField("Приветствие (HE)", blank=True, default="")
    address = models.CharField("Адрес (RU)", max_length=300, blank=True)
    address_en = models.CharField("Адрес (EN)", max_length=300, blank=True, default="")
    address_he = models.CharField("Адрес (HE)", max_length=300, blank=True, default="")
    contact = models.CharField("Контакт (RU)", max_length=200, blank=True)
    contact_en = models.CharField("Контакт (EN)", max_length=200, blank=True, default="")
    contact_he = models.CharField("Контакт (HE)", max_length=200, blank=True, default="")
    days_ahead = models.PositiveIntegerField("На сколько дней вперёд записывать", default=7)
    ask_guests = models.BooleanField("Спрашивать количество гостей", default=False)
    max_guests = models.PositiveIntegerField("Максимум гостей", default=4)
    ask_phone = models.BooleanField("Спрашивать телефон", default=True)
    notify_owner = models.BooleanField("Уведомлять владельца", default=True)
    owner_chat_ids = models.TextField("Chat ID владельцев (через запятую)", blank=True)
    notify_mode = models.CharField("Режим уведомлений", max_length=20, default="all", choices=NOTIFY_MODE_CHOICES)
    notification_group_id = models.BigIntegerField("ID группы для уведомлений", null=True, blank=True)
    notification_group_link = models.CharField(
        "Ссылка-приглашение в группу для семей",
        max_length=300, blank=True, default="",
        help_text="Сюда будет перенаправлена семья после регистрации"
    )

    class Meta:
        verbose_name = "Настройки"
        verbose_name_plural = "Настройки"

    def __str__(self):
        return "Настройки бота"

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def owner_ids(self):
        if not self.owner_chat_ids:
            return []
        return [int(x.strip()) for x in self.owner_chat_ids.split(",") if x.strip().isdigit()]

    def get_title(self, lang="ru"):
        if lang == "en" and self.title_en:
            return self.title_en
        if lang == "he" and self.title_he:
            return self.title_he
        return self.title

    def get_greeting(self, lang="ru"):
        if lang == "en" and self.greeting_en:
            return self.greeting_en
        if lang == "he" and self.greeting_he:
            return self.greeting_he
        return self.greeting

    def get_address(self, lang="ru"):
        if lang == "en" and self.address_en:
            return self.address_en
        if lang == "he" and self.address_he:
            return self.address_he
        return self.address

    def get_contact(self, lang="ru"):
        if lang == "en" and self.contact_en:
            return self.contact_en
        if lang == "he" and self.contact_he:
            return self.contact_he
        return self.contact