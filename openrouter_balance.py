#!/usr/bin/env python3

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

API_BASE = "https://openrouter.ai/api/v1"
DEFAULT_ENV_FILE = Path(__file__).resolve().with_name(".env")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Return OpenRouter credit balance and usage."
    )
    parser.add_argument(
        "--daily-usage",
        action="store_true",
        help="Print only today's usage in USD (e.g. 0.82).",
    )
    parser.add_argument(
        "--remaining",
        action="store_true",
        help="Print only remaining credits in USD.",
    )
    parser.add_argument(
        "--key-env",
        default="OPENROUTER_API_KEY",
        help="Environment variable holding the API key (default: OPENROUTER_API_KEY).",
    )
    return parser.parse_args()


def fail(message: str, exit_code: int = 1):
    print(message, file=sys.stderr)
    raise SystemExit(exit_code)


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def load_key(env_name: str) -> str:
    value = os.environ.get(env_name)
    if not value:
        fail(f"missing environment variable: {env_name}")
    return value


def api_get(path: str, api_key: str) -> dict:
    request = urllib.request.Request(
        f"{API_BASE}{path}",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "User-Agent": "openrouter-balance/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:300]
        # Avoid logging error bodies that may echo back the API key
        safe_body = body if "sk-or-" not in body else "(redacted — may contain credentials)"
        fail(f"request failed ({exc.code}): {safe_body}")
    except urllib.error.URLError as exc:
        fail(f"network error: {exc.reason}")


def main() -> int:
    args = parse_args()
    env_file = Path(
        os.environ.get("OPENROUTER_BALANCE_ENV_FILE", str(DEFAULT_ENV_FILE))
    ).expanduser()
    load_env_file(env_file)
    api_key = load_key(args.key_env)

    auth = api_get("/auth/key", api_key).get("data", {})
    credits = api_get("/credits", api_key).get("data", {})

    total_credits = credits.get("total_credits", 0)
    total_usage = credits.get("total_usage", 0)
    remaining = round(total_credits - total_usage, 2)
    daily = auth.get("usage_daily", 0)

    if args.daily_usage:
        print(daily)
    elif args.remaining:
        print(remaining)
    else:
        print(json.dumps({
            "total_credits": total_credits,
            "total_usage": round(total_usage, 2),
            "remaining": remaining,
            "usage_daily": daily,
            "usage_weekly": auth.get("usage_weekly", 0),
            "usage_monthly": auth.get("usage_monthly", 0),
        }, separators=(",", ":"), sort_keys=True))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
