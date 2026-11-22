import hashlib
import json
from pathlib import Path
import tarfile
import tomllib

root = Path(__file__).resolve().parent.parent
dist = root / "dist"
dist.mkdir(exist_ok=True)
version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
archive = dist / f"wormhole-{version}-operator.tar.gz"
with tarfile.open(archive, "w:gz") as tar:
    for name in ("compose.yaml", ".env.example", "README.md", "THIRD_PARTY_NOTICES.md"):
        tar.add(root / name, arcname=name, recursive=False)
    tar.add(root / "wormhole/cli.py", arcname="wormhole-cli.py", recursive=False)
    for file in sorted((root / "docs").glob("*.md")):
        tar.add(file, arcname="docs/" + file.name, recursive=False)
checksums = {
    p.name: hashlib.sha256(p.read_bytes()).hexdigest()
    for p in sorted(dist.glob("*"))
    if p.is_file() and p.name != "SHA256SUMS"
}
(dist / "SHA256SUMS").write_text(
    "".join(f"{digest}  {name}\n" for name, digest in checksums.items())
)
print(json.dumps({"version": version, "checksums": checksums}, indent=2))
