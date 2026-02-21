#!/usr/bin/env python3
"""
Collect KRW/VND rates, save JSON history, send Telegram, and auto-push to GitHub.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_DIR = SCRIPT_DIR
REPO_DATA_FILE = REPO_DIR / "exchange_data" / "rates.json"
STATE_FILE = REPO_DIR / "exchange_data" / "collector_state.json"
LEGACY_DATA_FILE = Path(r"C:\gemini\exchange_data\rates.json")

API_URL = "https://api.exchangerate-api.com/v4/latest/KRW"
REQUEST_TIMEOUT_SEC = 15

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN", "8297687133:AAHK1b_aInggvX3jUv8xseoqJqYJ774ovlM"
)
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "393163178")


def is_enabled(value: str, default: bool = True) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"0", "false", "no", "off"}:
        return False
    if normalized in {"1", "true", "yes", "on"}:
        return True
    return default


ENABLE_GIT_PUSH = is_enabled(os.getenv("ENABLE_GIT_PUSH", "1"), default=True)
ENABLE_TELEGRAM = is_enabled(os.getenv("ENABLE_TELEGRAM", "1"), default=True)
FORCE_TELEGRAM = is_enabled(os.getenv("FORCE_TELEGRAM", "0"), default=False)


def ensure_parent_dir(file_path: Path) -> None:
    file_path.parent.mkdir(parents=True, exist_ok=True)


def load_json(file_path: Path) -> dict[str, Any]:
    if not file_path.exists():
        return {}
    try:
        # Accept UTF-8 with or without BOM.
        with file_path.open("r", encoding="utf-8-sig") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        print(f"[WARN] Failed to read {file_path}: {exc}")
        return {}


def save_json(file_path: Path, data: dict[str, Any]) -> None:
    ensure_parent_dir(file_path)
    with file_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def merge_histories(repo_history: dict[str, Any], legacy_history: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}

    def upsert(source: dict[str, Any]) -> None:
        for day, entry in source.items():
            if not isinstance(entry, dict):
                continue
            prev = merged.get(day)
            if prev is None:
                merged[day] = entry
                continue
            prev_ts = str(prev.get("timestamp", ""))
            curr_ts = str(entry.get("timestamp", ""))
            if curr_ts > prev_ts:
                merged[day] = entry

    upsert(repo_history)
    upsert(legacy_history)
    return dict(sorted(merged.items()))


def fetch_exchange_rate() -> dict[str, Any] | None:
    try:
        response = requests.get(API_URL, timeout=REQUEST_TIMEOUT_SEC)
        response.raise_for_status()
        payload = response.json()
        vnd_per_krw = float(payload["rates"]["VND"])
        krw_per_100vnd = 100 / vnd_per_krw
        return {
            "krwToVnd": round(vnd_per_krw, 2),
            "vndToKrw": round(krw_per_100vnd, 2),
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as exc:
        print(f"[ERROR] Failed to fetch exchange rate: {exc}")
        return None


def send_telegram_message(rate_data: dict[str, Any], total_days: int) -> bool:
    if not ENABLE_TELEGRAM:
        print("[INFO] ENABLE_TELEGRAM=0, skip notification.")
        return False

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[WARN] Telegram config missing, skip notification.")
        return False

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    message = (
        "<b>KRW/VND Daily Update</b>\n\n"
        f"{now_str}\n\n"
        f"1 KRW = <b>{rate_data['krwToVnd']} VND</b>\n"
        f"100 VND = <b>{rate_data['vndToKrw']} KRW</b>\n\n"
        f"Total saved days: {total_days}"
    )

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        response = requests.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "HTML",
            },
            timeout=REQUEST_TIMEOUT_SEC,
        )
        if response.ok:
            print("[OK] Telegram sent.")
            return True
        print(f"[WARN] Telegram failed: {response.status_code} {response.text}")
        return False
    except Exception as exc:
        print(f"[WARN] Telegram error: {exc}")
        return False


def run_git(args: list[str]) -> subprocess.CompletedProcess[str]:
    cmd = ["git", "-C", str(REPO_DIR)] + args
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")


def ensure_git_identity() -> bool:
    name_result = run_git(["config", "user.name"])
    email_result = run_git(["config", "user.email"])
    current_name = name_result.stdout.strip() if name_result.returncode == 0 else ""
    current_email = email_result.stdout.strip() if email_result.returncode == 0 else ""

    if current_name and current_email:
        return True

    origin_result = run_git(["remote", "get-url", "origin"])
    origin_url = origin_result.stdout.strip() if origin_result.returncode == 0 else ""
    matched = re.search(r"github\.com[:/](?P<user>[^/]+)/", origin_url)
    guessed_user = matched.group("user") if matched else ""

    fallback_name = (
        os.getenv("GIT_USER_NAME", "").strip()
        or guessed_user
        or os.getenv("USERNAME", "").strip()
        or "scheduler"
    )
    fallback_email = (
        os.getenv("GIT_USER_EMAIL", "").strip()
        or (f"{guessed_user}@users.noreply.github.com" if guessed_user else "")
        or (f"{fallback_name}@users.noreply.github.com")
    )

    if not current_name:
        set_name = run_git(["config", "user.name", fallback_name])
        if set_name.returncode != 0:
            print("[ERROR] Failed to set git user.name:", set_name.stderr.strip())
            return False
        print(f"[INFO] Set git user.name = {fallback_name}")

    if not current_email:
        set_email = run_git(["config", "user.email", fallback_email])
        if set_email.returncode != 0:
            print("[ERROR] Failed to set git user.email:", set_email.stderr.strip())
            return False
        print(f"[INFO] Set git user.email = {fallback_email}")

    return True


def get_current_branch() -> str | None:
    branch_result = run_git(["rev-parse", "--abbrev-ref", "HEAD"])
    if branch_result.returncode != 0:
        print("[ERROR] Failed to detect current branch:", branch_result.stderr.strip())
        return None
    branch = branch_result.stdout.strip()
    if not branch or branch == "HEAD":
        branch = "main"
    return branch


def sync_with_origin(branch: str) -> bool:
    pull_result = run_git(["pull", "--rebase", "--autostash", "origin", branch])
    if pull_result.returncode == 0:
        return True

    run_git(["rebase", "--abort"])
    print("[ERROR] git pull --rebase failed:")
    print(pull_result.stderr.strip() or pull_result.stdout.strip())
    return False


def auto_commit_and_push() -> bool:
    if not ENABLE_GIT_PUSH:
        print("[INFO] ENABLE_GIT_PUSH=0, skip GitHub push.")
        return True

    if shutil.which("git") is None:
        print("[ERROR] git command not found.")
        return False

    repo_check = run_git(["rev-parse", "--is-inside-work-tree"])
    if repo_check.returncode != 0 or repo_check.stdout.strip() != "true":
        print("[ERROR] Not a git repository:", REPO_DIR)
        return False

    rel_path = REPO_DATA_FILE.relative_to(REPO_DIR).as_posix()

    add_result = run_git(["add", rel_path])
    if add_result.returncode != 0:
        print("[ERROR] git add failed:", add_result.stderr.strip())
        return False

    diff_cached = run_git(["diff", "--cached", "--quiet", "--", rel_path])
    if diff_cached.returncode == 0:
        print("[INFO] No staged changes for exchange_data/rates.json.")
        return True

    if not ensure_git_identity():
        return False

    branch = get_current_branch()
    if branch is None:
        return False

    commit_msg = f"chore: update KRW/VND rate {datetime.now():%Y-%m-%d %H:%M}"
    commit_result = run_git(["commit", "-m", commit_msg])
    if commit_result.returncode != 0:
        print("[ERROR] git commit failed:", commit_result.stderr.strip() or commit_result.stdout.strip())
        return False

    push_result = run_git(["push", "origin", branch])
    if push_result.returncode == 0:
        print("[OK] GitHub push completed.")
        return True

    push_error = (push_result.stderr.strip() or push_result.stdout.strip()).lower()
    if "fetch first" in push_error or "non-fast-forward" in push_error or "rejected" in push_error:
        print("[WARN] Push rejected due remote updates. Retrying after pull --rebase...")
        if not sync_with_origin(branch):
            return False
        push_retry = run_git(["push", "origin", branch])
        if push_retry.returncode == 0:
            print("[OK] GitHub push completed (after retry).")
            return True
        print("[ERROR] git push failed after retry:")
        print(push_retry.stderr.strip() or push_retry.stdout.strip())
        return False

    print("[ERROR] git push failed:")
    print(push_result.stderr.strip() or push_result.stdout.strip())
    return False


def should_send_telegram_today(state: dict[str, Any], today: str) -> bool:
    if FORCE_TELEGRAM:
        return True
    last_sent_day = str(state.get("last_telegram_date", "")).strip()
    return last_sent_day != today


def main() -> int:
    print("=" * 56)
    print("KRW/VND collector started")
    print("=" * 56)

    if ENABLE_GIT_PUSH:
        if shutil.which("git") is None:
            print("[ERROR] git command not found.")
            return 2
        if not ensure_git_identity():
            return 2
        branch = get_current_branch()
        if branch is None:
            return 2
        if not sync_with_origin(branch):
            return 2

    repo_history = load_json(REPO_DATA_FILE)
    legacy_history = load_json(LEGACY_DATA_FILE)
    state = load_json(STATE_FILE)
    history = merge_histories(repo_history, legacy_history)

    print(f"[INFO] Loaded {len(history)} day(s) of history.")

    rate_data = fetch_exchange_rate()
    if not rate_data:
        return 1

    today = datetime.now().strftime("%Y-%m-%d")
    history[today] = rate_data
    history = dict(sorted(history.items()))

    save_json(REPO_DATA_FILE, history)
    print(f"[OK] Saved repository data: {REPO_DATA_FILE}")

    try:
        save_json(LEGACY_DATA_FILE, history)
        print(f"[OK] Synced legacy data: {LEGACY_DATA_FILE}")
    except Exception as exc:
        print(f"[WARN] Legacy sync failed: {exc}")

    print(f"[INFO] 1 KRW = {rate_data['krwToVnd']} VND")
    print(f"[INFO] 100 VND = {rate_data['vndToKrw']} KRW")

    if should_send_telegram_today(state, today):
        if send_telegram_message(rate_data, len(history)):
            state["last_telegram_date"] = today
            state["last_telegram_ts"] = datetime.now().isoformat()
            save_json(STATE_FILE, state)
    else:
        print(f"[INFO] Telegram already sent for {today}, skip duplicate.")

    if not auto_commit_and_push():
        return 2

    print("=" * 56)
    print("Done")
    print("=" * 56)
    return 0


if __name__ == "__main__":
    sys.exit(main())
