"""Exercise the actual Docker image with disposable state, not production shares."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.error
import uuid


def main():
    image = sys.argv[1]
    prefix = "wormhole-test-" + uuid.uuid4().hex[:10]
    started = []
    report = []
    with tempfile.TemporaryDirectory(
        prefix=prefix, dir=os.environ.get("WORMHOLE_TEST_TMPDIR", tempfile.gettempdir())
    ) as temporary:
        root = Path(temporary).resolve()
        root.chmod(0o755)
        for name in ("state", "archive"):
            (root / name).mkdir(mode=0o777)
            (root / name).chmod(0o777)
        identity = "3" * 32
        marker = root / "archive/.wormhole-archive-id"
        marker.write_text(identity + "\n")
        environment = {
            "WORMHOLE_STATE_DIR": "/state",
            "WORMHOLE_ARCHIVE_ROOT": "/archive",
            "WORMHOLE_ARCHIVE_ID": identity,
            "WORMHOLE_SECRET_KEY": "synthetic-container-secret-not-a-real-account",
            "WORMHOLE_SECURE_COOKIES": "0",
        }
        common = [
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges:true",
            "--tmpfs",
            "/tmp:size=67108864,mode=1777",
            "-v",
            f"{root}/state:/state",
            "-v",
            f"{root}/archive:/archive",
        ]
        for key, value in environment.items():
            common += ["-e", f"{key}={value}"]

        def run(args, **kwargs):
            return subprocess.run(
                ["docker", *args],
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
                **kwargs,
            )

        try:
            run(
                [
                    "run",
                    "--rm",
                    *common,
                    image,
                    "python",
                    "manage.py",
                    "migrate",
                    "--noinput",
                ]
            )
            seed = """import os,django,hashlib,secrets,json
os.environ.setdefault('DJANGO_SETTINGS_MODULE','wormhole.settings')
django.setup()
from django.contrib.auth import get_user_model
from core.models import Bucket,Grant,ApiToken
u=get_user_model().objects.create_user('container-fixture')
b=Bucket.objects.create(name='Media',folder='media')
Grant.objects.create(user=u,bucket=b)
raw=secrets.token_urlsafe(32)
t=ApiToken.objects.create(user=u,label='Fixture',digest=hashlib.sha256(raw.encode()).hexdigest())
t.buckets.add(b)
print(json.dumps({'token':raw,'bucket':b.pk}))
"""
            credentials = json.loads(
                run(
                    ["run", "--rm", "-i", *common, image, "python", "-"], input=seed
                ).stdout
            )
            urls = []
            for surface in ("portal", "admin"):
                name = prefix + "-" + surface
                run(
                    [
                        "run",
                        "-d",
                        "--name",
                        name,
                        *common,
                        "-e",
                        "WORMHOLE_SURFACE=" + surface,
                        "-p",
                        "127.0.0.1::8000",
                        image,
                    ]
                )
                started.append(name)
                inspected = json.loads(run(["inspect", name]).stdout)[0]
                assert inspected["HostConfig"]["ReadonlyRootfs"]
                port = inspected["NetworkSettings"]["Ports"]["8000/tcp"][0]["HostPort"]
                urls.append("http://127.0.0.1:" + port)

            def health(url):
                with urllib.request.urlopen(url + "/health", timeout=4) as response:
                    return json.load(response)

            for surface, url in zip(("portal", "admin"), urls):
                for attempt in range(80):
                    try:
                        observed = health(url)
                        if (
                            observed["status"] == "ok"
                            and observed["surface"] == surface
                            and observed["version"] == "0.1.0"
                        ):
                            break
                    except (OSError, ValueError):
                        pass
                    time.sleep(0.25)
                else:
                    raise RuntimeError("Container did not become healthy")
            report.append(
                "Both non-root read-only Docker surfaces report version 0.1.0 with real database and archive marker"
            )
            try:
                urllib.request.urlopen(urls[0] + "/admin/", timeout=4)
            except urllib.error.HTTPError as error:
                assert error.code == 404
            else:
                raise AssertionError("Admin route exposed on portal")
            payload = root / "synthetic.bin"
            payload.write_bytes(bytes(range(251)) * 5000)
            client_env = {**os.environ, "WORMHOLE_TOKEN": credentials["token"]}
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "wormhole.cli",
                    "--url",
                    urls[0],
                    "upload",
                    str(payload),
                    "--bucket",
                    str(credentials["bucket"]),
                ],
                env=client_env,
                check=True,
                capture_output=True,
                text=True,
                timeout=60,
            )
            receipt = json.loads(result.stdout)
            assert receipt["sha256"] == hashlib.sha256(payload.read_bytes()).hexdigest()
            files = list((root / "archive/media").iterdir())
            assert len(files) == 1 and files[0].read_bytes() == payload.read_bytes()
            report.append(
                "Host CLI uploads multiple chunks into actual container and exact mounted bytes match receipt"
            )
            run(["restart", started[0]])
            for attempt in range(80):
                try:
                    if health(urls[0])["status"] == "ok":
                        break
                except OSError:
                    pass
                time.sleep(0.25)
            else:
                raise RuntimeError("Container restart failed")
            assert files[0].read_bytes() == payload.read_bytes()
            report.append(
                "Container restart preserves archive and local account database"
            )
            marker.unlink()
            try:
                health(urls[0])
            except urllib.error.HTTPError as error:
                assert error.code == 503
            else:
                raise AssertionError("Missing archive marker reported healthy")
            report.append(
                "Missing archive identity fails closed rather than writing into an empty mount"
            )
            Path(".local").mkdir(exist_ok=True)
            Path(".local/container-verification.json").write_text(
                json.dumps(
                    {"image": image, "checks": report, "real_smb_mount_tested": False},
                    indent=2,
                )
            )
            print(json.dumps({"checks": report, "image": image}, indent=2))
        finally:
            for name in started:
                subprocess.run(
                    ["docker", "rm", "-f", name], capture_output=True, timeout=30
                )


if __name__ == "__main__":
    main()
