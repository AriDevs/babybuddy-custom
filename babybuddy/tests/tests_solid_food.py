import os
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.test import Client as HttpClient
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from babybuddy.ha_api import build_summary
from core import models


class SolidFoodTestCase(TestCase):
    def setUp(self):
        # Keep the bottle-reminder signal from calling the real Home Assistant webhook.
        env = patch.dict(os.environ, {"HOME_ASSISTANT_WEBHOOK_URL": ""})
        env.start()
        self.addCleanup(env.stop)
        self.user = get_user_model().objects.create_user(
            username="solid", password="pw-solid-123", is_superuser=True
        )
        self.child = models.Child.objects.create(
            first_name="Spaghetti", last_name="Baby", birth_date="2024-01-01"
        )
        self.now = timezone.now()
        for hours in (12, 9, 6, 3, 1):
            at = self.now - timedelta(hours=hours)
            models.Feeding.objects.create(
                child=self.child,
                start=at,
                end=at,
                type="formula",
                method="bottle",
                amount=4,
            )

    def _bottle_state(self):
        summary = build_summary(now=self.now)
        return (
            summary["last_feeding_at"],
            summary["next_feeding_at"],
            summary["alert_level"],
            summary["today_ounces"],
        )

    def test_page_logs_solid_food_without_moving_bottle_timer(self):
        before = self._bottle_state()
        client = HttpClient()
        client.force_login(self.user)
        event_time = timezone.localtime(self.now - timedelta(minutes=10))
        response = client.post(
            "/last-feeding/",
            data={
                "action": "solid_food",
                "event_time": event_time.strftime("%Y-%m-%dT%H:%M"),
                "notes": "Oatmeal",
            },
        )
        self.assertEqual(response.status_code, 302)
        solid = models.Feeding.objects.get(type="solid food")
        self.assertEqual(solid.method, "parent fed")
        self.assertEqual(solid.notes, "Oatmeal")
        self.assertEqual(self._bottle_state(), before)

        page = client.get("/last-feeding/")
        self.assertEqual(page.context["feeding"].type, "formula")
        self.assertContains(page, "Solid food at")

    def test_ha_action_logs_solid_food(self):
        before = self._bottle_state()
        api = APIClient()
        token = Token.objects.create(user=self.user)
        api.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        response = api.post(
            "/api/ha/action/",
            {"action": "solid_food", "notes": "Banana"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["last_solid_food_notes"], "Banana")
        self.assertIsNotNone(response.data["last_solid_food_at"])
        self.assertEqual(models.Feeding.objects.filter(type="solid food").count(), 1)
        self.assertEqual(self._bottle_state(), before)
