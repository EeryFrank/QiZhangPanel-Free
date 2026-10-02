"""Read-only release boundary checks for the independent Free source tree.

Copyright (c) 2026 EeryFrank. SPDX-License-Identifier: GPL-3.0-only
The report contains relative paths and finding categories, never matched values.
Default mode examines distributable source, excluding documented local build
directories. --git-index examines every tracked file, including ignored files.
This is a bounded pattern/boundary check, not proof that no unknown secret exists.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys


SOURCE_DIRS = {"src", "scripts", "tests", "docs", ".github", ".gitlab"}
SOURCE_FILES = {
    ".gitignore", ".gitattributes", ".gitlab-ci.yml", "README.md", "LICENSE",
    "THIRD_PARTY_NOTICES.md", "CHANGELOG.md", "CONTRIBUTING.md", "SECURITY.md",
    "AGENTS.md", "免责说明.md", "pyproject.toml", "requirements.txt",
}
LOCAL_DIRS = {"artifacts", "outputs", "work", "cache", "runtime", "build", "dist",
              ".venv", ".vs", ".idea", ".pytest_cache", "__pycache__"}
PAID_MODULES = {
    "native_remote", "native_assistant", "native_sakura", "native_watchdog",
    "native_verdict", "native_components", "native_maintenance", "native_update_idle",
    "assistant_stats", "scheduler", "shortcut_store", "commercial_service",
    "supabase_license", "license_gateway", "afdian_delivery", "edition_download",
}
PAID_FILES = {
    "RemoteUi.cs", "RemoteConnection.cs", "SakuraUi.cs", "SakuraClientSettings.cs",
    "VerdictUi.cs", "ComponentsUi.cs", "MaintenanceUi.cs", "AutomaticUpdates.cs",
    "NativeUpdater.cs", "SilentUpdate.cs", "UpdateOnlineVerification.cs",
    "CommercialAuthorization.cs", "CommercialLicenseTransport.cs", "CommercialPayload.cs",
    "IssuerToolLauncher.cs", "commercial-payload-builder.cs",
}
PRIVATE_NAMES = {
    "accounts.json", "servers.json", "software.json", "edition-slot.json",
    "server.properties", "server-icon.png", "ops.json", "whitelist.json", "usercache.json",
    "banned-ips.json", "banned-players.json", "eula.txt", "release-secret.json",
    "commercial.config", "commercial.payload", "credentials.json", "secrets.json",
}
PRIVATE_DIRS = {"data", "mcsever", "mcserver", "world", "world_nether", "world_the_end",
                "playerdata", "logs", "crash-reports", "private-commercial"}
SECRET_SUFFIXES = {".dpapi", ".pfx", ".p12", ".key", ".pem", ".sqlite", ".sqlite3", ".db"}
BINARY_SUFFIXES = {".exe", ".dll", ".jar", ".class", ".pdb", ".pyd", ".zip", ".7z", ".rar"}
TEXT_SUFFIXES = {".py", ".cs", ".java", ".ps1", ".bat", ".cmd", ".json", ".md", ".txt",
                 ".yml", ".yaml", ".toml", ".xml", ".manifest", ".mf", ".config", ".ini"}
MAX_SOURCE_BYTES = 8 * 1024 * 1024
SELF_PATH = "scripts/audit-public-tree.py"

SECRET_PATTERNS = {
    "credential-supabase-token": rb"\b(?:sbp_|sb_secret_)[A-Za-z0-9_-]{24,}\b",
    "credential-github-token": rb"\b(?:gh[pousr]_|github_pat_)[A-Za-z0-9_]{30,}\b",
    "credential-gitlab-token": rb"\bglpat-[A-Za-z0-9_-]{20,}\b",
    "credential-private-key": rb"-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----",
    "credential-aws-access-id": rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b",
    "credential-assigned-secret": rb'''["'](?:master_?key|service_role_key|access_token|refresh_token|api_secret)["']\s*[:=]\s*["'][A-Za-z0-9_+\-/=.]{32,}["']''',
    "credential-license-digest-record": rb'''["']key_digest["']\s*:\s*["'][0-9a-fA-F]{64}["']''',
    "credential-authorization-header": rb"\bBearer\s+(?:eyJ[A-Za-z0-9_\-.]{30,}|[A-Za-z0-9_-]{40,})",
}
PAID_IDENTIFIERS = re.compile(
    r"\b(?:NativeRemote|NativeAssistant|NativeSakura|NativeWatchdog|NativeVerdict|"
    r"TaskScheduler|ShortcutStore|AutomaticUpdateCoordinator|CommercialAuthorization|"
    r"CommercialLicenseTransport|CommercialPayload|SakuraClientSettings|NativeUpdater)\b")
PRIVATE_URL = re.compile(r"https?://[A-Za-z0-9][A-Za-z0-9.-]*\.supabase\.co(?:[/\s\"'<>]|$)", re.I)
PERSONAL_PATH = re.compile(
    r"(?:[A-Za-z]:[\\/](?:Users[\\/](?!Public(?:[\\/]|$)|Default(?:[\\/]|$))[^\s\"'<>]+|"
    r"(?:Codex_work|保存|Q1666)[\\/])|Tencent Files[\\/]|OneDrive[\\/])", re.I)


def add(findings: list[dict], path: str, category: str) -> None:
    entry = {"path": path, "category": category}
    if entry not in findings:
        findings.append(entry)


def inspect_bytes(relative: str, data: bytes, findings: list[dict]) -> None:
    """Pure content check; callers may use synthetic data to test redaction."""
    variants = (data, data.replace(b"\x00", b"")) if b"\x00" in data else (data,)
    for category, pattern in SECRET_PATTERNS.items():
        if any(re.search(pattern, value, re.I if category == "credential-assigned-secret" else 0)
               for value in variants):
            add(findings, relative, category)
    path = PurePosixPath(relative)
    text_file = path.suffix.lower() in TEXT_SUFFIXES or path.name in SOURCE_FILES
    if not text_file or b"\x00" in data:
        return
    try:
        content = data.decode("utf-8-sig")
    except UnicodeError:
        add(findings, relative, "source-not-utf8")
        return
    # This script necessarily contains prohibited identifier examples. Secret
    # value scanning still covers the script itself; product checks do not.
    if relative == SELF_PATH:
        return
    if PRIVATE_URL.search(content):
        add(findings, relative, "deployment-specific-cloud-endpoint")
    if PERSONAL_PATH.search(content):
        add(findings, relative, "personal-or-private-workspace-path")
    if path.suffix.lower() in {".py", ".cs", ".ps1", ".java"}:
        references = [match.group() for match in PAID_IDENTIFIERS.finditer(content)]
        # System.Threading.Tasks.TaskScheduler is a standard UI/concurrency
        # primitive; the similarly named Python scheduler is a paid subsystem.
        if path.suffix.lower() == ".cs":
            references = [name for name in references if name != "TaskScheduler"]
        if references:
            add(findings, relative, "paid-implementation-reference")
        if re.search(r"\bEDITION_(?:COMMERCIAL|ULTIMATE)\b", content):
            add(findings, relative, "paid-build-target")
    if path.suffix.lower() == ".py":
        try:
            tree = ast.parse(content, filename=relative)
        except SyntaxError:
            add(findings, relative, "python-syntax-error")
            return
        for node in ast.walk(tree):
            imported = ([item.name for item in node.names] if isinstance(node, ast.Import)
                        else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            if any(name.split(".")[0] in PAID_MODULES for name in imported):
                add(findings, relative, "paid-module-import")


def relative_paths(root: Path, git_index: bool) -> tuple[list[str], list[str]]:
    if git_index:
        result = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "--cached"],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        if result.returncode:
            raise RuntimeError("git-index-unavailable")
        return sorted(set(result.stdout.decode("utf-8").rstrip("\0").split("\0")) - {""}), []
    paths, excluded = [], []
    for current, dirs, files in os.walk(root, followlinks=False):
        here = Path(current)
        for name in list(dirs):
            item = here / name
            relative = item.relative_to(root).as_posix()
            info = item.lstat()
            is_link = stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)
            if name == ".git":
                dirs.remove(name)
            elif is_link:
                paths.append(relative)
                dirs.remove(name)
            elif name in LOCAL_DIRS:
                excluded.append(relative)
                dirs.remove(name)
        paths.extend((here / name).relative_to(root).as_posix() for name in files)
    return sorted(paths), sorted(excluded)


def audit(root: Path, git_index: bool = False) -> dict:
    findings: list[dict] = []
    paths, excluded = relative_paths(root, git_index)
    if git_index:
        # Content is read from disk below. Reject any index/worktree difference
        # rather than accidentally certifying clean disk bytes over a stale or
        # unsafe staged blob. No diff content or matching value is printed.
        compared = subprocess.run(
            ["git", "-C", str(root), "diff", "--name-only", "-z", "--no-ext-diff", "--no-textconv"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        if compared.returncode:
            raise RuntimeError("git-index-comparison-unavailable")
        for relative in compared.stdout.decode("utf-8").split("\0"):
            if relative:
                add(findings, relative, "index-differs-from-worktree")
    checked = 0
    for relative in paths:
        pure = PurePosixPath(relative)
        if pure.is_absolute() or ".." in pure.parts or "\\" in relative or ":" in relative:
            add(findings, relative, "unsafe-public-path")
            continue
        path = root.joinpath(*pure.parts)
        try:
            info = path.lstat()
        except OSError:
            add(findings, relative, "public-file-unreadable-or-missing")
            continue
        if stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400):
            add(findings, relative, "reparse-point-or-symbolic-link")
            continue
        if not path.is_file():
            add(findings, relative, "public-entry-not-regular-file")
            continue
        if ((len(pure.parts) == 1 and pure.name not in SOURCE_FILES)
                or (len(pure.parts) > 1 and pure.parts[0] not in SOURCE_DIRS)):
            add(findings, relative, "outside-public-source-allowlist")
        if git_index and any(part in LOCAL_DIRS for part in pure.parts[:-1]):
            add(findings, relative, "tracked-generated-or-runtime-directory")
        if any(part.lower() in PRIVATE_DIRS for part in pure.parts[:-1]):
            add(findings, relative, "local-account-or-server-data-directory")
        if pure.name.lower() in {name.lower() for name in PRIVATE_NAMES}:
            add(findings, relative, "private-runtime-or-issuer-file")
        if path.suffix.lower() in SECRET_SUFFIXES or (pure.name.startswith(".env") and pure.name != ".env.example"):
            add(findings, relative, "credential-or-database-file")
        if any(part in PAID_MODULES for part in pure.parts) or pure.stem in PAID_MODULES or pure.name in PAID_FILES:
            add(findings, relative, "paid-implementation-file")
        if re.search(r"(?:issue[-_]?supabase[-_]?keys|(?:supabase|afdian).*(?:deploy|owner)|release-secret|issuer-tools)", pure.name, re.I):
            add(findings, relative, "issuer-or-cloud-operation-script")
        if path.suffix.lower() in BINARY_SUFFIXES:
            # Generated artifacts belong in Release assets, not the source index.
            add(findings, relative, "binary-in-public-source-tree")
            java_source = root / "src/backend/tools/command-agent/src"
            known_agent = (pure.name == "qizhang-command-agent-v3.jar"
                           and (java_source / "QiZhangAgentLoader.java").is_file()
                           and (java_source / "QiZhangBukkitCommandAgentV3.java").is_file())
            if not known_agent:
                add(findings, relative, "binary-without-explicit-source-mapping")
        if path.suffix.lower() in {".pyc", ".pyo", ".log"}:
            add(findings, relative, "generated-runtime-file")
        if info.st_size > MAX_SOURCE_BYTES:
            add(findings, relative, "source-file-exceeds-scan-limit")
            continue
        try:
            data = path.read_bytes()
        except OSError:
            add(findings, relative, "public-file-unreadable-or-missing")
            continue
        inspect_bytes(relative, data, findings)
        checked += 1
    for required in ("LICENSE", "THIRD_PARTY_NOTICES.md", "README.md",
                     "src/backend/tools/command-agent/src/QiZhangAgentLoader.java",
                     "src/backend/tools/command-agent/src/QiZhangBukkitCommandAgentV3.java"):
        if required not in paths:
            add(findings, required, "required-license-or-source-missing")
    findings.sort(key=lambda item: (item["path"], item["category"]))
    return {"ok": not findings, "scope": "git-index" if git_index else "public-source-tree",
            "files_checked": checked, "excluded_local_directories": excluded,
            "findings": findings,
            "limits": "Pattern and explicit file-boundary audit only; no secret values are reported. "
                      "No runtime, installer execution, external network, or legal clearance is implied."}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--git-index", action="store_true",
                        help="Audit every tracked source file, even if it is ignored.")
    args = parser.parse_args()
    try:
        result = audit(args.root.resolve(strict=True), args.git_index)
    except (OSError, RuntimeError, UnicodeError):
        result = {"ok": False, "findings": [{"path": ".", "category": "audit-input-unavailable"}]}
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
