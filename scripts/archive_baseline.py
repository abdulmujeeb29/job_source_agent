"""Preserve the evaluated source and artifact hashes before post-fix development."""
import hashlib
import json
import zipfile
from pathlib import Path

from evaluation.run import fingerprint

folder = Path("evaluation/results")
frozen = json.loads((folder / "freeze.json").read_text())["configuration"]
if fingerprint() != frozen["source_sha256"]:
    raise SystemExit("Current source does not match the baseline freeze; refusing to label it baseline.")
archive = Path("evaluation/baseline-source.zip")
files = sorted([*Path("app").rglob("*.py"), *Path("app/static").glob("*"),
                *Path("evaluation").glob("*.py"), Path("pyproject.toml"), Path("uv.lock"), Path("Dockerfile")])
with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as output:
    for file in files:
        output.write(file)
hashes = {str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
          for p in sorted(folder.rglob("*")) if p.is_file()}
Path("evaluation/baseline-artifacts.sha256.json").write_text(json.dumps(hashes, indent=2))
print("Archived baseline source and hashes; original evaluation artifacts remain in place.")
