# Copyright (c) 2026 EeryFrank. https://github.com/EeryFrank
# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations
import argparse
import base64
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
import urllib.parse
import uuid
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)

def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.new')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)

def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return default

def protect_state(state_root: Path) -> None:
    """The runtime contains account hashes and a private local-control capability."""
    identity = subprocess.run(['whoami.exe', '/user', '/fo', 'csv', '/nh'], capture_output=True, check=True, creationflags=NO_WINDOW, timeout=10).stdout.decode('utf-8', errors='replace')
    match = re.search('S-1-5-(?:\\d+-)*\\d+', identity)
    if not match:
        raise RuntimeError('无法确认当前 Windows 用户，未创建面板账号数据。')
    subprocess.run(['icacls.exe', str(state_root), '/inheritance:r', '/grant:r', f'*{match.group(0)}:(OI)(CI)F', '/grant:r', '*S-1-5-18:(OI)(CI)F'], capture_output=True, check=True, creationflags=NO_WINDOW, timeout=10)
