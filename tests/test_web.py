from django.test import TestCase, override_settings


class SurfaceTests(TestCase):
    def test_health_reports_version_on_both_surfaces(self):
        for urlconf in ("wormhole.urls_portal", "wormhole.urls_admin"):
            with override_settings(ROOT_URLCONF=urlconf):
                response = self.client.get("/health")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["version"], "0.1.0")

    def test_upload_api_requires_real_authentication(self):
        response = self.client.get("/api/buckets", HTTP_X_RELAY_USER="admin")
        self.assertEqual(response.status_code, 401)

    def test_login_is_csrf_protected(self):
        from django.test import Client

        response = Client(enforce_csrf_checks=True).post(
            "/login/", {"username": "a", "password": "b"}
        )
        self.assertEqual(response.status_code, 403)

    def test_login_rate_limit_and_host_validation(self):
        for _ in range(5):
            self.assertEqual(
                self.client.post(
                    "/login/", {"username": "missing", "password": "wrong"}
                ).status_code,
                200,
            )
        self.assertEqual(
            self.client.post(
                "/login/", {"username": "missing", "password": "wrong"}
            ).status_code,
            429,
        )
        self.assertEqual(
            self.client.get("/health", HTTP_HOST="untrusted.example").status_code, 400
        )

    def test_username_variants_share_login_throttle(self):
        for _ in range(5):
            self.assertEqual(
                self.client.post(
                    "/login/", {"username": "missing", "password": "wrong"}
                ).status_code,
                200,
            )
        for username in [
            " missing",
            "missing\t",
            "\u3000missing",
            "ｍｉｓｓｉｎｇ",
            "MISSING",
        ]:
            self.assertEqual(
                self.client.post(
                    "/login/", {"username": username, "password": "wrong"}
                ).status_code,
                429,
            )

    def test_shared_proxy_peer_does_not_lock_out_all_accounts(self):
        for index in range(52):
            self.assertEqual(
                self.client.post(
                    "/login/", {"username": f"missing-{index}", "password": "wrong"}
                ).status_code,
                200,
            )

    def test_portal_never_registers_admin(self):
        self.assertEqual(self.client.get("/admin/").status_code, 404)
