from django.test import TestCase, override_settings
from tests.test_archive import ArchiveFixture


class AdminTests(ArchiveFixture, TestCase):
    @override_settings(ROOT_URLCONF="wormhole.urls_admin")
    def test_admin_creates_disables_and_monitors_account(self):
        self.client.force_login(self.admin)
        result = self.post(
            "/admin/api/accounts",
            {"username": "collector", "password": "A-long-synthetic-password!"},
        )
        self.assertEqual(result.status_code, 201)
        user_id = result.json()["id"]
        result = self.post(
            "/admin/api/accounts/status", {"user_id": user_id, "active": False}
        )
        self.assertEqual(result.status_code, 200)
        state = self.client.get("/admin/api/state").json()
        self.assertFalse(
            next(u for u in state["accounts"] if u["id"] == user_id)["active"]
        )
        self.assertEqual(state["uploads"], [])

    @override_settings(ROOT_URLCONF="wormhole.urls_admin")
    def test_admin_dashboard_is_real_and_portal_cannot_access_it(self):
        self.client.force_login(self.admin)
        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Buckets &amp; access")
        with override_settings(ROOT_URLCONF="wormhole.urls_portal"):
            self.assertEqual(self.client.get("/admin/").status_code, 404)

    def test_portal_requires_login_and_has_real_upload_controls(self):
        self.assertEqual(self.client.get("/").status_code, 302)
        self.client.force_login(self.archivist)
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="toss"')
        self.assertNotContains(response, "Try a sample")
