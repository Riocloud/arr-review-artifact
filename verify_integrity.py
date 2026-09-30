"""Verify supplied artifact hashes; no provider calls or writes."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main():
    manifest = json.loads((ROOT / "MANIFEST.json").read_text())
    errors = []
    for row in manifest["files"]:
        rel = Path(row["path"])
        path = ROOT / rel
        if rel.is_absolute() or ".." in rel.parts or not path.is_file() or path.is_symlink():
            errors.append(str(rel) + ": missing or invalid")
            continue
        data = path.read_bytes()
        if len(data) != row["bytes"] or hashlib.sha256(data).hexdigest() != row["sha256"]:
            errors.append(str(rel) + ": hash or size mismatch")
    if errors:
        raise SystemExit("\n".join(errors))
    print(json.dumps({"status": "supplied file hashes match", "files": len(manifest["files"])}, indent=2))


if __name__ == "__main__":
    main()
