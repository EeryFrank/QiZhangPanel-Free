"""Copyright (c) 2026 EeryFrank. SPDX-License-Identifier: GPL-3.0-only."""
import argparse
import hashlib
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
records = []
for path in sorted(args.output.iterdir()):
    if path.is_file() and path.suffix.lower() in {".exe", ".zip"}:
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        records.append(f"{digest}  {path.name}\n")
(args.output / "SHA256SUMS.txt").write_text("".join(records), encoding="utf-8")
print("".join(records), end="")
