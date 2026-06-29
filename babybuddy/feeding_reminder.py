import json
import os
from datetime import timedelta
from urllib.request import Request, urlopen

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from core.models import Feeding


def is_bottle_feeding(feeding):
    feeding_type = str(getattr(feeding, "type", "") or "").lower()
    method = str(getattr(feeding, "method", "") or "").lower()

    return (
        "formula" in feeding_type or "bottle" in method or "fortified" in feeding_type
    )


@receiver(post_save, sender=Feeding)
def send_bottle_reminder_to_home_assistant(sender, instance, created, **kwargs):
    if not created:
        return

    if not is_bottle_feeding(instance):
        return

    webhook_url = os.environ.get("HOME_ASSISTANT_WEBHOOK_URL")
    if not webhook_url:
        print("HOME_ASSISTANT_WEBHOOK_URL is not set.")
        return

    reminder_hours = int(os.environ.get("BABY_BOTTLE_REMINDER_HOURS", "2"))

    start_time = getattr(instance, "start", None)
    if not start_time:
        return

    local_start = timezone.localtime(start_time)
    reminder_at = local_start + timedelta(hours=reminder_hours)

    payload = {
        "feeding_id": instance.id,
        "child_id": instance.child_id,
        "feeding_start": local_start.isoformat(),
        "reminder_at": reminder_at.isoformat(),
        "reminder_at_ha": reminder_at.strftime("%Y-%m-%d %H:%M:%S"),
        "message": f"It has been {reminder_hours} hours since the last bottle feeding.",
    }

    request = Request(
        webhook_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        urlopen(request, timeout=5)
        print(
            f"Home Assistant bottle reminder scheduled for {payload['reminder_at_ha']}"
        )
    except Exception as exc:
        print(f"Failed to call Home Assistant webhook: {exc}")
