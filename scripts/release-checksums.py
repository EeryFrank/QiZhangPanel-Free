"""Prepare immutable release files and the fixed-name installer download alias.

Copyright (c) 2026 EeryFrank. SPDX-License-Identifier: GPL-3.0-only.
This script only prepares local files; it does not publish or change Git tags.
"""
import argparse
import hashlib
import os
from pathlib import Path
import re
import shutil
import uuid


INSTALLER_ALIAS = "qizhang-panel-free-setup.exe"


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def prepare_release(output: Path, version: str) -> str:
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("Version must have the form X.Y.Z.")
    output = output.resolve(strict=True)
    installer = output / f"qizhang-panel-free-{version}-setup.exe"
    portable = output / f"qizhang-panel-free-{version}-portable.zip"
    alias = output / INSTALLER_ALIAS
    files = (installer, portable, alias)
    for path in (installer, portable):
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Missing regular release file: {path.name}")
    unexpected = sorted(
        path.name for path in output.iterdir()
        if path.suffix.lower() in {".exe", ".zip"} and path not in files
    )
    if unexpected:
        raise ValueError("Use a separate output directory for each release; unexpected files: "
                         + ", ".join(unexpected))
    installer_hash = sha256(installer)
    if alias.exists() or alias.is_symlink():
        if alias.is_symlink() or not alias.is_file() or sha256(alias) != installer_hash:
            raise ValueError("Installer alias already exists with different content. "
                             "Use a new release output directory; no files were replaced.")
    else:
        # Exclusive creation prevents overwriting an existing release asset.
        with alias.open("xb") as destination, installer.open("rb") as source:
            shutil.copyfileobj(source, destination)
        if sha256(alias) != installer_hash:
            raise ValueError("Installer alias verification failed; do not publish this directory.")
    records = "".join(f"{sha256(path)}  {path.name}\n" for path in sorted(files))
    checksum_path = output / "SHA256SUMS.txt"
    if checksum_path.is_symlink():
        raise ValueError("The checksum output must not be a symbolic link.")
    temporary = output / f".SHA256SUMS-{uuid.uuid4().hex}.tmp"
    try:
        temporary.write_text(records, encoding="utf-8", newline="\n")
        os.replace(temporary, checksum_path)
    finally:
        temporary.unlink(missing_ok=True)
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--version", required=True, help="Exact release version, for example 2.5.7")
    args = parser.parse_args()
    try:
        print(prepare_release(args.output, args.version), end="")
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Release preparation failed: {exc}\n")


if __name__ == "__main__":
    main()
