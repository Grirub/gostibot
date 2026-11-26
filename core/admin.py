from django import forms
from django.contrib import admin
from django.utils import timezone
from django.utils.html import format_html
from .models import Booking, Family, Settings, City, District, GuestProfile, Blacklist

admin.site.site_header = "Запись в гости — управление"
admin.site.site_title = "Запись в гости"
admin.site.index_title = "Заявки и настройки бота"


class SettingsForm(forms.ModelForm):
    class Meta:
        model = Settings
        fields = "__all__"


@admin.register(City)
class CityAdmin(admin.ModelAdmin):
    list_display = ("name", "name_en", "name_he", "order")
    list_editable = ("name_en", "name_he", "order")
    ordering = ("order", "name")


@admin.register(District)
class DistrictAdmin(admin.ModelAdmin):
    list_display = ("name", "name_en", "name_he", "city", "order")
    list_editable = ("name_en", "name_he", "city", "order")
    list_filter = ("city",)
    ordering = ("city", "order", "name")


@admin.register(GuestProfile)
class GuestProfileAdmin(admin.ModelAdmin):
    list_display = ("tg_id", "name", "phone", "consented_at", "jewish_origin",
                    "gender", "language", "city", "district")
    list_filter = ("consented_at", "jewish_origin", "gender", "language", "city")
    search_fields = ("name", "phone", "tg_id")
    readonly_fields = ("tg_id", "tg_username", "consented_at", "state_json")
    ordering = ("-consented_at",)


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ("date", "meal", "city", "district", "assigned_family",
                    "name", "phone", "guests", "status", "rating", "tg_link", "created_at")
    list_filter = ("status", "meal", "assigned_family", "date", "city", "district")
    search_fields = ("name", "phone", "tg_username", "comment")
    date_hierarchy = "date"
    ordering = ("date", "time")
    readonly_fields = ("created_at", "decided_at", "tg_id", "tg_username", "photo_display")
    actions = ("action_confirm", "action_decline")

    @admin.display(description="Фото гостя")
    def photo_display(self, obj):
        if obj.photo:
            return format_html(
                '<img src="{}" width="100" style="object-fit: cover; border-radius: 4px;" />',
                obj.photo.url
            )
        return "—"

    @admin.display(description="Telegram")
    def tg_link(self, obj):
        if not obj.tg_username:
            return "—"
        return format_html('<a href="https://t.me/{}" target="_blank">@{}</a>',
                           obj.tg_username, obj.tg_username)

    def _set_status(self, request, queryset, status):
        n = queryset.exclude(status=status).update(status=status, decided_at=timezone.now())
        self.message_user(request, f"Обновлено записей: {n}")

    @admin.action(description="✅ Подтвердить выбранные")
    def action_confirm(self, request, queryset):
        self._set_status(request, queryset, "confirmed")

    @admin.action(description="❌ Отклонить выбранные")
    def action_decline(self, request, queryset):
        self._set_status(request, queryset, "declined")


class ConsentedFamily(Family):
    class Meta:
        proxy = True
        verbose_name = "Семья с согласием (кашрут)"
        verbose_name_plural = "Семьи с согласием (кашрут)"


@admin.register(ConsentedFamily)
class ConsentedFamilyAdmin(admin.ModelAdmin):
    list_display = ("name", "district", "consented_at", "is_active", "telegram_chat_id")
    list_filter = ("consented_at", "district__city", "district", "is_active")
    ordering = ("-consented_at", "name")
    search_fields = ("name", "district__name", "telegram_chat_id")

    def get_queryset(self, request):
        return super().get_queryset(request).filter(consented_at__isnull=False)


@admin.register(Blacklist)
class BlacklistAdmin(admin.ModelAdmin):
    list_display = ("tg_id", "reason", "blocked_at", "blocked_by")
    search_fields = ("tg_id", "reason", "blocked_by")
    list_filter = ("blocked_at",)
    ordering = ("-blocked_at",)
    readonly_fields = ("blocked_at",)


@admin.register(Family)
class FamilyAdmin(admin.ModelAdmin):
    list_display = ("name", "district", "photo_tag", "order", "is_active",
                    "active_fri_evening", "active_sat_day",
                    "telegram_chat_id", "consented_at", "language")
    list_editable = ("district", "order", "is_active",
                     "active_fri_evening", "active_sat_day", "telegram_chat_id", "language")
    list_filter = ("consented_at", "district__city", "district", "is_active", "language")
    ordering = ("order", "name")

    def get_exclude(self, request, obj=None):
        try:
            Family._meta.get_field("seats")
            return ("seats",)
        except Exception:
            return ()

    @admin.display(description="Фото")
    def photo_tag(self, obj):
        if obj.photo:
            return format_html(
                '<img src="{}" width="50" style="object-fit: cover; border-radius: 4px;" />',
                obj.photo.url
            )
        return "—"


@admin.register(Settings)
class SettingsAdmin(admin.ModelAdmin):
    form = SettingsForm
    fieldsets = (
        ("Тексты (RU)", {"fields": ("title", "greeting", "address", "contact")}),
        ("Тексты (EN)", {"fields": ("title_en", "greeting_en", "address_en", "contact_en")}),
        ("Тексты (HE)", {"fields": ("title_he", "greeting_he", "address_he", "contact_he")}),
        ("Запись", {"fields": ("days_ahead",)}),
        ("Заявка", {"fields": ("ask_guests", "max_guests", "ask_phone")}),
        ("Уведомления", {"fields": ("notify_owner", "owner_chat_ids", "notify_mode",
                                    "notification_group_id", "notification_group_link")}),
    )

    def has_add_permission(self, request):
        return not Settings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False