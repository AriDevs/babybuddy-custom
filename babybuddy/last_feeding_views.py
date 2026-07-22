from datetime import datetime

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils import timezone

from core.models import (
    BannerDismissal,
    Child,
    Feeding,
    LayDownEvent,
    MedicineEvent,
    Sleep,
)


def parse_manual_event_time(value, fallback):
    if not value:
        return fallback

    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M")
    except ValueError:
        return fallback

    return timezone.make_aware(parsed, timezone.get_current_timezone())


@login_required
def last_feeding_page(request):
    now = timezone.now()
    local_now = timezone.localtime(now)
    child = Child.objects.first()

    if request.method == "POST":
        action = request.POST.get("action", "bottle")

        if child:
            manual_event_time = parse_manual_event_time(
                request.POST.get("event_time"), now
            )

            if action == "medicine":
                MedicineEvent.objects.create(child=child, time=now)
            elif action == "medicine_manual":
                MedicineEvent.objects.create(child=child, time=manual_event_time)
            elif action == "dismiss_medicine":
                BannerDismissal.objects.update_or_create(
                    child=child,
                    banner_type=BannerDismissal.MEDICINE,
                    reminder_date=local_now.date(),
                    defaults={"dismissed_at": now, "feeding": None},
                )
            elif action == "lay_down":
                LayDownEvent.objects.create(child=child, time=now)
            elif action == "lay_down_manual":
                LayDownEvent.objects.create(child=child, time=manual_event_time)
            elif action == "dismiss_bed":
                feeding_id = request.POST.get("feeding_id")
                feeding = Feeding.objects.filter(id=feeding_id, child=child).first()
                if feeding:
                    BannerDismissal.objects.update_or_create(
                        child=child,
                        banner_type=BannerDismissal.BED,
                        feeding=feeding,
                        defaults={"dismissed_at": now, "reminder_date": None},
                    )
            else:
                amount = request.POST.get("amount") or None
                notes = request.POST.get("notes", "")
                Feeding.objects.create(
                    child=child,
                    start=now,
                    end=now,
                    type="formula",
                    method="bottle",
                    amount=amount,
                    notes=notes,
                )

        return redirect("babybuddy:last_feeding_page")

    feeding = Feeding.objects.order_by("-start").first()

    minutes_since_feeding = None
    hours = 0
    minutes = 0
    alert_level = "normal"
    should_blink_alert = False
    show_medicine_banner = False
    show_bed_banner = False

    is_medicine_reminder_window = 21 <= local_now.hour < 23

    if child and is_medicine_reminder_window:
        has_medicine_event = MedicineEvent.objects.filter(
            child=child,
            time__date=local_now.date(),
            time__hour__gte=21,
            time__hour__lt=23,
        ).exists()
        is_medicine_dismissed = BannerDismissal.objects.filter(
            child=child,
            banner_type=BannerDismissal.MEDICINE,
            reminder_date=local_now.date(),
        ).exists()
        show_medicine_banner = not has_medicine_event and not is_medicine_dismissed

    if feeding:
        minutes_since_feeding = int((now - feeding.start).total_seconds() / 60)
        hours = minutes_since_feeding // 60
        minutes = minutes_since_feeding % 60
        is_quiet_hour = local_now.hour >= 21 or local_now.hour < 8
        is_sleeping = Sleep.objects.filter(
            child=feeding.child,
            start__lte=now,
            end__gt=now,
        ).exists()
        show_bed_banner = (
            60 <= minutes_since_feeding < 120 and not is_sleeping and not is_quiet_hour
        )
        if show_bed_banner:
            has_lay_down_event = LayDownEvent.objects.filter(
                child=feeding.child,
                time__gte=feeding.start,
            ).exists()
            is_bed_dismissed = BannerDismissal.objects.filter(
                child=feeding.child,
                banner_type=BannerDismissal.BED,
                feeding=feeding,
            ).exists()
            show_bed_banner = not has_lay_down_event and not is_bed_dismissed

        if minutes_since_feeding >= 180:
            alert_level = "red"
            should_blink_alert = minutes_since_feeding >= 210
        elif minutes_since_feeding >= 120:
            alert_level = "yellow"
            should_blink_alert = minutes_since_feeding >= 150

    context = {
        "feeding": feeding,
        "child": child,
        "minutes_since_feeding": minutes_since_feeding,
        "hours": hours,
        "minutes": minutes,
        "alert_level": alert_level,
        "should_blink_alert": should_blink_alert,
        "show_medicine_banner": show_medicine_banner,
        "show_bed_banner": show_bed_banner,
        "medicine_window_start": local_now.replace(
            hour=21, minute=0, second=0, microsecond=0
        ),
        "medicine_window_end": local_now.replace(
            hour=23, minute=0, second=0, microsecond=0
        ),
        "manual_event_time_value": local_now.strftime("%Y-%m-%dT%H:%M"),
    }

    return render(request, "babybuddy/last_feeding.html", context)
