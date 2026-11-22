import json
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings


class ArchiveFixture:
    def setUp(self):
        import tempfile
        from pathlib import Path
        from django.conf import settings

        fixture = tempfile.TemporaryDirectory(
            dir=settings.STATE_DIR.parent, prefix="archive-fixture-"
        )
        self.addCleanup(fixture.cleanup)
        root = Path(fixture.name)
        (root / "state").mkdir()
        (root / "archive").mkdir()
        (root / "archive" / ".wormhole-archive-id").write_text(
            settings.ARCHIVE_ID + "\n"
        )
        override = override_settings(
            STATE_DIR=root / "state", ARCHIVE_ROOT=root / "archive"
        )
        override.enable()
        self.addCleanup(override.disable)
        self.admin = get_user_model().objects.create_user(
            "operator", password="synthetic-password", is_staff=True, is_superuser=True
        )
        self.archivist = get_user_model().objects.create_user(
            "archivist", password="synthetic-password"
        )

    def post(self, path, data):
        return self.client.post(path, json.dumps(data), content_type="application/json")


class ArchiveFlowTests(ArchiveFixture, TestCase):
    def test_shared_bucket_upload_grants_are_explicit(self):
        self.client.force_login(self.admin)
        with override_settings(ROOT_URLCONF="wormhole.urls_admin"):
            response = self.post(
                "/admin/api/buckets", {"name": "Audio", "folder": "audio"}
            )
            self.assertEqual(response.status_code, 201)
            bucket = response.json()["id"]
            response = self.post(
                "/admin/api/grants",
                {"user_id": self.archivist.pk, "bucket_id": bucket, "allowed": True},
            )
            self.assertEqual(response.status_code, 200)
        self.client.force_login(self.archivist)
        response = self.client.get("/api/buckets")
        self.assertEqual(response.json()["buckets"], [{"id": bucket, "name": "Audio"}])
        other = get_user_model().objects.create_user("other")
        self.client.force_login(other)
        self.assertEqual(self.client.get("/api/buckets").json()["buckets"], [])

    def test_toss_stores_exact_bytes_with_a_receipt(self):
        import hashlib
        from django.conf import settings
        from core.models import Bucket, Grant

        bucket = Bucket.objects.create(name="Audio", folder="audio")
        Grant.objects.create(user=self.archivist, bucket=bucket)
        self.client.force_login(self.archivist)
        content = b"synthetic media bytes\x00\xff"
        digest = hashlib.sha256(content).hexdigest()
        response = self.post(
            "/api/uploads",
            {
                "bucket_id": bucket.pk,
                "name": "recording.bin",
                "size": len(content),
                "sha256": digest,
            },
        )
        self.assertEqual(response.status_code, 201)
        upload_id = response.json()["id"]
        response = self.client.put(
            f"/api/uploads/{upload_id}/chunk?offset=0",
            content,
            content_type="application/octet-stream",
            HTTP_X_CHUNK_SHA256=digest,
        )
        self.assertEqual(response.status_code, 200)
        response = self.post(f"/api/uploads/{upload_id}/finish", {})
        self.assertEqual(response.status_code, 200)
        receipt = response.json()
        self.assertEqual(receipt["sha256"], digest)
        self.assertEqual(receipt["size"], len(content))
        stored = list((settings.ARCHIVE_ROOT / "audio").glob("*"))
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0].read_bytes(), content)
        self.assertEqual(
            self.post(f"/api/uploads/{upload_id}/finish", {}).json(), receipt
        )

    def test_nested_destinations_require_their_own_grants(self):
        from core.models import Bucket, Grant

        parent = Bucket.objects.create(name="Audio", folder="audio")
        child = Bucket.objects.create(
            name="Recordings", folder="audio/recordings", parent=parent
        )
        Grant.objects.create(user=self.archivist, bucket=parent)
        self.client.force_login(self.archivist)
        self.assertEqual(
            self.post(
                "/api/uploads", {"bucket_id": child.pk, "name": "empty", "size": 0}
            ).status_code,
            403,
        )
        Grant.objects.create(user=self.archivist, bucket=child)
        self.assertIn(
            {"id": child.pk, "name": "Audio / Recordings"},
            self.client.get("/api/buckets").json()["buckets"],
        )
        uid = self.post(
            "/api/uploads", {"bucket_id": child.pk, "name": "empty", "size": 0}
        ).json()["id"]
        self.assertEqual(self.post(f"/api/uploads/{uid}/finish", {}).status_code, 200)

    def test_nonadmin_cannot_configure_destinations(self):
        self.client.force_login(self.archivist)
        with override_settings(ROOT_URLCONF="wormhole.urls_admin"):
            self.assertEqual(
                self.post(
                    "/admin/api/buckets", {"name": "Bad", "folder": "../escape"}
                ).status_code,
                403,
            )
