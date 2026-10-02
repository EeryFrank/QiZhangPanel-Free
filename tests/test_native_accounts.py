from __future__ import annotations

import base64
import concurrent.futures
import hashlib
import json
from pathlib import Path
import secrets
import sys
import tempfile
import unittest
from unittest import mock
import uuid

BACKEND = Path(__file__).resolve().parents[1] / "src" / "backend"
sys.path.insert(0, str(BACKEND))
import native_accounts
from native_accounts import NativeAccounts, NativeAccountError


class NativeAccountsTests(unittest.TestCase):
    def setUp(self):
        scratch = Path(tempfile.gettempdir()) / 'QiZhangPanel-Free-tests'
        scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="accounts-", dir=scratch)
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "accounts.json"
        self.repository = NativeAccounts(self.path)
        self.password = "测试密码-LongEnough-123"

    def test_registration_returns_distinct_stable_workspace_ids_and_no_hashes(self):
        first = self.repository.register("  管理员  ", self.password)
        second = self.repository.register("Second", self.password)
        self.assertEqual(first["username"], "管理员")
        self.assertEqual(first["id"], str(uuid.UUID(first["id"])))
        self.assertEqual(first["workspace_id"], first["id"])
        self.assertNotEqual(first["workspace_id"], second["workspace_id"])
        self.assertEqual(first["theme"], "forest")
        self.assertEqual(first["origin"], "registered")
        self.assertEqual(self.repository.status()["account_count"], 2)
        reopened = NativeAccounts(self.path)
        self.assertEqual(reopened.get_account(first["id"]), first)
        self.assertEqual(reopened.accounts(), [first, second])
        serialized = self.path.read_text(encoding="utf-8")
        self.assertNotIn(self.password, serialized)
        persisted = json.loads(serialized)["accounts"]
        self.assertNotEqual(persisted[0]["remote_password_salt"], persisted[1]["remote_password_salt"])
        for profile in (first, second, *reopened.accounts()):
            self.assertFalse(any("password" in key or "salt" in key or "hash" in key for key in profile))
        self.assertFalse((self.path.parent / "profiles").exists(), "Repository must not create workspace data")

    def test_case_insensitive_username_uniqueness_and_unicode_login(self):
        account = self.repository.register("Alice", self.password)
        with self.assertRaisesRegex(NativeAccountError, "已被使用"):
            self.repository.register("  ALICE ", self.password)
        self.assertEqual(self.repository.authenticate(" alice ", self.password)["id"], account["id"])
        chinese = self.repository.register("林间玩家", self.password)
        self.assertEqual(self.repository.authenticate("林间玩家", self.password)["id"], chinese["id"])

    def test_cross_account_passwords_do_not_authenticate(self):
        first = self.repository.register("one", "First-Password-123")
        second = self.repository.register("two", "Second-Password-456")
        with self.assertRaisesRegex(NativeAccountError, "账号或密码错误"):
            self.repository.authenticate("one", "Second-Password-456")
        with self.assertRaisesRegex(NativeAccountError, "账号或密码错误"):
            self.repository.authenticate("unknown", "First-Password-123")
        self.assertEqual(self.repository.authenticate("one", "First-Password-123")["id"], first["id"])
        self.assertEqual(self.repository.authenticate("two", "Second-Password-456")["id"], second["id"])

    def test_account_change_preserves_id_workspace_and_custom_metadata(self):
        original = self.repository.register("owner", self.password)
        document = json.loads(self.path.read_text(encoding="utf-8"))
        document["registration_policy"] = {"enabled": True, "reason": "retain metadata"}
        document["accounts"][0]["theme"] = "slate"
        document["accounts"][0]["workspace_migrated"] = {"completed": True, "source": "fixture"}
        self.path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
        updated = self.repository.change_account(original["id"], self.password, "renamed", "New-Password-789")
        self.assertEqual(updated["id"], original["id"])
        self.assertEqual(updated["workspace_id"], original["workspace_id"])
        self.assertEqual(updated["created_at"], original["created_at"])
        self.assertEqual(updated["theme"], "slate")
        stored = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(stored["registration_policy"], document["registration_policy"])
        self.assertEqual(stored["accounts"][0]["workspace_migrated"], document["accounts"][0]["workspace_migrated"])
        self.assertNotIn("workspace_migrated", updated)
        with self.assertRaises(NativeAccountError):
            self.repository.authenticate("owner", self.password)
        with self.assertRaises(NativeAccountError):
            self.repository.authenticate("renamed", self.password)
        self.assertEqual(self.repository.authenticate("renamed", "New-Password-789")["id"], original["id"])

    def test_collision_wrong_current_password_and_weak_replacement_leave_file_unchanged(self):
        first = self.repository.register("one", self.password)
        self.repository.register("two", "Other-Password-456")
        before = self.path.read_bytes()
        attempts = [("incorrect", "new", "Some-Password-123"),
                    (self.password, "TWO", "Some-Password-123"),
                    (self.password, "new", "short")]
        for current, username, replacement in attempts:
            with self.subTest(username=username, current_valid=current == self.password):
                with self.assertRaises(NativeAccountError):
                    self.repository.change_account(first["id"], current, username, replacement)
                self.assertEqual(self.path.read_bytes(), before)

    def test_blank_new_password_only_changes_username_and_preserves_hash(self):
        account = self.repository.register("one", self.password)
        before = json.loads(self.path.read_text(encoding="utf-8"))["accounts"][0]
        result = self.repository.change_account(account["id"], self.password, "OnlyRename", "")
        after = json.loads(self.path.read_text(encoding="utf-8"))["accounts"][0]
        for key in ("remote_password_hash", "remote_password_salt", "remote_password_iterations"):
            self.assertEqual(before[key], after[key])
        self.assertEqual(self.repository.authenticate("onlyrename", self.password)["id"], result["id"])

    def test_legacy_hash_is_seeded_exactly_once_without_plaintext_password(self):
        legacy_path = self.path.parent / "imported-accounts.json"
        salt = secrets.token_bytes(16)
        iterations = 100_123
        legacy = {"remote_username": "旧管理员", "remote_password_salt": base64.b64encode(salt).decode("ascii"),
                  "remote_password_hash": base64.b64encode(hashlib.pbkdf2_hmac("sha256", self.password.encode("utf-8"), salt, iterations)).decode("ascii"),
                  "remote_password_iterations": iterations, "remote_access": True, "unrelated_private_field": "do not copy"}
        migrated = NativeAccounts(legacy_path, legacy)
        account = migrated.authenticate("旧管理员", self.password)
        self.assertEqual(account["origin"], "legacy")
        stored = json.loads(legacy_path.read_text(encoding="utf-8"))["accounts"][0]
        for key in ("remote_password_hash", "remote_password_salt", "remote_password_iterations"):
            self.assertEqual(stored[key], legacy[key])
        self.assertNotIn("unrelated_private_field", stored)
        migrated.register("additional", "Additional-Pass-123")
        reopened = NativeAccounts(legacy_path, {**legacy, "remote_username": "should-not-be-seeded"})
        self.assertEqual(reopened.status()["account_count"], 2)
        self.assertEqual(reopened.authenticate("旧管理员", self.password)["id"], account["id"])

    def test_invalid_repository_and_invalid_legacy_hash_are_never_reset(self):
        self.path.write_text('{"version":1,"accounts": "damaged"}', encoding="utf-8")
        before = self.path.read_bytes()
        with self.assertRaises(NativeAccountError):
            NativeAccounts(self.path)
        self.assertEqual(self.path.read_bytes(), before)
        legacy_path = self.path.parent / "invalid-legacy.json"
        with self.assertRaises(NativeAccountError):
            NativeAccounts(legacy_path, {"remote_password_hash": "invalid", "remote_password_salt": "invalid"})
        self.assertFalse(legacy_path.exists())

    def test_atomic_write_failure_keeps_previous_accounts_and_cleans_temporary_file(self):
        account = self.repository.register("one", self.password)
        before = self.path.read_bytes()
        with mock.patch.object(native_accounts.os, "replace", side_effect=OSError("simulated disk failure")):
            with self.assertRaises(OSError):
                self.repository.register("two", "Another-Password-456")
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.repository.accounts(), [account])
        self.assertFalse(list(self.path.parent.glob(".*.tmp")))

    def test_concurrent_repository_instances_do_not_lose_registration(self):
        another = NativeAccounts(self.path)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.repository.register, "one", self.password)
            second = pool.submit(another.register, "two", self.password)
            registered = [first.result(), second.result()]
        self.assertEqual({a["id"] for a in self.repository.accounts()}, {a["id"] for a in registered})
        def duplicate(repo):
            try:
                repo.register("ONE", self.password)
            except NativeAccountError:
                return "duplicate"
            return "unexpected"
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(list(pool.map(duplicate, [self.repository, another])), ["duplicate", "duplicate"])

    def test_username_and_password_validation(self):
        for name in ("", "   ", "name with space", "name/path", "name\\path", "name:colon", "x" * 65, "name\x7f"):
            with self.subTest(username=name), self.assertRaises(NativeAccountError):
                self.repository.register(name, self.password)
        for password in ("short", "x" * 129, "long-enough\ninvalid", "long-enough\0invalid"):
            with self.subTest(password_length=len(password)), self.assertRaises(NativeAccountError):
                self.repository.register("valid", password)
        self.assertFalse(self.repository.status()["has_accounts"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
