# -*- coding: utf-8 -*-
import re
import time
from unittest.mock import patch

from django.test import TestCase, override_settings, tag
from django.test import Client as HttpClient
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import call_command
from django.utils import timezone

from faker import Faker

from babybuddy.views import UserUnlock
from core import models


class ViewsTestCase(TestCase):
    @classmethod
    def setUpClass(cls):
        super(ViewsTestCase, cls).setUpClass()
        fake = Faker()
        call_command("migrate", verbosity=0)

        cls.c = HttpClient()

        fake_user = fake.simple_profile()
        cls.credentials = {
            "username": fake_user["username"],
            "password": fake.password(),
        }
        cls.user = get_user_model().objects.create_user(
            is_superuser=True, email="admin@admin.admin", **cls.credentials
        )

        cls.c.force_login(cls.user)

    def test_root_router(self):
        page = self.c.get("/")
        self.assertEqual(page.url, "/dashboard/")

    @override_settings(ROLLING_SESSION_REFRESH=1)
    def test_rolling_sessions(self):
        self.c.get("/")
        session1 = str(self.c.cookies["sessionid"])
        # Sleep longer than ROLLING_SESSION_REFRESH.
        time.sleep(2)
        self.c.get("/")
        session2 = str(self.c.cookies["sessionid"])
        self.c.get("/")
        session3 = str(self.c.cookies["sessionid"])
        self.assertNotEqual(session1, session2)
        self.assertEqual(session2, session3)

    def test_user_settings(self):
        page = self.c.get("/user/settings/")
        self.assertEqual(page.status_code, 200)

    def test_add_device_page(self):
        page = self.c.get("/user/add-device/")
        self.assertRegex(
            page.content.decode(),
            r""".*<div [^>]* data-qr-code-content="[^"]+"[^>]*>.*""",
        )

    def test_user_views(self):
        # Staff setting is required to access user management.
        page = self.c.get("/users/")
        self.assertEqual(page.status_code, 403)
        self.user.is_staff = True
        self.user.save()

        page = self.c.get("/users/")
        self.assertEqual(page.status_code, 200)
        page = self.c.get("/users/add/")
        self.assertEqual(page.status_code, 200)

        entry = get_user_model().objects.first()
        page = self.c.get("/users/{}/edit/".format(entry.id))
        self.assertEqual(page.status_code, 200)
        page = self.c.get("/users/{}/delete/".format(entry.id))
        self.assertEqual(page.status_code, 200)

    def test_user_unlock(self):
        # Staff setting is required to unlock users.
        self.user.is_staff = True
        self.user.save()

        entry = get_user_model().objects.first()
        url = "/users/{}/unlock/".format(entry.id)

        page = self.c.get(url)
        self.assertEqual(page.status_code, 200)
        page = self.c.post(url, follow=True)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, UserUnlock.success_message)

    def test_welcome(self):
        page = self.c.get("/welcome/")
        self.assertEqual(page.status_code, 200)

    def test_logout_get_fails(self):
        page = self.c.get("/logout/")
        self.assertEqual(page.status_code, 405)

    @tag("isolate")
    def test_password_reset(self):
        """
        Testing this class primarily ensures Baby Buddy's custom templates are correctly
        configured for Django's password reset flow.
        """
        self.c.logout()

        page = self.c.get("/reset/")
        self.assertEqual(page.status_code, 200)

        page = self.c.post("/reset/", data={"email": self.user.email}, follow=True)
        self.assertEqual(page.status_code, 200)

        self.assertEqual(len(mail.outbox), 1)

        path = re.search(
            "http://testserver(?P<path>[^\\s]+)", mail.outbox[0].body
        ).group("path")
        page = self.c.get(path, follow=True)
        self.assertEqual(page.status_code, 200)

        new_password = "xZZVN6z4TvhFg6S"
        data = {
            "new_password1": new_password,
            "new_password2": new_password,
        }
        page = self.c.post(page.request["PATH_INFO"], data=data, follow=True)
        self.assertEqual(page.status_code, 200)


class LastFeedingPageTestCase(TestCase):
    @classmethod
    def setUpClass(cls):
        super(LastFeedingPageTestCase, cls).setUpClass()
        fake = Faker()
        cls.c = HttpClient()

        fake_user = fake.simple_profile()
        cls.credentials = {
            "username": fake_user["username"],
            "password": fake.password(),
        }
        cls.user = get_user_model().objects.create_user(
            is_superuser=True, email="admin@admin.admin", **cls.credentials
        )
        cls.child = models.Child.objects.create(
            first_name="Spaghetti",
            last_name="Baby",
            birth_date="2024-01-01",
        )
        cls.c.force_login(cls.user)

    def test_last_feeding_page_adds_bottle_feeding(self):
        response = self.c.post(
            "/last-feeding/",
            data={"action": "bottle", "amount": "4.5", "notes": "Bedtime bottle"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/last-feeding/")

        feeding = models.Feeding.objects.get()
        self.assertEqual(feeding.child, self.child)
        self.assertEqual(feeding.amount, 4.5)
        self.assertEqual(feeding.notes, "Bedtime bottle")

    def test_last_feeding_page_adds_medicine_event(self):
        response = self.c.post("/last-feeding/", data={"action": "medicine"})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/last-feeding/")
        self.assertEqual(models.MedicineEvent.objects.count(), 1)
        self.assertEqual(models.MedicineEvent.objects.get().child, self.child)

    def test_last_feeding_page_adds_lay_down_event(self):
        response = self.c.post("/last-feeding/", data={"action": "lay_down"})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/last-feeding/")
        self.assertEqual(models.LayDownEvent.objects.count(), 1)
        self.assertEqual(models.LayDownEvent.objects.get().child, self.child)

    def test_last_feeding_page_adds_manual_medicine_event(self):
        response = self.c.post(
            "/last-feeding/",
            data={
                "action": "medicine_manual",
                "event_time": "2026-07-07T21:15",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/last-feeding/")
        event = models.MedicineEvent.objects.get()
        self.assertEqual(event.child, self.child)
        self.assertEqual(
            timezone.localtime(event.time).strftime("%Y-%m-%dT%H:%M"),
            "2026-07-07T21:15",
        )

    def test_last_feeding_page_adds_manual_lay_down_event(self):
        response = self.c.post(
            "/last-feeding/",
            data={
                "action": "lay_down_manual",
                "event_time": "2026-07-07T19:45",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/last-feeding/")
        event = models.LayDownEvent.objects.get()
        self.assertEqual(event.child, self.child)
        self.assertEqual(
            timezone.localtime(event.time).strftime("%Y-%m-%dT%H:%M"),
            "2026-07-07T19:45",
        )

    def test_last_feeding_page_without_child_creates_nothing(self):
        models.Child.objects.all().delete()

        response = self.c.post("/last-feeding/", data={"action": "medicine"})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/last-feeding/")
        self.assertEqual(models.MedicineEvent.objects.count(), 0)
        self.assertEqual(models.Feeding.objects.count(), 0)
        self.assertEqual(models.LayDownEvent.objects.count(), 0)

    def test_last_feeding_page_hides_medicine_banner_after_medicine_logged(self):
        now = timezone.make_aware(timezone.datetime(2026, 7, 3, 21, 30))

        with patch(
            "babybuddy.last_feeding_views.timezone.now", return_value=now
        ), patch("babybuddy.last_feeding_views.timezone.localtime", return_value=now):
            response = self.c.get("/last-feeding/")
            self.assertContains(response, "REFLUX MEDICINE")

            self.c.post("/last-feeding/", data={"action": "medicine"})
            response = self.c.get("/last-feeding/")
            self.assertNotContains(response, "REFLUX MEDICINE")

    def test_last_feeding_page_hides_bed_banner_after_lay_down_logged(self):
        now = timezone.make_aware(timezone.datetime(2026, 7, 3, 13, 0))
        feeding_start = now - timezone.timedelta(minutes=90)
        models.Feeding.objects.create(
            child=self.child,
            start=feeding_start,
            end=feeding_start,
            type="formula",
            method="bottle",
            amount=4.0,
        )

        with patch(
            "babybuddy.last_feeding_views.timezone.now", return_value=now
        ), patch("babybuddy.last_feeding_views.timezone.localtime", return_value=now):
            response = self.c.get("/last-feeding/")
            self.assertContains(response, "Put down the Spaghetti!")

            self.c.post("/last-feeding/", data={"action": "lay_down"})
            response = self.c.get("/last-feeding/")
            self.assertNotContains(response, "Put down the Spaghetti!")

    def test_last_feeding_page_dismisses_medicine_banner_without_logging(self):
        now = timezone.make_aware(timezone.datetime(2026, 7, 3, 21, 30))

        with patch(
            "babybuddy.last_feeding_views.timezone.now", return_value=now
        ), patch("babybuddy.last_feeding_views.timezone.localtime", return_value=now):
            response = self.c.get("/last-feeding/")
            self.assertContains(response, "REFLUX MEDICINE")

            self.c.post("/last-feeding/", data={"action": "dismiss_medicine"})
            response = self.c.get("/last-feeding/")
            self.assertNotContains(response, "REFLUX MEDICINE")

        self.assertEqual(models.MedicineEvent.objects.count(), 0)
        self.assertEqual(models.BannerDismissal.objects.count(), 1)

    def test_last_feeding_page_dismisses_bed_banner_without_logging(self):
        now = timezone.make_aware(timezone.datetime(2026, 7, 3, 13, 0))
        feeding_start = now - timezone.timedelta(minutes=90)
        feeding = models.Feeding.objects.create(
            child=self.child,
            start=feeding_start,
            end=feeding_start,
            type="formula",
            method="bottle",
            amount=4.0,
        )

        with patch(
            "babybuddy.last_feeding_views.timezone.now", return_value=now
        ), patch("babybuddy.last_feeding_views.timezone.localtime", return_value=now):
            response = self.c.get("/last-feeding/")
            self.assertContains(response, "Put down the Spaghetti!")

            self.c.post(
                "/last-feeding/",
                data={"action": "dismiss_bed", "feeding_id": feeding.id},
            )
            response = self.c.get("/last-feeding/")
            self.assertNotContains(response, "Put down the Spaghetti!")

        self.assertEqual(models.LayDownEvent.objects.count(), 0)
        self.assertEqual(models.BannerDismissal.objects.count(), 1)

    def test_last_feeding_page_hides_bed_banner_during_evening_quiet_hours(self):
        now = timezone.make_aware(timezone.datetime(2026, 7, 3, 21, 30))
        feeding_start = now - timezone.timedelta(minutes=90)
        models.Feeding.objects.create(
            child=self.child,
            start=feeding_start,
            end=feeding_start,
            type="formula",
            method="bottle",
            amount=4.0,
        )

        with patch(
            "babybuddy.last_feeding_views.timezone.now", return_value=now
        ), patch("babybuddy.last_feeding_views.timezone.localtime", return_value=now):
            response = self.c.get("/last-feeding/")
            self.assertNotContains(response, "Put down the Spaghetti!")

    def test_last_feeding_page_feed_alert_thresholds(self):
        feeding_start = timezone.now() - timezone.timedelta(minutes=120)
        models.Feeding.objects.create(
            child=self.child,
            start=feeding_start,
            end=feeding_start,
            type="formula",
            method="bottle",
            amount=4.0,
        )

        response = self.c.get("/last-feeding/")
        self.assertContains(response, "FEED SOON")
        self.assertNotContains(response, "FEED NOW")

        feeding = models.Feeding.objects.get()
        feeding.start = timezone.now() - timezone.timedelta(minutes=210)
        feeding.end = feeding.start
        feeding.save(update_fields=("start", "end"))
        response = self.c.get("/last-feeding/")
        self.assertContains(response, "FEED NOW")
