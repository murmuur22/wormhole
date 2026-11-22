import hashlib
from django.test import Client, TestCase, override_settings
from core.models import Bucket, Grant, ApiToken
from tests.test_archive import ArchiveFixture


class TokenTests(ArchiveFixture, TestCase):
    def test_scoped_token_uploads_without_session_and_revokes(self):
        bucket = Bucket.objects.create(name="Media", folder="media")
        other = Bucket.objects.create(name="Private", folder="private")
        Grant.objects.create(user=self.archivist, bucket=bucket)
        Grant.objects.create(user=self.archivist, bucket=other)
        self.client.force_login(self.admin)
        with override_settings(ROOT_URLCONF="wormhole.urls_admin"):
            result = self.post(
                "/admin/api/tokens",
                {
                    "user_id": self.archivist.pk,
                    "label": "Indexer",
                    "bucket_ids": [bucket.pk],
                },
            )
        self.assertEqual(result.status_code, 201)
        token = result.json()["token"]
        client = Client(enforce_csrf_checks=True, HTTP_AUTHORIZATION="Bearer " + token)
        self.assertEqual(
            client.get("/api/buckets").json()["buckets"],
            [{"id": bucket.pk, "name": "Media"}],
        )
        import json

        result = client.post(
            "/api/uploads",
            json.dumps({"bucket_id": bucket.pk, "name": "empty.bin", "size": 0}),
            content_type="application/json",
        )
        self.assertEqual(result.status_code, 201)
        uid = result.json()["id"]
        denied = client.post(
            "/api/uploads",
            json.dumps({"bucket_id": other.pk, "name": "x", "size": 0}),
            content_type="application/json",
        )
        self.assertEqual(denied.status_code, 403)
        result = client.post(f"/api/uploads/{uid}/finish")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["sha256"], hashlib.sha256(b"").hexdigest())
        self.client.force_login(self.archivist)
        other_upload = self.post(
            "/api/uploads",
            {"bucket_id": other.pk, "name": "outside-token-scope", "size": 0},
        )
        self.assertEqual(other_upload.status_code, 201)
        self.assertEqual(
            client.delete("/api/uploads/" + other_upload.json()["id"]).status_code, 403
        )
        ApiToken.objects.update(active=False)
        self.assertEqual(client.get("/api/buckets").status_code, 401)

    def test_invalid_bearer_does_not_fall_back_to_cookie(self):
        self.client.force_login(self.archivist)
        self.assertEqual(
            self.client.get(
                "/api/buckets", HTTP_AUTHORIZATION="Bearer invalid"
            ).status_code,
            401,
        )
