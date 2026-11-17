from datetime import datetime

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.templatetags.static import static
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from babybuddy.feeding_estimate import next_feeding_estimate

from core.models import (
    BannerDismissal,
    Child,
    Feeding,
    LayDownEvent,
    MedicineEvent,
    Sleep,
)

SOLID_FOOD = "solid food"


def parse_manual_event_time(value, fallback):
    if not value:
        return fallback

    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M")
    except ValueError:
        return fallback

    return timezone.make_aware(parsed, timezone.get_current_timezone())


def last_feeding_manifest(request):
    """Web app manifest so a tablet can install the page as a fullscreen app."""
    return JsonResponse(
        {
            "name": "Last Feeding",
            "short_name": "Last Feeding",
            "start_url": reverse("babybuddy:last_feeding_page") + "?kiosk=1",
            "scope": "/",
            "display": "fullscreen",
            "background_color": "#000000",
            "theme_color": "#000000",
            "icons": [
                {
                    "src": static(f"babybuddy/root/android-chrome-{size}x{size}.png"),
                    "sizes": f"{size}x{size}",
                    "type": "image/png",
                }
                for size in (192, 512)
            ],
        },
        content_type="application/manifest+json",
    )


LAST_FEEDING_SERVICE_WORKER = """
// Keeps the last successfully loaded Last Feeding page so the browser can show
// it when the server cannot be reached.
const CACHE = "last-feeding-v1";
const PAGE_KEY = "last-feeding-page";

self.addEventListener("install", function () { self.skipWaiting(); });
self.addEventListener("activate", function (event) { event.waitUntil(self.clients.claim()); });

function withTimeout(promise, ms) {
    return new Promise(function (resolve, reject) {
        const timer = setTimeout(function () { reject(new Error("timeout")); }, ms);
        promise.then(
            function (value) { clearTimeout(timer); resolve(value); },
            function (error) { clearTimeout(timer); reject(error); }
        );
    });
}

async function savedPage() {
    const cache = await caches.open(CACHE);
    const saved = await cache.match(PAGE_KEY);
    if (!saved) return null;
    // Mark the copy so the page can say it is not live.
    const html = (await saved.text()).replace("<html", '<html data-offline-copy="1"');
    return new Response(html, { headers: { "Content-Type": "text/html; charset=utf-8" } });
}

async function loadPage(request) {
    try {
        const response = await withTimeout(fetch(request), 10000);
        if (response.status >= 500) throw new Error("server error");
        if (response.ok && !response.redirected) {
            const cache = await caches.open(CACHE);
            await cache.put(PAGE_KEY, response.clone());
        }
        return response;
    } catch (error) {
        const saved = await savedPage();
        if (saved) return saved;
        throw error;
    }
}

self.addEventListener("fetch", function (event) {
    const request = event.request;
    if (request.method !== "GET" || request.mode !== "navigate") return;
    if (new URL(request.url).pathname !== "__PAGE_PATH__") return;
    event.respondWith(loadPage(request));
});
"""


def last_feeding_service_worker(request):
    """Service worker that keeps an offline copy of the last feeding page."""
    script = LAST_FEEDING_SERVICE_WORKER.replace(
        "__PAGE_PATH__", reverse("babybuddy:last_feeding_page")
    )
    response = HttpResponse(script, content_type="application/javascript")
    response["Cache-Control"] = "no-cache"
    return response


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
            elif action == "solid_food":
                # Logged as its own feeding type; the bottle timer, alerts and
                # next-bottle estimate all ignore "solid food" entries.
                Feeding.objects.create(
                    child=child,
                    start=manual_event_time,
                    end=manual_event_time,
                    type=SOLID_FOOD,
                    method="parent fed",
                    notes=request.POST.get("notes", ""),
                )
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

    feeding = Feeding.objects.exclude(type=SOLID_FOOD).order_by("-start").first()
    last_solid_food = (
        Feeding.objects.filter(child=child, type=SOLID_FOOD).order_by("-start").first()
        if child
        else None
    )

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

        if minutes_since_feeding >= 210:
            alert_level = "red"
            should_blink_alert = minutes_since_feeding >= 210
        elif minutes_since_feeding >= 180:
            alert_level = "yellow"
            should_blink_alert = minutes_since_feeding >= 210

    context = {
        "next_feeding": (
            next_feeding_estimate(feeding.child, now=now) if feeding else None
        ),
        "feeding": feeding,
        "last_solid_food": last_solid_food,
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
