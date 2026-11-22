"""Create synthetic browser fixtures outside the checkout; emit local test configuration."""

import json
import os
from pathlib import Path
import tempfile
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
fixture = Path(
    tempfile.mkdtemp(
        prefix="wormhole-browser-",
        dir=os.environ.get("WORMHOLE_TEST_TMPDIR", tempfile.gettempdir()),
    )
).resolve()
(fixture / "state").mkdir()
(fixture / "archive").mkdir()
identity = "2" * 32
(fixture / "archive" / ".wormhole-archive-id").write_text(identity + "\n")
env = {
    "WORMHOLE_STATE_DIR": str(fixture / "state"),
    "WORMHOLE_ARCHIVE_ROOT": str(fixture / "archive"),
    "WORMHOLE_ARCHIVE_ID": identity,
    "WORMHOLE_SECRET_KEY": "synthetic-browser-secret-not-a-real-account",
    "WORMHOLE_SECURE_COOKIES": "0",
    "WORMHOLE_HOSTS": "127.0.0.1,localhost",
    "DJANGO_SETTINGS_MODULE": "wormhole.settings",
}
os.environ.update(env)
import django  # noqa: E402

django.setup()
from django.core.management import call_command  # noqa: E402
from django.contrib.auth import get_user_model  # noqa: E402

call_command("migrate", interactive=False, verbosity=0)
get_user_model().objects.create_superuser(
    "operator", password="synthetic-browser-password-473!"
)
(ROOT / ".local").mkdir(exist_ok=True)
(ROOT / ".local" / "browser-fixture.json").write_text(
    json.dumps(
        {
            "root": str(fixture),
            "env": env,
            "username": "operator",
            "password": "synthetic-browser-password-473!",
        }
    )
)
print("Created synthetic browser fixture; no real accounts or media used.")
