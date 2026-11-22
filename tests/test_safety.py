import hashlib
import json
from unittest.mock import patch
from django.conf import settings
from django.db import DatabaseError
from django.test import Client, TestCase, override_settings
from core.models import Bucket, Grant, Upload
from tests.test_archive import ArchiveFixture


class UploadSafetyTests(ArchiveFixture, TestCase):
    def setUp(self):
        super().setUp()
        self.bucket = Bucket.objects.create(name="Media", folder="media")
        self.grant = Grant.objects.create(user=self.archivist, bucket=self.bucket)
        self.client.force_login(self.archivist)
        self.digest = hashlib.sha256(b"abcd").hexdigest()

    def begin(self, **extra):
        return self.post(
            "/api/uploads",
            dict(bucket_id=self.bucket.pk, name="a.bin", size=4, **extra),
        )

    def prepare(self):
        result = self.begin()
        self.assertEqual(result.status_code, 201)
        uid = result.json()["id"]
        result = self.client.put(
            f"/api/uploads/{uid}/chunk?offset=0",
            b"abcd",
            content_type="application/octet-stream",
            HTTP_X_CHUNK_SHA256=self.digest,
        )
        self.assertEqual(result.status_code, 200)
        return uid

    def test_revocation_prevents_finalize(self):
        uid = self.prepare()
        self.grant.delete()
        self.assertEqual(self.post(f"/api/uploads/{uid}/finish", {}).status_code, 403)
        self.assertFalse((settings.ARCHIVE_ROOT / "media").exists())

    def test_symlink_destination_is_refused(self):
        uid = self.prepare()
        (settings.ARCHIVE_ROOT / "media").symlink_to(
            settings.STATE_DIR, target_is_directory=True
        )
        self.assertEqual(self.post(f"/api/uploads/{uid}/finish", {}).status_code, 503)
        self.assertEqual(list(settings.STATE_DIR.glob("*a.bin")), [])

    def test_mismatched_checksum_never_commits(self):
        uid = self.begin(sha256="0" * 64).json()["id"]
        self.client.put(
            f"/api/uploads/{uid}/chunk?offset=0",
            b"abcd",
            content_type="application/octet-stream",
            HTTP_X_CHUNK_SHA256=self.digest,
        )
        self.assertEqual(self.post(f"/api/uploads/{uid}/finish", {}).status_code, 409)
        self.assertEqual(list((settings.ARCHIVE_ROOT / "media").iterdir()), [])

    def test_database_save_failure_removes_destination(self):
        uid = self.prepare()
        with patch.object(
            Upload, "save", side_effect=DatabaseError("synthetic failure")
        ):
            self.assertEqual(
                self.post(f"/api/uploads/{uid}/finish", {}).status_code, 503
            )
        self.assertEqual(list((settings.ARCHIVE_ROOT / "media").iterdir()), [])
        self.assertEqual(Upload.objects.get(pk=uid).state, "pending")

    def test_corrupt_chunk_and_duplicate_offset_refused(self):
        uid = self.begin().json()["id"]
        path = f"/api/uploads/{uid}/chunk?offset=0"
        self.assertEqual(
            self.client.put(
                path,
                b"abcd",
                content_type="application/octet-stream",
                HTTP_X_CHUNK_SHA256="0" * 64,
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.put(
                path,
                b"abcd",
                content_type="application/octet-stream",
                HTTP_X_CHUNK_SHA256=self.digest,
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.put(
                path,
                b"abcd",
                content_type="application/octet-stream",
                HTTP_X_CHUNK_SHA256=self.digest,
            ).status_code,
            409,
        )

    def test_traversal_and_oversized_metadata_refused(self):
        for name in ("../evil", "a/b", "a\\b", "\x00"):
            self.assertEqual(
                self.post(
                    "/api/uploads",
                    {"bucket_id": self.bucket.pk, "name": name, "size": 4},
                ).status_code,
                400,
            )
        self.assertEqual(
            self.post(
                "/api/uploads",
                {
                    "bucket_id": self.bucket.pk,
                    "name": "big",
                    "size": settings.MAX_FILE_BYTES + 1,
                },
            ).status_code,
            400,
        )

    def test_foreign_user_cannot_access_upload(self):
        uid = self.prepare()
        self.client.force_login(self.admin)
        self.assertEqual(self.post(f"/api/uploads/{uid}/finish", {}).status_code, 404)

    def test_session_mutations_require_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.archivist)
        self.assertEqual(
            client.post(
                "/api/uploads",
                json.dumps({"bucket_id": self.bucket.pk, "name": "x", "size": 0}),
                content_type="application/json",
            ).status_code,
            403,
        )

    def test_admin_rejects_traversal_and_missing_parent(self):
        self.client.force_login(self.admin)
        with override_settings(ROOT_URLCONF="wormhole.urls_admin"):
            self.assertEqual(
                self.post(
                    "/admin/api/buckets", {"name": "bad", "folder": "../escape"}
                ).status_code,
                400,
            )
            self.assertEqual(
                self.post(
                    "/admin/api/buckets",
                    {"name": "bad", "folder": "child", "parent_id": 999},
                ).status_code,
                400,
            )

    def test_missing_archive_marker_refuses_begin_and_finalize(self):
        uid = self.prepare()
        marker = settings.ARCHIVE_ROOT / ".wormhole-archive-id"
        if marker.exists():
            marker.unlink()
        self.assertEqual(self.begin().status_code, 503)
        self.assertEqual(self.post(f"/api/uploads/{uid}/finish", {}).status_code, 503)
        self.assertFalse((settings.ARCHIVE_ROOT / "media").exists())

    def test_health_refuses_missing_archive(self):
        (settings.ARCHIVE_ROOT / ".wormhole-archive-id").unlink()
        self.assertEqual(self.client.get("/health").status_code, 503)

    def test_cleanup_expires_partial_transfers(self):
        from core import storage
        from datetime import timedelta
        from django.utils import timezone

        uid = self.prepare()
        Upload.objects.filter(pk=uid).update(created=timezone.now() - timedelta(days=2))
        self.assertTrue(callable(getattr(storage, "cleanup_expired", None)))
        storage.cleanup_expired()
        self.assertEqual(Upload.objects.get(pk=uid).state, "expired")
        self.assertFalse((settings.STATE_DIR / "parts" / uid).exists())

    def test_archive_capability_probe_cleans_its_files(self):
        from django.core.management import call_command, get_commands

        self.assertIn("check_archive", get_commands())
        before = set(settings.ARCHIVE_ROOT.iterdir())
        call_command("check_archive")
        self.assertEqual(set(settings.ARCHIVE_ROOT.iterdir()), before)

    def test_one_account_cannot_reserve_the_entire_global_budget(self):
        first = self.post(
            "/api/uploads",
            {
                "bucket_id": self.bucket.pk,
                "name": "large",
                "size": settings.MAX_FILE_BYTES,
            },
        )
        self.assertEqual(first.status_code, 201)
        second = self.post(
            "/api/uploads", {"bucket_id": self.bucket.pk, "name": "extra", "size": 1}
        )
        self.assertEqual(second.status_code, 429)

    def test_crash_leftover_requires_reconciliation_without_overwrite(self):
        uid = self.prepare()
        directory = settings.ARCHIVE_ROOT / "media"
        directory.mkdir()
        incoming = directory / (".incoming-" + uid)
        incoming.write_bytes(b"uncertain previous write")
        self.assertEqual(self.post(f"/api/uploads/{uid}/finish", {}).status_code, 409)
        self.assertEqual(incoming.read_bytes(), b"uncertain previous write")
        self.assertEqual(Upload.objects.get(pk=uid).state, "reconcile")

    def test_cancel_removes_partial_file(self):
        uid = self.prepare()
        response = self.client.delete(f"/api/uploads/{uid}")
        self.assertEqual(response.status_code, 200)
        self.assertFalse((settings.STATE_DIR / "parts" / uid).exists())
        self.assertEqual(self.post(f"/api/uploads/{uid}/finish", {}).status_code, 409)
