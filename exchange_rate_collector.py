#!/usr/bin/env python3
"""
Collect KRW/VND rates, save JSON history, send Telegram, and auto-push to GitHub.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_DIR = SCRIPT_DIR
REPO_DATA_FILE = REPO_DIR / "exchange_data" / "rates.json"
STATE_FILE = REPO_DIR / "exchange_data" / "collector_state.json"
LOG_FILE = REPO_DIR / "exchange_data" / "collector.log"
LEGACY_DATA_FILE = Path(r"C:\gemini\exchange_data\rates.json")

API_SOURCES: tuple[tuple[str, str], ...] = (
    ("exchange-rate-api", "https://api.exchangerate-api.com/v4/latest/KRW"),
    ("open-er-api", "https://open.er-api.com/v6/latest/KRW"),
)
REQUEST_TIMEOUT_SEC = 15

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN", "8297687133:AAHK1b_aInggvX3jUv8xseoqJqYJ774ovlM"
)
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "393163178")

LOGGER = logging.getLogger("exchange_rate_collector")


def get_int_env(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default)).strip()))
    except (TypeError, ValueError):
        return default


def get_float_env(name: str, default: float, minimum: float = 0.0) -> float:
    try:
        return max(minimum, float(os.getenv(name, str(default)).strip()))
    except (TypeError, ValueError):
        return default


FETCH_MAX_RETRIES = get_int_env("FETCH_MAX_RETRIES", 3, minimum=1)
FETCH_RETRY_DELAY_SEC = get_float_env("FETCH_RETRY_DELAY_SEC", 2.0, minimum=0.0)


def is_enabled(value: str | None, default: bool = True) -> bool:
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


def setup_logging() -> None:
    ensure_parent_dir(LOG_FILE)
    if LOGGER.handlers:
        return

    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=512 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)

    LOGGER.addHandler(file_handler)
    LOGGER.addHandler(stream_handler)


def load_json(file_path: Path) -> dict[str, Any]:
    if not file_path.exists():
        return {}
    try:
        with file_path.open("r", encoding="utf-8-sig") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        LOGGER.warning("Failed to read %s: %s", file_path, exc)
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


def _extract_vnd_per_krw(source_name: str, payload: Any) -> float:
    if not isinstance(payload, dict):
        raise TypeError("response payload is not a JSON object")

    if source_name == "open-er-api":
        result = str(payload.get("result", "")).lower()
        if result != "success":
            raise ValueError(f"API result={payload.get('result')!r}")

    rates = payload.get("rates")
    if not isinstance(rates, dict):
        raise KeyError("rates missing in API response")

    raw_value = rates.get("VND")
    if raw_value is None:
        raise KeyError("rates.VND missing in API response")

    vnd_per_krw = float(raw_value)
    if vnd_per_krw <= 0:
        raise ValueError(f"invalid VND rate: {vnd_per_krw}")
    return vnd_per_krw


def fetch_exchange_rate() -> tuple[dict[str, Any] | None, list[str]]:
    errors: list[str] = []

    for source_name, url in API_SOURCES:
        for attempt in range(1, FETCH_MAX_RETRIES + 1):
            try:
                LOGGER.info(
                    "Fetching rate from %s (attempt %s/%s)",
                    source_name,
                    attempt,
                    FETCH_MAX_RETRIES,
                )
                response = requests.get(url, timeout=REQUEST_TIMEOUT_SEC)
                response.raise_for_status()
                payload = response.json()
                vnd_per_krw = _extract_vnd_per_krw(source_name, payload)
                krw_per_100vnd = 100 / vnd_per_krw
                rate_data = {
                    "krwToVnd": round(vnd_per_krw, 2),
                    "vndToKrw": round(krw_per_100vnd, 2),
                    "timestamp": datetime.now().isoformat(),
                }
                LOGGER.info(
                    "Fetch succeeded via %s: 1 KRW = %.2f VND, 100 VND = %.2f KRW",
                    source_name,
                    rate_data["krwToVnd"],
                    rate_data["vndToKrw"],
                )
                return rate_data, errors
            except Exception as exc:
                error_line = f"{source_name} attempt {attempt}/{FETCH_MAX_RETRIES}: {exc}"
                errors.append(error_line)
                LOGGER.warning("Fetch failed: %s", error_line)
                if attempt < FETCH_MAX_RETRIES and FETCH_RETRY_DELAY_SEC > 0:
                    time.sleep(FETCH_RETRY_DELAY_SEC)

        LOGGER.warning("Source %s exhausted. Trying next source.", source_name)

    LOGGER.error("All exchange rate sources failed.")
    return None, errors


def _format_timestamp_for_message(rate_data: dict[str, Any]) -> str:
    raw = str(rate_data.get("timestamp", "")).strip()
    if raw:
        try:
            dt = datetime.fromisoformat(raw)
            return dt.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            pass
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def build_telegram_message(rate_data: dict[str, Any], total_days: int, git_status_line: str) -> str:
    time_str = _format_timestamp_for_message(rate_data)
    return (
        "\U0001f4b1 \uc624\ub298\uc758 \ud658\uc728 \uc815\ubcf4\n\n"
        f"\U0001f4c5 {time_str}\n\n"
        f"\U0001f4b9 1 KRW = {rate_data['krwToVnd']} VND\n"
        f"\U0001f4b9 100 VND = {rate_data['vndToKrw']} KRW\n\n"
        f"\U0001f4ca \ucd1d \uc800\uc7a5 \ub370\uc774\ud130: {total_days}\uc77c\n"
        f"\U0001f517 {git_status_line}"
    )


def _truncate(text: str, max_len: int = 240) -> str:
    compact = " ".join(text.strip().split())
    if len(compact) <= max_len:
        return compact
    return compact[: max_len - 3] + "..."


def build_failure_message(summary: str, details: list[str]) -> str:
    lines = [
        "KRW/VND collector failed",
        "",
        f"Time: {datetime.now():%Y-%m-%d %H:%M}",
        f"Reason: {summary}",
    ]
    if details:
        lines.append("")
        lines.append("Details:")
        for detail in details[:6]:
            lines.append(f"- {_truncate(detail)}")
    return "\n".join(lines)[:3500]


def send_telegram_message(message: str) -> bool:
    if not ENABLE_TELEGRAM:
        LOGGER.info("ENABLE_TELEGRAM=0, skipping Telegram notification.")
        return False

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        LOGGER.warning("Telegram config missing, skipping notification.")
        return False

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        response = requests.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
            },
            timeout=REQUEST_TIMEOUT_SEC,
        )
        if response.ok:
            LOGGER.info("Telegram sent.")
            return True
        LOGGER.warning("Telegram failed: %s %s", response.status_code, response.text)
        return False
    except Exception as exc:
        LOGGER.warning("Telegram error: %s", exc)
        return False


def notify_failure(summary: str, details: list[str]) -> None:
    message = build_failure_message(summary, details)
    if send_telegram_message(message):
        LOGGER.info("Failure alert sent.")
    else:
        LOGGER.warning("Failure alert could not be delivered.")


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
            LOGGER.error("Failed to set git user.name: %s", set_name.stderr.strip())
            return False
        LOGGER.info("Set git user.name = %s", fallback_name)

    if not current_email:
        set_email = run_git(["config", "user.email", fallback_email])
        if set_email.returncode != 0:
            LOGGER.error("Failed to set git user.email: %s", set_email.stderr.strip())
            return False
        LOGGER.info("Set git user.email = %s", fallback_email)

    return True


def get_current_branch() -> str | None:
    branch_result = run_git(["rev-parse", "--abbrev-ref", "HEAD"])
    if branch_result.returncode != 0:
        LOGGER.error("Failed to detect current branch: %s", branch_result.stderr.strip())
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
    LOGGER.error("git pull --rebase failed:")
    LOGGER.error("%s", pull_result.stderr.strip() or pull_result.stdout.strip())
    return False


def auto_commit_and_push() -> tuple[bool, str]:
    if not ENABLE_GIT_PUSH:
        LOGGER.info("ENABLE_GIT_PUSH=0, skipping GitHub push.")
        return True, "⏭ GitHub 푸시 비활성화"

    if shutil.which("git") is None:
        LOGGER.error("git command not found.")
        return False, "❌ GitHub 푸시 실패"

    repo_check = run_git(["rev-parse", "--is-inside-work-tree"])
    if repo_check.returncode != 0 or repo_check.stdout.strip() != "true":
        LOGGER.error("Not a git repository: %s", REPO_DIR)
        return False, "❌ GitHub 푸시 실패"

    rel_path = REPO_DATA_FILE.relative_to(REPO_DIR).as_posix()

    add_result = run_git(["add", rel_path])
    if add_result.returncode != 0:
        LOGGER.error("git add failed: %s", add_result.stderr.strip())
        return False, "❌ GitHub 푸시 실패"

    diff_cached = run_git(["diff", "--cached", "--quiet", "--", rel_path])
    if diff_cached.returncode == 0:
        LOGGER.info("No staged changes for exchange_data/rates.json.")
        return True, "✅ GitHub 푸시 완료"

    if not ensure_git_identity():
        return False, "❌ GitHub 푸시 실패"

    branch = get_current_branch()
    if branch is None:
        return False, "❌ GitHub 푸시 실패"

    commit_msg = f"chore: update KRW/VND rate {datetime.now():%Y-%m-%d %H:%M}"
    commit_result = run_git(["commit", "-m", commit_msg])
    if commit_result.returncode != 0:
        LOGGER.error("git commit failed: %s", commit_result.stderr.strip() or commit_result.stdout.strip())
        return False, "❌ GitHub 푸시 실패"

    push_result = run_git(["push", "origin", branch])
    if push_result.returncode == 0:
        LOGGER.info("GitHub push completed.")
        return True, "✅ GitHub 푸시 완료"

    push_error = (push_result.stderr.strip() or push_result.stdout.strip()).lower()
    if "fetch first" in push_error or "non-fast-forward" in push_error or "rejected" in push_error:
        LOGGER.warning("Push rejected due to remote updates. Retrying after pull --rebase.")
        if not sync_with_origin(branch):
            return False, "❌ GitHub 푸시 실패"
        push_retry = run_git(["push", "origin", branch])
        if push_retry.returncode == 0:
            LOGGER.info("GitHub push completed after retry.")
            return True, "✅ GitHub 푸시 완료"
        LOGGER.error("git push failed after retry:")
        LOGGER.error("%s", push_retry.stderr.strip() or push_retry.stdout.strip())
        return False, "❌ GitHub 푸시 실패"

    LOGGER.error("git push failed:")
    LOGGER.error("%s", push_result.stderr.strip() or push_result.stdout.strip())
    return False, "❌ GitHub 푸시 실패"


def should_send_telegram_today(state: dict[str, Any], today: str) -> bool:
    if FORCE_TELEGRAM:
        return True
    last_sent_day = str(state.get("last_telegram_date", "")).strip()
    return last_sent_day != today


def fail_with_alert(code: int, summary: str, details: list[str]) -> int:
    LOGGER.error("%s", summary)
    for detail in details:
        LOGGER.error("%s", detail)
    notify_failure(summary, details)
    return code


def main() -> int:
    setup_logging()
    LOGGER.info("=" * 56)
    LOGGER.info("KRW/VND collector started")
    LOGGER.info("=" * 56)

    try:
        if ENABLE_GIT_PUSH:
            if shutil.which("git") is None:
                return fail_with_alert(2, "Git pre-flight failed", ["git command not found"])
            if not ensure_git_identity():
                return fail_with_alert(2, "Git pre-flight failed", ["failed to configure git identity"])
            branch = get_current_branch()
            if branch is None:
                return fail_with_alert(2, "Git pre-flight failed", ["failed to detect current branch"])
            if not sync_with_origin(branch):
                return fail_with_alert(2, "Git pre-flight failed", [f"git pull --rebase failed on branch {branch}"])

        repo_history = load_json(REPO_DATA_FILE)
        legacy_history = load_json(LEGACY_DATA_FILE)
        state = load_json(STATE_FILE)
        history = merge_histories(repo_history, legacy_history)

        LOGGER.info("Loaded %s day(s) of history.", len(history))

        rate_data, fetch_errors = fetch_exchange_rate()
        if not rate_data:
            return fail_with_alert(1, "Exchange rate fetch failed", fetch_errors)

        today = datetime.now().strftime("%Y-%m-%d")
        history[today] = rate_data
        history = dict(sorted(history.items()))

        save_json(REPO_DATA_FILE, history)
        LOGGER.info("Saved repository data: %s", REPO_DATA_FILE)

        try:
            save_json(LEGACY_DATA_FILE, history)
            LOGGER.info("Synced legacy data: %s", LEGACY_DATA_FILE)
        except Exception as exc:
            LOGGER.warning("Legacy sync failed: %s", exc)

        LOGGER.info("1 KRW = %s VND", rate_data["krwToVnd"])
        LOGGER.info("100 VND = %s KRW", rate_data["vndToKrw"])

        push_ok, git_status_line = auto_commit_and_push()
        if not push_ok:
            LOGGER.warning("GitHub push failed; daily Telegram message will include failure status.")

        if should_send_telegram_today(state, today):
            telegram_message = build_telegram_message(rate_data, len(history), git_status_line)
            if send_telegram_message(telegram_message):
                state["last_telegram_date"] = today
                state["last_telegram_ts"] = datetime.now().isoformat()
                save_json(STATE_FILE, state)
        else:
            LOGGER.info("Telegram already sent for %s, skipping duplicate.", today)

        if not push_ok:
            return 2

        LOGGER.info("=" * 56)
        LOGGER.info("Done")
        LOGGER.info("=" * 56)
        return 0
    except Exception as exc:
        LOGGER.exception("Unhandled collector error: %s", exc)
        return fail_with_alert(3, "Unhandled collector error", [str(exc)])


if __name__ == "__main__":
    sys.exit(main())
