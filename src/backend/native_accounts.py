# 七章控制面板项目归属：EeryFrank。项目主页：https://github.com/EeryFrank
"""Local native-panel accounts; workspace contents are managed by the host."""
from __future__ import annotations

import base64
import copy
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import threading
from typing import Any
import uuid


class NativeAccountError(ValueError):
    """A user-facing account validation or credential error."""


_PATH_LOCKS: dict[str, Any] = {}
_PATH_LOCKS_GUARD = threading.Lock()
_ITERATIONS = 310_000
_SAFE_FIELDS = (
    "id", "username", "workspace_id", "theme", "created_at", "updated_at", "origin",
)
_DUMMY_PASSWORD = {
    "remote_password_salt": base64.b64encode(bytes(16)).decode("ascii"),
    "remote_password_hash": base64.b64encode(bytes(32)).decode("ascii"),
    "remote_password_iterations": _ITERATIONS,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _username(value: Any) -> str:
    if not isinstance(value, str):
        raise NativeAccountError("账号格式无效。")
    value = value.strip()
    if not 1 <= len(value) <= 64 or any(
        char.isspace() or ord(char) < 32 or ord(char) == 127 or char in ":\\/"
        for char in value
    ):
        raise NativeAccountError("账号需要 1～64 位，不能包含空格、冒号、斜线或控制字符。")
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise NativeAccountError("账号包含无效字符。") from None
    return value


def _password(value: Any) -> str:
    if not isinstance(value, str) or not 10 <= len(value) <= 128:
        raise NativeAccountError("密码长度必须为 10～128 位。")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise NativeAccountError("密码不能包含换行或控制字符。")
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise NativeAccountError("密码包含无效字符。") from None
    return value


def _record(password: str) -> dict[str, Any]:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERATIONS)
    return {
        "remote_password_salt": base64.b64encode(salt).decode("ascii"),
        "remote_password_hash": base64.b64encode(digest).decode("ascii"),
        "remote_password_iterations": _ITERATIONS,
    }


def _decode_record(record: dict[str, Any]) -> tuple[bytes, bytes, int]:
    try:
        iterations = int(record.get("remote_password_iterations", _ITERATIONS))
        salt = base64.b64decode(record["remote_password_salt"], validate=True)
        digest = base64.b64decode(record["remote_password_hash"], validate=True)
        if not 100_000 <= iterations <= 2_000_000 or not 16 <= len(salt) <= 256 or len(digest) != 32:
            raise ValueError
        return salt, digest, iterations
    except (KeyError, TypeError, ValueError, UnicodeError):
        raise NativeAccountError("账号密码记录无效，请保留原文件并从备份恢复。") from None


def _verify(record: dict[str, Any], password: Any) -> bool:
    if not isinstance(password, str) or len(password) > 128:
        return False
    try:
        encoded = password.encode("utf-8")
        salt, expected, iterations = _decode_record(record)
        actual = hashlib.pbkdf2_hmac("sha256", encoded, salt, iterations)
        return hmac.compare_digest(actual, expected)
    except (NativeAccountError, UnicodeError):
        return False


class NativeAccounts:
    """Account repository. The host owns login throttling and filesystem ACLs.

    One panel host owns this file across processes. Instances in the same
    process share a path lock and reload before mutation to avoid stale writes.
    """

    def __init__(self, path: Path, legacy_config: dict[str, Any] | None = None):
        self.path = Path(path).resolve()
        key = os.path.normcase(str(self.path))
        with _PATH_LOCKS_GUARD:
            self._lock = _PATH_LOCKS.setdefault(key, threading.RLock())
        with self._lock:
            if self.path.exists():
                self._read()
                return
            stamp = _now()
            document = {"version": 1, "accounts": [], "created_at": stamp, "updated_at": stamp}
            if legacy_config and legacy_config.get("remote_password_hash"):
                _decode_record(legacy_config)
                name = _username(legacy_config.get("remote_username", "qizhang"))
                account = self._new_account(name, "legacy")
                for field in _DUMMY_PASSWORD:
                    account[field] = legacy_config.get(field, _ITERATIONS if field.endswith("iterations") else "")
                document["accounts"].append(account)
            self._write(document)

    @staticmethod
    def _new_account(username: str, origin: str) -> dict[str, Any]:
        identifier = str(uuid.uuid4())
        stamp = _now()
        return {"id": identifier, "workspace_id": identifier, "username": username,
                "theme": "forest", "created_at": stamp, "updated_at": stamp, "origin": origin}

    @staticmethod
    def _safe(account: dict[str, Any]) -> dict[str, Any]:
        return copy.deepcopy({key: account[key] for key in _SAFE_FIELDS if key in account})

    def _read(self) -> dict[str, Any]:
        try:
            document = json.loads(self.path.read_text(encoding="utf-8-sig"))
            if not isinstance(document, dict) or document.get("version") != 1 or not isinstance(document.get("accounts"), list):
                raise ValueError
            ids, names = set(), set()
            for account in document["accounts"]:
                if not isinstance(account, dict):
                    raise ValueError
                identifier = str(uuid.UUID(account["id"]))
                if identifier != account["id"] or identifier in ids:
                    raise ValueError
                # Workspaces are permanently bound to the stable account ID.
                if account.get("workspace_id") != identifier:
                    raise ValueError
                username = _username(account["username"])
                if username != account["username"] or username.casefold() in names:
                    raise ValueError
                _decode_record(account)
                ids.add(identifier)
                names.add(username.casefold())
            return document
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            raise NativeAccountError("无法读取账号资料，请保留原文件并检查格式或恢复备份。") from None

    def _write(self, document: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name("." + self.path.name + "." + uuid.uuid4().hex + ".tmp")
        try:
            with temporary.open("x", encoding="utf-8", newline="\n") as output:
                json.dump(document, output, ensure_ascii=False, indent=2)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _find(document: dict[str, Any], account_id: Any) -> dict[str, Any]:
        for account in document["accounts"]:
            if account["id"] == account_id:
                return account
        raise NativeAccountError("账号不存在。")

    def status(self) -> dict[str, Any]:
        with self._lock:
            count = len(self._read()["accounts"])
            return {"has_accounts": bool(count), "account_count": count, "registration_allowed": True}

    def accounts(self) -> list[dict[str, Any]]:
        with self._lock:
            return [self._safe(account) for account in self._read()["accounts"]]

    def get_account(self, account_id: str) -> dict[str, Any]:
        with self._lock:
            return self._safe(self._find(self._read(), account_id))

    def register(self, username: str, password: str) -> dict[str, Any]:
        name, password = _username(username), _password(password)
        with self._lock:
            document = self._read()
            if any(account["username"].casefold() == name.casefold() for account in document["accounts"]):
                raise NativeAccountError("这个账号已被使用，请换一个名称。")
            account = self._new_account(name, "registered")
            account.update(_record(password))
            document["accounts"].append(account)
            document["updated_at"] = _now()
            self._write(document)
            return self._safe(account)

    def authenticate(self, username: str, password: str) -> dict[str, Any]:
        try:
            name = _username(username)
        except NativeAccountError:
            name = ""
        with self._lock:
            account = next((entry for entry in self._read()["accounts"]
                            if entry["username"].casefold() == name.casefold()), None)
            valid = _verify(account if account is not None else _DUMMY_PASSWORD, password)
            if account is None or not valid:
                raise NativeAccountError("账号或密码错误。")
            return self._safe(account)

    def change_account(self, account_id: str, current_password: str, username: str,
                       password: str | None = None) -> dict[str, Any]:
        name = _username(username)
        with self._lock:
            document = self._read()
            account = self._find(document, account_id)
            if not _verify(account, current_password):
                raise NativeAccountError("当前密码不正确。")
            if any(entry["id"] != account_id and entry["username"].casefold() == name.casefold()
                   for entry in document["accounts"]):
                raise NativeAccountError("这个账号已被使用，请换一个名称。")
            if password is not None and password != "":
                account.update(_record(_password(password)))
            account["username"] = name
            account["updated_at"] = _now()
            document["updated_at"] = _now()
            self._write(document)
            return self._safe(account)
