"""Build the Java 8 queue agent deterministically with an explicitly selected JDK.

Copyright (c) 2026 EeryFrank. https://github.com/EeryFrank
No Minecraft libraries or third-party code are compiled or executed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import zipfile

PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT / "src" / "backend" / "tools" / "command-agent"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--jdk", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path,
                        default=Path(os.environ.get("QIZHANG_CACHE_ROOT", tempfile.gettempdir())) / "QiZhangPanel-Free-build")
    args = parser.parse_args()
    javac = args.jdk.resolve() / "bin" / "javac.exe"
    if not javac.is_file():
        raise SystemExit("The explicitly selected JDK has no javac.exe")
    env = os.environ.copy()
    for key in ("JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS", "JDK_JAVA_OPTIONS"):
        env.pop(key, None)
    sources = [ROOT / "src" / "QiZhangAgentLoader.java",
               ROOT / "src" / "QiZhangBukkitCommandAgentV3.java"]
    output = ROOT / "build" / "qizhang-command-agent-v3.jar"
    output.parent.mkdir(parents=True, exist_ok=True)
    cache = args.cache_dir.resolve()
    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="classes-", dir=cache) as temp:
        classes = Path(temp)
        result = subprocess.run(
            [str(javac), "--release", "8", "-g:none", "-encoding", "UTF-8",
             "-d", str(classes), *map(str, sources)],
            env=env, text=True, capture_output=True, timeout=60,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode:
            raise SystemExit(result.stdout + result.stderr)
        records = []
        contents = {"META-INF/MANIFEST.MF": (ROOT / "MANIFEST.MF").read_bytes()
                    .replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")}
        for file in sorted(classes.rglob("*.class")):
            major = struct.unpack(">H", file.read_bytes()[6:8])[0]
            if major != 52:
                raise SystemExit(f"Expected Java 8 class (52), got {major}: {file.name}")
            name = file.relative_to(classes).as_posix()
            contents[name] = file.read_bytes()
            records.append({"entry": name, "major": major, "sha256": sha(file)})
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as jar:
            for name, value in sorted(contents.items()):
                info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                jar.writestr(info, value, compresslevel=9)
    receipt = {
        "jar": str(output.relative_to(PROJECT)), "sha256": sha(output),
        "sources": {str(file.relative_to(PROJECT)): sha(file) for file in sources},
        "manifest_sha256": sha(ROOT / "MANIFEST.MF"),
        "javac": str(javac), "javac_sha256": sha(javac),
        "classes": records, "copyright": "EeryFrank https://github.com/EeryFrank",
    }
    (output.parent / "build-record-v3.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
