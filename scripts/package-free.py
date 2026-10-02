"""Package the stand-alone free panel; standard library only.

Copyright (c) 2026 EeryFrank. https://github.com/EeryFrank
SPDX-License-Identifier: GPL-3.0-only
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_NAME = "python-3.13.15-embed-amd64.zip"
RUNTIME_URL = "https://www.python.org/ftp/python/3.13.15/" + RUNTIME_NAME
# Published at https://www.python.org/downloads/release/python-31315/
RUNTIME_SHA256 = "d1f04d990aee1253d8569e8e5104e30fa9f5fa830899f14843448872d936a2cf"


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", default="2.5.7")
    for name in ("output", "native-build", "uninstaller-build", "cache-dir"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--runtime-archive", type=Path)
    args = parser.parse_args()
    runtime = args.runtime_archive or args.cache_dir / RUNTIME_NAME
    if not runtime.is_file():
        if args.runtime_archive:
            raise FileNotFoundError(runtime)
        runtime.parent.mkdir(parents=True, exist_ok=True)
        temporary = runtime.with_suffix(".partial")
        try:
            with urllib.request.urlopen(RUNTIME_URL, timeout=90) as response, temporary.open("wb") as out:
                shutil.copyfileobj(response, out)
            if sha(temporary) != RUNTIME_SHA256:
                raise ValueError("Official Python runtime checksum mismatch")
            temporary.replace(runtime)
        finally:
            temporary.unlink(missing_ok=True)
    if sha(runtime) != RUNTIME_SHA256:
        raise ValueError("Python runtime checksum mismatch")
    args.output.mkdir(parents=True, exist_ok=True)
    name = f"qizhang-panel-free-{args.version}-portable"
    staging = args.output / name
    if staging.exists():
        raise FileExistsError("Use a fresh output folder; existing packages are never overwritten: " + str(staging))
    staging.mkdir()
    with zipfile.ZipFile(runtime) as archive:
        archive.extractall(staging / "runtime")
    for path in (ROOT / "src/backend").glob("*.py"):
        destination = staging / "backend" / path.name
        destination.parent.mkdir(exist_ok=True)
        shutil.copy2(path, destination)
    agent = ROOT / "src/backend/tools/command-agent/build/qizhang-command-agent-v3.jar"
    if not agent.is_file():
        raise FileNotFoundError("Build the Java command agent from source first")
    agent_dest = staging / "backend/tools/command-agent/build" / agent.name
    agent_dest.parent.mkdir(parents=True)
    shutil.copy2(agent, agent_dest)
    for name in ("native-host.py", "state_store.py"):
        shutil.copy2(ROOT / "src" / name, staging / name)
    shutil.copy2(ROOT / "src/assets/QiZhang.ico", staging / "QiZhang.ico")
    for name in ("七章控制面板.exe", "七章控制面板.exe.config"):
        shutil.copy2(args.native_build / name, staging / name)
    shutil.copy2(args.uninstaller_build / "卸载七章控制面板.exe", staging / "卸载七章控制面板.exe")
    for name in ("README.md", "LICENSE", "THIRD_PARTY_NOTICES.md", "免责说明.md"):
        source = ROOT / name
        if not source.is_file():
            raise FileNotFoundError("Required distribution notice missing: " + name)
        shutil.copy2(source, staging / name)
    if (ROOT / "docs").is_dir():
        shutil.copytree(ROOT / "docs", staging / "docs", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (staging / "portable.flag").write_text("Local accounts and workspace data are stored beside this application.\n", encoding="utf-8")
    (staging / "edition.json").write_text('{"schema":1,"edition":"free"}\n', encoding="utf-8")
    files = [p for p in sorted(staging.rglob("*")) if p.is_file()]
    manifest = [{"path": p.relative_to(staging).as_posix(), "bytes": p.stat().st_size, "sha256": sha(p)} for p in files]
    (staging / "manifest.sha256.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output = staging.with_suffix(".zip")
    # with_suffix would discard the patch version in a dotted directory name.
    output = args.output / (staging.name + ".zip")
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(staging.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(staging.parent))
    print(json.dumps({"path": str(output), "sha256": sha(output), "bytes": output.stat().st_size}, ensure_ascii=False))


if __name__ == "__main__":
    main()
