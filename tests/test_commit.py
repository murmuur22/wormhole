from unittest.mock import patch
import hashlib
from django.conf import settings
from django.db import connection, DatabaseError
from django.test import TransactionTestCase
from core.models import Bucket, Grant, Upload
from tests.test_archive import ArchiveFixture


class CommitTests(ArchiveFixture, TransactionTestCase):
    def test_commit_failure_does_not_leave_published_file(self):
        bucket = Bucket.objects.create(name="Commit", folder="commit")
        Grant.objects.create(user=self.archivist, bucket=bucket)
        self.client.force_login(self.archivist)
        uid = self.post(
            "/api/uploads", {"bucket_id": bucket.pk, "name": "payload.bin", "size": 4}
        ).json()["id"]
        self.assertEqual(
            self.client.put(
                f"/api/uploads/{uid}/chunk?offset=0",
                b"abcd",
                content_type="application/octet-stream",
                HTTP_X_CHUNK_SHA256=hashlib.sha256(b"abcd").hexdigest(),
            ).status_code,
            200,
        )
        original_commit = connection.commit
        count = 0

        def fail_publication_commit():
            nonlocal count
            count += 1
            if count == 2:
                raise DatabaseError("synthetic final commit error")
            return original_commit()

        with patch.object(connection, "commit", side_effect=fail_publication_commit):
            response = self.post(f"/api/uploads/{uid}/finish", {})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(list((settings.ARCHIVE_ROOT / "commit").iterdir()), [])
        self.assertEqual(Upload.objects.get(pk=uid).state, "pending")
