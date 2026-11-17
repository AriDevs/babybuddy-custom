"""Descriptive feeding estimates from completed, recorded milk feedings."""

from datetime import timedelta
from statistics import median

from django.utils import timezone

from core.models import Feeding

SIMILAR_MINUTES = 120
# How strongly a smaller-than-usual bottle pulls the next feeding earlier:
# 0.5 means a bottle 30% below usual shortens the gap by 15%.
SMALL_FEED_WEIGHT = 0.5
MIN_INTERVAL_FACTOR = 0.75


def _clock_minute(moment):
    local = timezone.localtime(moment)
    return local.hour * 60 + local.minute


def _similar(rows, minute):
    """Values recorded near this time of day, or all values if too few match."""
    similar = [
        value
        for clock, value in rows
        if min(abs(clock - minute), 1440 - abs(clock - minute)) <= SIMILAR_MINUTES
    ]
    return (
        (similar, True) if len(similar) >= 3 else ([value for _, value in rows], False)
    )


def _interval_factor(amount, usual_amount):
    """Shorten the next gap when the baby ate less than usual."""
    if not amount or not usual_amount or amount >= usual_amount:
        return 1.0
    shortfall = 1 - amount / usual_amount
    return max(MIN_INTERVAL_FACTOR, 1 - SMALL_FEED_WEIGHT * shortfall)


def next_feeding_estimate(child, now=None):
    now = now or timezone.now()
    feedings = (
        Feeding.objects.filter(
            child=child,
            start__gte=now - timedelta(days=14),
            start__lte=now,
            end__lte=now,
        )
        .exclude(type="solid food")
        .order_by("start")
        .values_list("start", "amount")
    )
    # Several entries can share a start time; merge their amounts.
    amounts_by_start = {}
    for start, amount in feedings:
        amounts_by_start.setdefault(start, None)
        if amount:
            amounts_by_start[start] = (amounts_by_start[start] or 0) + amount
    starts = list(amounts_by_start)

    result = {"estimated_at": None, "sample_count": 0, "estimates": []}
    if len(starts) < 4:
        return result

    # Keep observed intervals separate from predictions. Each prediction selects
    # its own local time-of-day samples; elapsed durations stay in UTC for DST.
    history = []
    for start, following in zip(starts, starts[1:]):
        seconds = (following - start).total_seconds()
        if seconds > 0:
            history.append((_clock_minute(start), seconds))
    if len(history) < 3:
        return result

    amount_history = [
        (_clock_minute(start), amount)
        for start, amount in amounts_by_start.items()
        if amount
    ]

    def usual_amount(minute):
        return median(_similar(amount_history, minute)[0]) if amount_history else None

    anchor = starts[-1]
    anchor_amount = amounts_by_start[anchor]
    estimates = []
    for _ in range(3):
        minute = _clock_minute(anchor)
        samples, similar_time = _similar(history, minute)
        factor = _interval_factor(anchor_amount, usual_amount(minute))
        anchor += timedelta(seconds=median(samples) * factor)

        usual = usual_amount(_clock_minute(anchor))
        amount = round(usual * 2) / 2 if usual else None
        # Shift each displayed time without changing subsequent forecast anchors.
        estimated_at = anchor - timedelta(minutes=15)
        estimates.append(
            {
                "estimated_at": estimated_at,
                "estimate_passed": estimated_at <= now,
                "sample_count": len(samples),
                "similar_time": similar_time,
                "amount": amount,
                "shortened": factor < 1,
            }
        )
        anchor_amount = usual
    return {**estimates[0], "estimates": estimates}
