"""Логика бронирований с дедлайнами и защитой от гонок."""
import logging
from datetime import timedelta, time as dtime
from django.db import transaction
from django.utils import timezone
from core.models import Booking, District, GuestProfile

log = logging.getLogger("gostibot")


def get_next_weekday(weekday_num):
    today = timezone.localdate()
    days_ahead = weekday_num - today.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    return today + timedelta(days=days_ahead)


def get_active_meals(chat_id):
    return list(
        Booking.objects.filter(
            tg_id=chat_id, status__in=["pending", "confirmed"]
        ).values_list("meal", flat=True)
    )


@transaction.atomic
def create_booking(chat_id, data, meal_mode):
    profile = GuestProfile.objects.filter(tg_id=chat_id).first()
    if not profile:
        log.error("Profile not found for %s", chat_id)
        return None

    try:
        district = District.objects.get(pk=data["district_id"])
    except District.DoesNotExist:
        log.error("District %s not found", data.get("district_id"))
        return None

    city = district.city
    next_week = bool(data.get("next_week"))
    shift = timedelta(days=7) if next_week else timedelta(days=0)

    if meal_mode == "fri_evening":
        target_date = get_next_weekday(4) + shift
        target_time = dtime(18, 0)
    else:
        target_date = get_next_weekday(5) + shift
        target_time = dtime(13, 0)

    return Booking.objects.create(
        date=target_date,
        time=target_time,
        meal=meal_mode,
        name=profile.name,
        phone=profile.phone,
        guests=int(data.get("guests") or 1),
        comment=data.get("comment") or "",
        tg_id=chat_id,
        tg_username=profile.tg_username,
        photo=profile.photo,
        jewish_origin=profile.jewish_origin,
        gender=profile.gender,
        city=city,
        district=district,
        status="pending",
    )


@transaction.atomic
def claim_booking(booking_id, family):
    booking = Booking.objects.select_for_update().filter(pk=booking_id).first()
    if not booking:
        return None, "not_found"
    if booking.assigned_family:
        return booking, "already_accepted"
    if booking.status in ("cancelled", "declined", "expired"):
        return booking, "not_available"

    booking.assigned_family = family
    booking.status = "confirmed"
    booking.decided_at = timezone.now()
    booking.save(update_fields=["assigned_family", "status", "decided_at"])
    return booking, "ok"


@transaction.atomic
def cancel_booking_by_guest(booking_id, chat_id):
    booking = Booking.objects.filter(pk=booking_id, tg_id=chat_id).first()
    if not booking or booking.status in ("cancelled", "declined"):
        return None, "already_cancelled"

    from ..keyboards import can_guest_cancel
    if not can_guest_cancel(booking):
        return booking, "deadline_passed"

    old_status = booking.status
    booking.status = "cancelled"
    booking.decided_at = timezone.now()
    booking.save(update_fields=["status", "decided_at"])
    return booking, old_status


@transaction.atomic
def cancel_booking_by_family(booking_id, family):
    booking = Booking.objects.select_for_update().filter(pk=booking_id).first()
    if not booking or booking.assigned_family != family:
        return None, "no_access"
    if booking.status in ("cancelled", "declined"):
        return booking, "already_cancelled"

    from ..keyboards import can_family_cancel
    if not can_family_cancel(booking):
        return booking, "deadline_passed"

    if booking.date < timezone.localdate():
        booking.status = "cancelled"
        booking.decided_at = timezone.now()
        booking.save(update_fields=["status", "decided_at"])
        return booking, "cancelled_past"

    booking.assigned_family = None
    booking.status = "pending"
    booking.decided_at = timezone.now()
    booking.save(update_fields=["assigned_family", "status", "decided_at"])
    return booking, "requeued"


@transaction.atomic
def cancel_all_old_bookings(chat_id):
    old = Booking.objects.filter(tg_id=chat_id, status__in=["pending", "confirmed"])
    cancelled = []
    for b in old:
        b.status = "cancelled"
        b.decided_at = timezone.now()
        b.save(update_fields=["status", "decided_at"])
        cancelled.append(b)
    return cancelled