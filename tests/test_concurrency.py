import hashlib
import os
import threading
from unittest.mock import patch
from django.test import Client, TransactionTestCase
from core.models import Bucket, Grant
from tests.test_archive import ArchiveFixture


class ConcurrencyTests(ArchiveFixture, TransactionTestCase):
    def test_slow_archive_copy_does_not_block_other_chunks_or_logins(self):
        bucket = Bucket.objects.create(name="Media", folder="media")
        Grant.objects.create(user=self.archivist, bucket=bucket)
        self.client.force_login(self.archivist)
        ids = []
        for _ in range(2):
            ids.append(
                self.post(
                    "/api/uploads", {"bucket_id": bucket.pk, "name": "a.bin", "size": 4}
                ).json()["id"]
            )
        digest = hashlib.sha256(b"abcd").hexdigest()
        self.client.put(
            f"/api/uploads/{ids[0]}/chunk?offset=0",
            b"abcd",
            content_type="application/octet-stream",
            HTTP_X_CHUNK_SHA256=digest,
        )
        finalizer = Client()
        finalizer.force_login(self.archivist)
        copying, released = threading.Event(), threading.Event()
        original = os.fdopen
        results = []

        class PausedSource:
            def __init__(self, file):
                self.file = file

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return self.file.__exit__(*args)

            def __getattr__(self, name):
                return getattr(self.file, name)

            def read(self, size=-1):
                copying.set()
                if not released.wait(15):
                    raise TimeoutError("Fixture release timed out")
                return self.file.read(size)

        def opened(fd, mode, *args, **kwargs):
            file = original(fd, mode, *args, **kwargs)
            return (
                PausedSource(file)
                if mode == "rb" and os.fstat(fd).st_size == 4
                else file
            )

        def finish():
            try:
                results.append(finalizer.post(f"/api/uploads/{ids[0]}/finish"))
            finally:
                from django.db import connections

                connections.close_all()

        with patch("core.storage.os.fdopen", side_effect=opened):
            thread = threading.Thread(target=finish)
            thread.start()
            try:
                self.assertTrue(copying.wait(10))
                other = self.client.put(
                    f"/api/uploads/{ids[1]}/chunk?offset=0",
                    b"abcd",
                    content_type="application/octet-stream",
                    HTTP_X_CHUNK_SHA256=digest,
                )
                self.assertEqual(other.status_code, 200)
                login = Client().post(
                    "/login/",
                    {"username": "archivist", "password": "synthetic-password"},
                )
                self.assertEqual(login.status_code, 302)
                Grant.objects.filter(user=self.archivist, bucket=bucket).delete()
            finally:
                released.set()
                thread.join(20)
        self.assertFalse(thread.is_alive())
        self.assertEqual(results[0].status_code, 403)
