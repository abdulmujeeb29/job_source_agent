"""Archive the source matching an evaluation freeze, excluding credentials/artifacts."""
import argparse
import hashlib
import json
import zipfile
from pathlib import Path

from evaluation.run import fingerprint

parser = argparse.ArgumentParser()
parser.add_argument("directory", type=Path)
parser.add_argument("archive", type=Path)
args = parser.parse_args()
frozen = json.loads((args.directory / "freeze.json").read_text())["configuration"]
if fingerprint() != frozen["source_sha256"]:
    raise SystemExit("Source does not match this evaluation freeze.")
files = sorted([*Path("app").rglob("*.py"), *Path("app/static").glob("*"),
                *Path("evaluation").glob("*.py"), Path("pyproject.toml"), Path("uv.lock"), Path("Dockerfile")])
with zipfile.ZipFile(args.archive, "x", compression=zipfile.ZIP_DEFLATED) as output:
    for file in files:
        output.write(file)
hashes = {str(p.relative_to(args.directory)): hashlib.sha256(p.read_bytes()).hexdigest()
          for p in sorted(args.directory.rglob("*")) if p.is_file()}
args.archive.with_suffix(".artifacts.sha256.json").write_text(json.dumps(hashes, indent=2))
print("Archived evaluated source and artifact hashes.")
