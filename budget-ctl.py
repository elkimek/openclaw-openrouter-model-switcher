#!/usr/bin/env python3
"""Budget control for the OpenRouter model switcher.

Usage:
    budget-ctl.py status                        Show current budget, spend, and tier
    budget-ctl.py set <amount>                  Set a fixed daily budget in USD
    budget-ctl.py auto [days]                   Switch to auto-scaling (default: 30 days)
    budget-ctl.py get-days                      Print target days for auto mode
    budget-ctl.py tiers                         Show current model tiers
    budget-ctl.py tiers set <key>=<model>       Change a tier's model
    budget-ctl.py tiers add <pct> <key>=<model> Add a new tier at threshold %
    budget-ctl.py tiers remove <key>            Remove a tier
    budget-ctl.py tiers reset                   Reset tiers to defaults
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
TIERS_FILE = STATE_DIR / "or-tiers.json"
BALANCE_SCRIPT = SCRIPT_DIR / "openrouter_balance.py"
DEFAULT_TARGET_DAYS = 30

DEFAULT_TIERS = [
    {"threshold": 0,  "key": "sonnet", "model": "openrouter/anthropic/claude-sonnet-4.6"},
    {"threshold": 40, "key": "gpt",    "model": "openrouter/openai/gpt-5.4"},
    {"threshold": 70, "key": "kimi",   "model": "openrouter/moonshotai/kimi-k2.5"},
    {"threshold": 90, "key": "cheap",  "model": "openrouter/qwen/qwen3.5-9b"},
]


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


def load_tiers() -> list[dict]:
    if TIERS_FILE.exists():
        try:
            data = json.loads(TIERS_FILE.read_text())
            tiers = data.get("tiers", [])
            if tiers and all(
                isinstance(t, dict) and "threshold" in t and "key" in t and "model" in t
                for t in tiers
            ):
                return sorted(tiers, key=lambda t: t["threshold"])
        except (json.JSONDecodeError, OSError):
            pass
    return list(DEFAULT_TIERS)


def save_tiers(tiers: list[dict]) -> None:
    sorted_tiers = sorted(tiers, key=lambda t: t["threshold"])
    TIERS_FILE.write_text(json.dumps({"tiers": sorted_tiers}, indent=2))


def cmd_tiers():
    tiers = load_tiers()
    print(json.dumps({"tiers": tiers}, indent=2))


def cmd_tiers_set(assignment: str):
    if "=" not in assignment:
        print("Usage: tiers set <key>=<model>", file=sys.stderr)
        raise SystemExit(1)
    key, model = assignment.split("=", 1)
    key = key.strip()
    model = model.strip()
    if not key or not model:
        print("Both key and model must be non-empty", file=sys.stderr)
        raise SystemExit(1)
    tiers = load_tiers()
    found = False
    for t in tiers:
        if t["key"] == key:
            t["model"] = model
            found = True
            break
    if not found:
        print(f"Tier '{key}' not found. Use 'tiers add' to create a new tier.", file=sys.stderr)
        raise SystemExit(1)
    save_tiers(tiers)
    print(json.dumps({"ok": True, "action": "set", "key": key, "model": model, "tiers": sorted(tiers, key=lambda t: t["threshold"])}))


def cmd_tiers_add(threshold_str: str, assignment: str):
    try:
        threshold = int(threshold_str)
    except ValueError:
        print(f"Threshold must be an integer, got: {threshold_str}", file=sys.stderr)
        raise SystemExit(1)
    if threshold < 0 or threshold > 100:
        print("Threshold must be 0-100", file=sys.stderr)
        raise SystemExit(1)
    if "=" not in assignment:
        print("Usage: tiers add <pct> <key>=<model>", file=sys.stderr)
        raise SystemExit(1)
    key, model = assignment.split("=", 1)
    key = key.strip()
    model = model.strip()
    if not key or not model:
        print("Both key and model must be non-empty", file=sys.stderr)
        raise SystemExit(1)
    tiers = load_tiers()
    for t in tiers:
        if t["key"] == key:
            print(f"Tier '{key}' already exists. Use 'tiers set' to change it.", file=sys.stderr)
            raise SystemExit(1)
    tiers.append({"threshold": threshold, "key": key, "model": model})
    save_tiers(tiers)
    print(json.dumps({"ok": True, "action": "add", "key": key, "threshold": threshold, "model": model, "tiers": sorted(tiers, key=lambda t: t["threshold"])}))


def cmd_tiers_remove(key: str):
    tiers = load_tiers()
    new_tiers = [t for t in tiers if t["key"] != key]
    if len(new_tiers) == len(tiers):
        print(f"Tier '{key}' not found", file=sys.stderr)
        raise SystemExit(1)
    if not new_tiers:
        print("Cannot remove the last tier", file=sys.stderr)
        raise SystemExit(1)
    save_tiers(new_tiers)
    print(json.dumps({"ok": True, "action": "remove", "key": key, "tiers": sorted(new_tiers, key=lambda t: t["threshold"])}))


def cmd_tiers_reset():
    save_tiers(list(DEFAULT_TIERS))
    print(json.dumps({"ok": True, "action": "reset", "tiers": DEFAULT_TIERS}))


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
    elif cmd == "tiers":
        if len(sys.argv) < 3:
            cmd_tiers()
        elif sys.argv[2] == "set":
            if len(sys.argv) < 4:
                print("Usage: tiers set <key>=<model>", file=sys.stderr)
                raise SystemExit(1)
            cmd_tiers_set(sys.argv[3])
        elif sys.argv[2] == "add":
            if len(sys.argv) < 5:
                print("Usage: tiers add <pct> <key>=<model>", file=sys.stderr)
                raise SystemExit(1)
            cmd_tiers_add(sys.argv[3], sys.argv[4])
        elif sys.argv[2] == "remove":
            if len(sys.argv) < 4:
                print("Usage: tiers remove <key>", file=sys.stderr)
                raise SystemExit(1)
            cmd_tiers_remove(sys.argv[3])
        elif sys.argv[2] == "reset":
            cmd_tiers_reset()
        else:
            print(f"Unknown tiers subcommand: {sys.argv[2]}", file=sys.stderr)
            raise SystemExit(1)
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
