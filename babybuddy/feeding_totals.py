from datetime import timedelta

from django.db.models import Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from core.models import Feeding


def feeding_ounce_totals(child, now=None):
    """Recorded milk/formula ounces by local day for the past week."""
    now = now or timezone.now()
    local_now = timezone.localtime(now)
    # Amounts entered on this dashboard are ounces; solids use different units.
    measured_feedings = Feeding.objects.filter(
        child=child, start__lte=now, amount__isnull=False
    ).exclude(type="solid food")
    first_day = local_now.date() - timedelta(days=6)
    daily_amounts = dict(
        measured_feedings.filter(start__date__gte=first_day)
        .order_by()
        .annotate(day=TruncDate("start"))
        .values("day")
        .annotate(total=Sum("amount"))
        .values_list("day", "total")
    )
    daily_totals = [
        {
            "date": local_now.date() - timedelta(days=offset),
            "amount": daily_amounts.get(local_now.date() - timedelta(days=offset), 0),
        }
        for offset in range(7)
    ]

    return {
        "daily_feeding_totals": daily_totals,
        "today_ounces": daily_totals[0]["amount"],
    }
