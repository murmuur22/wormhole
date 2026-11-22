"""Agent upload CLI; authentication uses environment or an owner-only token file."""

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import urllib.error
import urllib.parse
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Redirect refused")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="wormhole")
    parser.add_argument("--url", required=True)
    parser.add_argument("--token-file")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("buckets")
    upload = sub.add_parser("upload")
    upload.add_argument("file")
    upload.add_argument("--bucket", type=int, required=True)
    args = parser.parse_args(argv)
    try:
        origin = urllib.parse.urlsplit(args.url)
        if (
            origin.username
            or origin.password
            or origin.query
            or origin.fragment
            or origin.path not in {"", "/"}
            or (
                origin.scheme != "https"
                and not (
                    origin.scheme == "http"
                    and origin.hostname in {"localhost", "127.0.0.1", "::1"}
                )
            )
        ):
            raise ValueError("Use an HTTPS origin (HTTP only on loopback)")
        token = os.environ.get("WORMHOLE_TOKEN", "")
        if args.token_file:
            fd = os.open(args.token_file, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "r") as file:
                info = os.fstat(file.fileno())
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_uid != os.getuid()
                    or info.st_mode & 0o077
                    or info.st_nlink != 1
                ):
                    raise ValueError("Token file must be an owner-only regular file")
                token = file.read(256).strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
            raise ValueError("Set WORMHOLE_TOKEN or provide a protected token file")
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), NoRedirect()
        )
        base = args.url.rstrip("/")

        def request(path, method="GET", body=None, extra=None):
            headers = {"Authorization": "Bearer " + token, **(extra or {})}
            if isinstance(body, dict):
                body = json.dumps(body).encode()
                headers["Content-Type"] = "application/json"
            req = urllib.request.Request(
                base + path, data=body, method=method, headers=headers
            )
            try:
                with opener.open(req, timeout=30) as response:
                    raw = response.read(65537)
                    if len(raw) > 65536:
                        raise ValueError("Server response too large")
                    return json.loads(raw)
            except urllib.error.HTTPError as exc:
                raise ValueError(f"Server refused request (HTTP {exc.code})") from None

        if args.command == "buckets":
            result = request("/api/buckets")
        else:
            fd = os.open(args.file, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "rb") as source:
                info = os.fstat(source.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > 2 * 1024**3:
                    raise ValueError("Expected regular file no larger than 2 GiB")
                digest = hashlib.file_digest(source, "sha256").hexdigest()
                source.seek(0)
                upload = request(
                    "/api/uploads",
                    "POST",
                    {
                        "name": os.path.basename(args.file),
                        "size": info.st_size,
                        "bucket_id": args.bucket,
                        "sha256": digest,
                    },
                )
                uid = upload["id"]
                if (
                    not re.fullmatch("[0-9a-f-]{36}", uid)
                    or type(upload["chunk_bytes"]) is not int
                    or not 1 <= upload["chunk_bytes"] <= 524288
                ):
                    raise ValueError("Invalid upload contract")
                offset = 0
                try:
                    while block := source.read(upload["chunk_bytes"]):
                        if offset + len(block) > info.st_size:
                            raise ValueError("File changed during upload")
                        progress = request(
                            f"/api/uploads/{uid}/chunk?offset={offset}",
                            "PUT",
                            block,
                            {
                                "Content-Type": "application/octet-stream",
                                "X-Chunk-SHA256": hashlib.sha256(block).hexdigest(),
                            },
                        )
                        offset += len(block)
                        if progress.get("offset") != offset:
                            raise ValueError("Invalid server offset")
                    result = request(f"/api/uploads/{uid}/finish", "POST")
                    if (
                        result.get("sha256") != digest
                        or result.get("size") != info.st_size
                        or result.get("state") != "complete"
                    ):
                        raise ValueError("Receipt integrity mismatch")
                except Exception:
                    try:
                        request(f"/api/uploads/{uid}", "DELETE")
                    except Exception:
                        pass
                    raise
        print(json.dumps(result))
        return 0
    except (ValueError, OSError, KeyError, urllib.error.URLError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
