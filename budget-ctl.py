#!/usr/bin/env python3
"""Budget control for the OpenRouter model switcher.

Usage:
    budget-ctl.py status          Show current budget, spend, and tier
    budget-ctl.py set <amount>    Set a fixed daily budget in USD
    budget-ctl.py auto [days]     Switch to auto-scaling (default: 30 days)
    budget-ctl.py get-days        Print target days for auto mode
"""

import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
STATE_DIR = Path.home() / ".openclaw"
OVERRIDE_FILE = STATE_DIR / "or-budget-override.json"
STATE_FILE = STATE_DIR / "or-switch-state.json"
BALANCE_SCRIPT = SCRIPT_DIR / "openrouter_balance.py"
DEFAULT_TARGET_DAYS = 30


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


def get_balance_json() -> dict:
    result = subprocess.run(
        [sys.executable, str(BALANCE_SCRIPT)],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        print(f"Error fetching balance: {result.stderr.strip()}", file=sys.stderr)
        raise SystemExit(1)
    return json.loads(result.stdout.strip())


def load_override() -> dict | None:
    if not OVERRIDE_FILE.exists():
        return None
    try:
        return json.loads(OVERRIDE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def save_override(data: dict) -> None:
    OVERRIDE_FILE.write_text(json.dumps(data, indent=2))


def remove_override() -> None:
    if OVERRIDE_FILE.exists():
        OVERRIDE_FILE.unlink()


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def resolve_auto_budget(remaining: float, target_days: int) -> float:
    if remaining <= 0 or target_days <= 0:
        return 0.01
    return round(remaining / target_days, 2)


def cmd_status():
    load_env_file(SCRIPT_DIR / ".env")
    balance = get_balance_json()
    override = load_override()
    state = load_state()
    remaining = balance["remaining"]

    if override and override.get("mode") == "fixed":
        budget = override["budget"]
        mode = f"fixed (${budget:.2f}/day)"
    else:
        target_days = (override or {}).get("target_days", DEFAULT_TARGET_DAYS)
        budget = resolve_auto_budget(remaining, target_days)
        mode = f"auto (${budget:.2f}/day over {target_days}d)"

    daily = balance["usage_daily"]
    pct = min(100, (daily / budget) * 100) if budget > 0 else 100
    tier = state.get("current_tier", "unknown")

    print(json.dumps({
        "mode": mode,
        "daily_budget": round(budget, 2),
        "daily_spend": daily,
        "daily_pct": round(pct),
        "remaining": remaining,
        "current_tier": tier,
    }, indent=2))


def cmd_set(amount: float):
    if amount <= 0:
        print("Budget must be positive", file=sys.stderr)
        raise SystemExit(1)
    save_override({"mode": "fixed", "budget": amount})
    print(json.dumps({"ok": True, "mode": "fixed", "budget": amount}))


def cmd_auto(target_days: int):
    if target_days <= 0:
        print("Target days must be positive", file=sys.stderr)
        raise SystemExit(1)
    remove_override()
    save_override({"mode": "auto", "target_days": target_days})
    load_env_file(SCRIPT_DIR / ".env")
    balance = get_balance_json()
    budget = resolve_auto_budget(balance["remaining"], target_days)
    print(json.dumps({
        "ok": True, "mode": "auto",
        "target_days": target_days,
        "computed_budget": budget,
        "remaining": balance["remaining"],
    }))


def cmd_get_days():
    override = load_override()
    days = (override or {}).get("target_days", DEFAULT_TARGET_DAYS)
    print(days)


def main():
    if len(sys.argv) < 2:
        print(__doc__.strip())
        raise SystemExit(1)

    cmd = sys.argv[1]
    if cmd == "status":
        cmd_status()
    elif cmd == "set":
        if len(sys.argv) < 3:
            print("Usage: budget-ctl.py set <amount>", file=sys.stderr)
            raise SystemExit(1)
        cmd_set(float(sys.argv[2]))
    elif cmd == "auto":
        days = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_TARGET_DAYS
        cmd_auto(days)
    elif cmd == "get-days":
        cmd_get_days()
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
