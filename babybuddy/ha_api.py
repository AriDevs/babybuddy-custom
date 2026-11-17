"""Token-authenticated JSON endpoints backing the Home Assistant dashboard.

GET  /api/ha/summary/  -> what the /last-feeding and /feedings pages show
POST /api/ha/action/   -> {"action": "bottle"|"medicine"|"lay_down", ...}
                          bottle also takes "amount" and "time" ("HH:MM", default now);
                          the time may instead ride on the action: "bottle@HH:MM"
"""

from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from django.utils import timezone
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from babybuddy.feeding_estimate import next_feeding_estimate
from babybuddy.feeding_totals import feeding_ounce_totals
from core.models import Child, Feeding, LayDownEvent, MedicineEvent

RECENT_FEEDINGS = 25


def _iso(moment):
    return timezone.localtime(moment).isoformat() if moment else None


def _number(value):
    return float(value) if value is not None else None


def resolve_event_time(value, now):
    """Turn an optional "HH:MM" clock time into the most recent matching moment.

    Empty values mean "now". A time later than now is taken as yesterday's, so
    logging an 11:50 PM bottle at 12:10 AM lands on the right day.
    """
    if not value:
        return now
    text = str(value).strip()
    parsed = None
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            parsed = datetime.strptime(text, fmt).time()
            break
        except ValueError:
            continue
    if parsed is None:
        raise ValueError("Invalid time.")
    local_now = timezone.localtime(now)
    moment = timezone.make_aware(
        datetime.combine(local_now.date(), parsed), timezone.get_current_timezone()
    )
    if moment > now + timedelta(minutes=5):
        moment -= timedelta(days=1)
    return min(moment, now)


class _HomeAssistantView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]
    schema = None

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        # Token requests skip the session based timezone middleware.
        user_settings = getattr(request.user, "settings", None)
        if user_settings and user_settings.timezone:
            timezone.activate(user_settings.timezone)

    def finalize_response(self, request, response, *args, **kwargs):
        timezone.deactivate()
        return super().finalize_response(request, response, *args, **kwargs)


def build_summary(now=None):
    now = now or timezone.now()
    local_now = timezone.localtime(now)
    child = Child.objects.first()
    feeding = Feeding.objects.order_by("-start").first()

    summary = {
        "generated_at": _iso(now),
        "child": child.first_name if child else None,
        "last_feeding_at": None,
        "last_feeding_amount": None,
        "last_feeding_type": None,
        "last_feeding_method": None,
        "last_feeding_notes": "",
        "minutes_since_feeding": None,
        "alert_level": "normal",
        "next_feeding_at": None,
        "next_feeding_amount": None,
        "next_feedings": [],
        "last_medicine_at": None,
        "last_lay_down_at": None,
        "today_ounces": 0,
        "today_feedings": 0,
        "daily_totals": [],
        "recent_feedings": [],
    }
    if not child:
        return summary

    if feeding:
        minutes = int((now - feeding.start).total_seconds() / 60)
        summary.update(
            last_feeding_at=_iso(feeding.start),
            last_feeding_amount=_number(feeding.amount),
            last_feeding_type=feeding.type,
            last_feeding_method=feeding.method,
            last_feeding_notes=feeding.notes or "",
            minutes_since_feeding=minutes,
            # Same thresholds as the /last-feeding page.
            alert_level=(
                "red" if minutes >= 210 else "yellow" if minutes >= 150 else "normal"
            ),
        )
        estimate = next_feeding_estimate(feeding.child, now=now)
        summary["next_feeding_at"] = _iso(estimate.get("estimated_at"))
        summary["next_feeding_amount"] = _number(estimate.get("amount"))
        summary["next_feedings"] = [
            {"at": _iso(item["estimated_at"]), "amount": _number(item["amount"])}
            for item in estimate.get("estimates", [])
        ]

    medicine = MedicineEvent.objects.filter(child=child).order_by("-time").first()
    lay_down = LayDownEvent.objects.filter(child=child).order_by("-time").first()
    summary["last_medicine_at"] = _iso(medicine.time) if medicine else None
    summary["last_lay_down_at"] = _iso(lay_down.time) if lay_down else None

    totals = feeding_ounce_totals(child, now=now)
    summary["today_ounces"] = _number(totals["today_ounces"])
    summary["daily_totals"] = [
        {"date": day["date"].isoformat(), "amount": _number(day["amount"])}
        for day in totals["daily_feeding_totals"]
    ]
    day_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    summary["today_feedings"] = Feeding.objects.filter(
        child=child, start__gte=day_start, start__lt=day_start + timedelta(days=1)
    ).count()

    summary["recent_feedings"] = [
        {
            "start": _iso(item.start),
            "amount": _number(item.amount),
            "type": item.type,
            "method": item.method,
            "notes": item.notes or "",
        }
        for item in Feeding.objects.filter(child=child).order_by("-start")[
            :RECENT_FEEDINGS
        ]
    ]
    return summary


class SummaryView(_HomeAssistantView):
    def get(self, request):
        return Response(build_summary())


class ActionView(_HomeAssistantView):
    def post(self, request):
        child = Child.objects.first()
        if not child:
            return Response({"error": "No child configured."}, status=400)

        # "bottle@15:56" carries the clock time inside the action, for callers
        # whose payload template does not forward a separate "time" field.
        action, _, action_time = str(request.data.get("action") or "").partition("@")
        now = timezone.now()
        try:
            when = resolve_event_time(request.data.get("time") or action_time, now)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)

        if action == "bottle":
            amount = request.data.get("amount")
            if amount in ("", None):
                amount = None
            else:
                try:
                    amount = Decimal(str(amount))
                except InvalidOperation:
                    return Response({"error": "Invalid amount."}, status=400)
                if amount <= 0:
                    amount = None
            # Mirrors the bottle form on the /last-feeding page.
            Feeding.objects.create(
                child=child,
                start=when,
                end=when,
                type="formula",
                method="bottle",
                amount=amount,
                notes=request.data.get("notes") or "",
            )
        elif action == "medicine":
            MedicineEvent.objects.create(child=child, time=now)
        elif action == "lay_down":
            LayDownEvent.objects.create(child=child, time=now)
        else:
            return Response({"error": "Unknown action."}, status=400)

        return Response(build_summary())
