# -*- coding: utf-8 -*-
from django.test import TestCase
from django.test import Client as HttpClient
from django.contrib.auth import get_user_model
from django.core.management import call_command

from faker import Faker

from core.models import Child


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
            is_superuser=True, **cls.credentials
        )

        cls.c.login(**cls.credentials)

    def test_dashboard_views(self):
        page = self.c.get("/dashboard/")
        self.assertEqual(page.url, "/welcome/")

        call_command("fake", verbosity=0, children=1, days=1)
        child = Child.objects.first()
        page = self.c.get("/dashboard/")
        self.assertEqual(page.url, "/children/{}/dashboard/".format(child.slug))

        page = self.c.get("/dashboard/")
        self.assertEqual(page.url, "/children/{}/dashboard/".format(child.slug))
        # Test the actual child dashboard (including cards).
        # TODO: Test cards more granularly.
        page = self.c.get("/children/{}/dashboard/".format(child.slug))
        self.assertEqual(page.status_code, 200)

        Child.objects.create(
            first_name="Second", last_name="Child", birth_date="2000-01-01"
        )
        page = self.c.get("/dashboard/")
        self.assertEqual(page.status_code, 200)

    def test_child_dashboard_feeding_totals(self):
        from django.utils import timezone
        from core.models import Feeding

        child = Child.objects.create(
            first_name="Arleti", last_name="Spagetti", birth_date="2024-01-01"
        )
        other = Child.objects.create(
            first_name="Another", last_name="Baby", birth_date="2024-01-01"
        )
        now = timezone.now()
        for owner, amount in [(child, 6.25), (other, 99)]:
            Feeding.objects.create(
                child=owner,
                start=now,
                end=now,
                amount=amount,
                type="formula",
                method="bottle",
            )
        page = self.c.get(f"/children/{child.slug}/dashboard/")
        self.assertContains(page, "Feeding totals")
        self.assertContains(page, "Today: 6.25 oz")
        self.assertNotContains(page, "All time")
        self.assertContains(page, "Daily ounces")
