from datetime import datetime, timedelta, timezone as dt_timezone
from unittest.mock import patch

from django.template.loader import render_to_string
from django.test import TestCase
from django.utils import timezone

from babybuddy.feeding_estimate import next_feeding_estimate
from core.models import Child, Feeding


class FeedingEstimateTests(TestCase):
    def setUp(self):
        self.child = Child.objects.create(
            first_name="Estimate", last_name="Test", birth_date="2025-01-01"
        )
        self.now = datetime(2026, 10, 17, 12, tzinfo=dt_timezone.utc)

    def feed(self, hours, **kwargs):
        start = self.now + timedelta(hours=hours)
        return Feeding.objects.create(
            child=kwargs.pop("child", self.child),
            start=start,
            end=start,
            type=kwargs.pop("type", "formula"),
            method="bottle",
            **kwargs,
        )

    def test_insufficient_history(self):
        self.assertIsNone(next_feeding_estimate(self.child, self.now)["estimated_at"])
        for hours in [-6, -3, 0]:
            self.feed(hours)
        result = next_feeding_estimate(self.child, self.now)
        self.assertIsNone(result["estimated_at"])
        self.assertIn(
            "Not enough history yet",
            render_to_string("cards/feeding_next.html", result),
        )

    def test_median_excludes_old_future_solids_other_children_and_duplicates(self):
        for hours in [-9, -6, -3, 0, 0, -337, 3]:
            self.feed(hours)
        self.feed(-1, type="solid food")
        other = Child.objects.create(first_name="Other", birth_date="2025-01-01")
        self.feed(-2, child=other)
        result = next_feeding_estimate(self.child, self.now)
        self.assertEqual(
            result["estimated_at"], self.now + timedelta(hours=3, minutes=-15)
        )
        self.assertEqual(result["sample_count"], 3)
        self.assertFalse(result["estimate_passed"])

    @timezone.override("UTC")
    def test_similar_time_across_midnight_and_passed_estimate(self):
        # Latest feeding is 23:00. Match 01:00 on preceding days across midnight.
        self.now = datetime(2026, 10, 17, 23, tzinfo=dt_timezone.utc)
        for hours in [-94, -90, -70, -66, -46, -42, 0]:
            self.feed(hours)
        result = next_feeding_estimate(self.child, self.now)
        self.assertTrue(result["similar_time"])
        self.assertEqual(result["sample_count"], 3)
        self.assertEqual(
            result["estimated_at"], self.now + timedelta(hours=4, minutes=-15)
        )
        later = next_feeding_estimate(self.child, self.now + timedelta(hours=5))
        self.assertTrue(later["estimate_passed"])
        self.assertNotIn(
            "Estimated time has passed",
            render_to_string("cards/feeding_next.html", later),
        )

    def test_dashboard_renders_card(self):
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.create_user(
            username="estimate", password="test", is_superuser=True
        )
        self.client.force_login(user)
        for hours in [-9, -6, -3, 0]:
            self.feed(hours)
        with patch("babybuddy.feeding_estimate.timezone.now", return_value=self.now):
            response = self.client.get(f"/children/{self.child.slug}/dashboard/")
        self.assertContains(response, "Estimated next feeding")
        self.assertNotContains(response, "Based on 3 feeding intervals")

    @timezone.override("UTC")
    def test_forecast_reselects_history_for_overnight_then_daytime(self):
        self.now = datetime(2026, 10, 17, 21, tzinfo=dt_timezone.utc)
        # Three full days: 21:00 -> 05:00 overnight, then shorter daytime gaps.
        for day in range(3, 0, -1):
            for offset in [0, 8, 12, 16, 20]:
                self.feed(-24 * day + offset)
        self.feed(0)
        result = next_feeding_estimate(self.child, self.now)
        self.assertEqual(
            [item["estimated_at"] for item in result["estimates"]],
            [self.now + timedelta(hours=hours, minutes=-15) for hours in [8, 12, 16]],
        )
        self.assertTrue(all(item["similar_time"] for item in result["estimates"]))
        self.assertEqual(Feeding.objects.count(), 16)
        html = render_to_string("cards/feeding_next.html", result)
        self.assertEqual(html.count('<li class="mb-2">'), 3)
        self.assertNotIn("Later estimates assume earlier feedings", html)

    def test_three_fallback_estimates_and_empty_forecast(self):
        self.assertEqual(next_feeding_estimate(self.child, self.now)["estimates"], [])
        for hours in [-9, -6, -3, 0]:
            self.feed(hours)
        result = next_feeding_estimate(self.child, self.now)
        self.assertEqual(
            [item["estimated_at"] for item in result["estimates"]],
            [self.now + timedelta(hours=hours, minutes=-15) for hours in [3, 6, 9]],
        )
        self.assertTrue(all(not item["similar_time"] for item in result["estimates"]))

    @timezone.override("UTC")
    def test_last_feeding_page_shows_only_next_adjusted_time(self):
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.create_user(
            username="last-estimate", password="test"
        )
        self.client.force_login(user)
        with patch("babybuddy.last_feeding_views.timezone.now", return_value=self.now):
            empty = self.client.get("/last-feeding/")
            self.assertNotContains(empty, "Next feeding ~")
            for hours in [-9, -6, -3, 0]:
                self.feed(hours)
            response = self.client.get("/last-feeding/", {"background_update": "1"})
        self.assertContains(response, "Next feeding ~", count=1)
        self.assertContains(response, ">2:45 PM</time>", html=False)
        self.assertNotContains(response, ">5:45 PM</time>", html=False)
        self.assertEqual(
            response.context["next_feeding"]["estimated_at"],
            self.now + timedelta(hours=2, minutes=45),
        )

    def test_estimates_include_usual_amount(self):
        for hours, amount in [(-9, 7), (-6, 6), (-3, 7.5), (0, 7)]:
            self.feed(hours, amount=amount)
        result = next_feeding_estimate(self.child, self.now)
        self.assertEqual([item["amount"] for item in result["estimates"]], [7, 7, 7])
        self.assertFalse(any(item["shortened"] for item in result["estimates"]))
        html = render_to_string("cards/feeding_next.html", result)
        self.assertIn("~7 oz", html)

    def test_small_last_feeding_moves_next_estimate_earlier(self):
        for hours in [-12, -8, -4]:
            self.feed(hours, amount=8)
        self.feed(0, amount=4)  # half the usual bottle
        result = next_feeding_estimate(self.child, self.now)
        # 4h usual gap shortened by 25% (the cap) -> 3h, minus the 15 min lead.
        self.assertEqual(
            result["estimated_at"], self.now + timedelta(hours=3, minutes=-15)
        )
        self.assertTrue(result["shortened"])
        # Later feedings assume a normal bottle, so they use the full usual gap.
        self.assertEqual(
            result["estimates"][1]["estimated_at"],
            self.now + timedelta(hours=7, minutes=-15),
        )
        self.assertFalse(result["estimates"][1]["shortened"])
        self.assertIn(
            "last bottle was small", render_to_string("cards/feeding_next.html", result)
        )

    def test_large_or_unknown_amount_does_not_shift_estimate(self):
        for hours in [-12, -8, -4]:
            self.feed(hours, amount=6)
        self.feed(0, amount=9)
        self.assertEqual(
            next_feeding_estimate(self.child, self.now)["estimated_at"],
            self.now + timedelta(hours=4, minutes=-15),
        )
