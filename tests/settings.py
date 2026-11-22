import os
import tempfile
from pathlib import Path

import atexit
import shutil

scratch = Path(os.environ.get("WORMHOLE_TEST_TMPDIR", tempfile.gettempdir())).resolve()
TEST_ROOT = Path(tempfile.mkdtemp(prefix="wormhole-test-", dir=scratch)).resolve()
atexit.register(shutil.rmtree, TEST_ROOT, ignore_errors=True)
(TEST_ROOT / "state").mkdir()
(TEST_ROOT / "archive").mkdir()
os.environ["WORMHOLE_SECRET_KEY"] = "synthetic-test-key-not-for-real-deployments"
os.environ["WORMHOLE_STATE_DIR"] = str(TEST_ROOT / "state")
os.environ["WORMHOLE_ARCHIVE_ROOT"] = str(TEST_ROOT / "archive")
os.environ["WORMHOLE_ARCHIVE_ID"] = "1" * 32
(TEST_ROOT / "archive" / ".wormhole-archive-id").write_text("1" * 32 + "\n")
from wormhole.settings import *  # noqa: E402,F403

ALLOWED_HOSTS = ["testserver", "127.0.0.1", "localhost"]
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
