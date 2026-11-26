from django import forms
from django.contrib import admin
from django.utils import timezone
from django.utils.html import format_html
from .models import Booking, Family, Settings, City, District, GuestProfile

admin.site.site_header = "Запись в гости — управление"
admin.site.site_title = "Запись в гости"
admin.site.index_title = "Заявки и настройки бота"


class SettingsForm(forms.ModelForm):
    class Meta:
        model = Settings
        fields = "__all__"


@admin.register(City)
class CityAdmin(admin.ModelAdmin):
    list_display = ("name", "order")
    list_editable = ("order",)
    ordering = ("order", "name")


@admin.register(District)
class DistrictAdmin(admin.ModelAdmin):
    list_display = ("name", "city", "order")
    list_editable = ("city", "order")
    list_filter = ("city",)
    ordering = ("city", "order", "name")


@admin.register(GuestProfile)
class GuestProfileAdmin(admin.ModelAdmin):
    list_display = ("tg_id", "name", "phone", "consented_at", "jewish_origin", "gender")
    list_filter = ("consented_at", "jewish_origin", "gender")
    search_fields = ("name", "phone", "tg_id")
    readonly_fields = ("tg_id", "tg_username", "consented_at")
    ordering = ("-consented_at",)


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ("date", "meal_title", "assigned_family", "name", "phone", "guests", "status", "tg_link", "created_at")
    list_filter = ("status", "meal", "assigned_family", "date")
    search_fields = ("name", "phone", "tg_username", "comment")
    date_hierarchy = "date"
    ordering = ("date", "time")
    readonly_fields = ("created_at", "decided_at", "tg_id", "tg_username", "photo_display")
    actions = ("action_confirm", "action_decline")

    @admin.display(description="Трапеза", ordering="meal")
    def meal_title(self, obj):
        return obj.meal_label

    @admin.display(description="Фото гостя")
    def photo_display(self, obj):
        if obj.photo:
            return format_html('<img src="{}" width="100" style="object-fit: cover; border-radius: 4px;" />', obj.photo.url)
        return "—"

    @admin.display(description="Telegram")
    def tg_link(self, obj):
        if not obj.tg_username:
            return "—"
        return format_html('<a href="https://t.me/{}" target="_blank">@{}</a>', obj.tg_username, obj.tg_username)

    def _set_status(self, request, queryset, status):
        n = queryset.exclude(status=status).update(status=status, decided_at=timezone.now())
        self.message_user(request, f"Обновлено записей: {n}")

    @admin.action(description="✅ Подтвердить выбранные")
    def action_confirm(self, request, queryset):
        self._set_status(request, queryset, "confirmed")

    @admin.action(description="❌ Отклонить выбранные")
    def action_decline(self, request, queryset):
        self._set_status(request, queryset, "declined")


@admin.register(Family)
class FamilyAdmin(admin.ModelAdmin):
    list_display = ("name", "district", "seats", "order", "is_active", "active_fri_evening", "active_sat_day", "telegram_chat_id")
    list_editable = ("district", "seats", "order", "is_active", "active_fri_evening", "active_sat_day", "telegram_chat_id")
    list_filter = ("district__city", "district", "is_active")
    ordering = ("order", "name")

    @admin.display(description="Фото")
    def photo_tag(self, obj):
        if obj.photo:
            return format_html('<img src="{}" width="50" style="object-fit: cover; border-radius: 4px;" />', obj.photo.url)
        return "—"


@admin.register(Settings)
class SettingsAdmin(admin.ModelAdmin):
    form = SettingsForm
    fieldsets = (
        ("Тексты", {"fields": ("title", "greeting", "address", "contact")}),
        ("Запись", {"fields": ("days_ahead",)}),
        ("Заявка", {"fields": ("ask_guests", "max_guests", "ask_phone")}),
        ("Уведомления", {"fields": ("notify_owner", "owner_chat_ids", "notify_mode", "notification_group_id")}),
    )

    def has_add_permission(self, request):
        return not Settings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False