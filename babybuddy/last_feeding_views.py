from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils import timezone

from core.models import Child, Feeding, LayDownEvent, MedicineEvent, Sleep


@login_required
def last_feeding_page(request):
    if request.method == "POST":
        child = Child.objects.first()
        action = request.POST.get("action", "bottle")

        if child:
            now = timezone.now()
            if action == "medicine":
                MedicineEvent.objects.create(child=child, time=now)
            elif action == "lay_down":
                LayDownEvent.objects.create(child=child, time=now)
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
    show_bed_banner = False

    if feeding:
        now = timezone.now()
        minutes_since_feeding = int((now - feeding.start).total_seconds() / 60)
        hours = minutes_since_feeding // 60
        minutes = minutes_since_feeding % 60
        is_quiet_hour = timezone.localtime(now).hour < 9
        is_sleeping = Sleep.objects.filter(
            child=feeding.child,
            start__lte=now,
            end__gt=now,
        ).exists()
        show_bed_banner = (
            60 <= minutes_since_feeding < 120 and not is_sleeping and not is_quiet_hour
        )

        if minutes_since_feeding >= 180:
            alert_level = "red"
        elif minutes_since_feeding >= 120:
            alert_level = "yellow"

    context = {
        "feeding": feeding,
        "minutes_since_feeding": minutes_since_feeding,
        "hours": hours,
        "minutes": minutes,
        "alert_level": alert_level,
        "show_bed_banner": show_bed_banner,
    }

    return render(request, "babybuddy/last_feeding.html", context)
