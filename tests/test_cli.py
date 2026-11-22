import hashlib
import json
import os
import secrets
import subprocess
import sys
from django.conf import settings
from django.test import LiveServerTestCase
from core.models import Bucket, Grant, ApiToken
from tests.test_archive import ArchiveFixture


class CliTests(ArchiveFixture, LiveServerTestCase):
    def test_real_cli_lists_and_archives_identical_bytes(self):
        bucket = Bucket.objects.create(name="Media", folder="cli-media")
        Grant.objects.create(user=self.archivist, bucket=bucket)
        raw = secrets.token_urlsafe(32)
        token = ApiToken.objects.create(
            user=self.archivist,
            label="Fixture",
            digest=hashlib.sha256(raw.encode()).hexdigest(),
        )
        token.buckets.add(bucket)
        environment = {**os.environ, "WORMHOLE_TOKEN": raw}
        source = settings.STATE_DIR / "synthetic.bin"
        source.write_bytes(b"cli synthetic bytes\x00\xff" * 60000)
        listed = subprocess.run(
            [
                sys.executable,
                "-m",
                "wormhole.cli",
                "--url",
                self.live_server_url,
                "buckets",
            ],
            env=environment,
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertEqual(
            json.loads(listed.stdout)["buckets"], [{"id": bucket.pk, "name": "Media"}]
        )
        uploaded = subprocess.run(
            [
                sys.executable,
                "-m",
                "wormhole.cli",
                "--url",
                self.live_server_url,
                "upload",
                str(source),
                "--bucket",
                str(bucket.pk),
            ],
            env=environment,
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(uploaded.returncode, 0, uploaded.stderr)
        receipt = json.loads(uploaded.stdout)
        self.assertEqual(
            receipt["sha256"], hashlib.sha256(source.read_bytes()).hexdigest()
        )
        dest = list((settings.ARCHIVE_ROOT / "cli-media").iterdir())
        self.assertEqual(dest[0].read_bytes(), source.read_bytes())
        self.assertNotIn(
            raw, listed.stdout + listed.stderr + uploaded.stdout + uploaded.stderr
        )

    def test_cli_refuses_unencrypted_remote_origin(self):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "wormhole.cli",
                "--url",
                "http://example.com",
                "buckets",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("HTTPS", result.stderr)
