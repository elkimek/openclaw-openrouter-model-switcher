#!/usr/bin/env python3
"""Budget control for the OpenRouter model switcher.

Usage:
    budget-ctl.py status                            Show budget, spend, tiers, and estimate
    budget-ctl.py set <amount>                      Set a fixed daily budget in USD
    budget-ctl.py auto [days]                       Auto-scale budget (default: 30 days)
    budget-ctl.py tiers                             Show model tiers
    budget-ctl.py tiers set <key> <model> [<pct>]   Create or update a tier
    budget-ctl.py tiers remove <key>                Remove a tier
    budget-ctl.py tiers reset                       Reset tiers to defaults
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
    {"threshold": 35, "key": "gpt",    "model": "openrouter/x-ai/grok-4.20-beta"},
    {"threshold": 65, "key": "kimi",   "model": "openrouter/openai/gpt-4.1-mini"},
    {"threshold": 90, "key": "cheap",  "model": "openrouter/qwen/qwen3-235b-a22b-2507"},
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def die(msg: str):
    print(msg, file=sys.stderr)
    raise SystemExit(1)


def ensure_state_dir():
    STATE_DIR.mkdir(parents=True, exist_ok=True)


def get_balance_json() -> dict:
    result = subprocess.run(
        [sys.executable, str(BALANCE_SCRIPT)],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        die(f"Error fetching balance: {result.stderr.strip()}")
    return json.loads(result.stdout.strip())


def load_override() -> dict | None:
    if not OVERRIDE_FILE.exists():
        return None
    try:
        return json.loads(OVERRIDE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def save_override(data: dict) -> None:
    ensure_state_dir()
    OVERRIDE_FILE.write_text(json.dumps(data, indent=2))


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


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
    ensure_state_dir()
    TIERS_FILE.write_text(json.dumps(
        {"tiers": sorted(tiers, key=lambda t: t["threshold"])}, indent=2
    ))


def resolve_auto_budget(remaining: float, target_days: int) -> float:
    if remaining <= 0 or target_days <= 0:
        return 0.01
    return round(remaining / target_days, 2)


def normalize_model(model: str) -> str:
    """Auto-prefix openrouter/ if the model looks like provider/name without it."""
    model = model.strip()
    parts = model.split("/")
    if len(parts) >= 3 and parts[0] == "openrouter":
        return model
    if len(parts) == 2:
        return f"openrouter/{model}"
    return model


def resolve_budget_and_mode(balance: dict) -> tuple[float, str]:
    override = load_override()
    remaining = balance["remaining"]
    if override and override.get("mode") == "fixed":
        budget = override["budget"]
        return budget, f"fixed ${budget:.2f}/day"
    target_days = (override or {}).get("target_days", DEFAULT_TARGET_DAYS)
    budget = resolve_auto_budget(remaining, target_days)
    return budget, f"auto ${budget:.2f}/day ({target_days}d)"


def parse_int(value: str, label: str) -> int:
    try:
        return int(value)
    except ValueError:
        die(f"{label} must be an integer, got: {value!r}")


def parse_float(value: str, label: str) -> float:
    try:
        return float(value)
    except ValueError:
        die(f"{label} must be a number, got: {value!r}")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_status():
    load_env_file(SCRIPT_DIR / ".env")
    balance = get_balance_json()
    state = load_state()
    tiers = load_tiers()

    budget, mode = resolve_budget_and_mode(balance)
    daily = balance["usage_daily"]
    remaining = balance["remaining"]
    pct = min(100, (daily / budget) * 100) if budget > 0 else 100
    current_tier = state.get("current_tier", "unknown")

    # Estimate days remaining at weekly average (more stable than daily)
    avg_daily = balance.get("usage_weekly", daily * 7) / 7
    if avg_daily > 0.01:
        days_left = round(remaining / avg_daily)
    else:
        days_left = None  # no meaningful data yet

    # Mark active tier
    tier_list = []
    for t in tiers:
        entry = {
            "threshold": t["threshold"],
            "key": t["key"],
            "model": t["model"],
        }
        if t["key"] == current_tier:
            entry["active"] = True
        tier_list.append(entry)

    result = {
        "mode": mode,
        "daily_budget": round(budget, 2),
        "daily_spend": round(daily, 2),
        "daily_pct": round(pct),
        "remaining": remaining,
        "current_tier": current_tier,
        "tiers": tier_list,
    }
    if days_left is not None:
        result["days_left"] = days_left

    print(json.dumps(result, indent=2))


def cmd_set(amount: float):
    if amount <= 0:
        die("Budget must be a positive number (e.g. 5 for $5/day)")
    save_override({"mode": "fixed", "budget": amount})
    print(json.dumps({"ok": True, "mode": "fixed", "budget": amount}))


def cmd_auto(target_days: int):
    if target_days <= 0:
        die("Target days must be positive")
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


def cmd_tiers():
    tiers = load_tiers()
    current_tier = load_state().get("current_tier")
    for t in tiers:
        if t["key"] == current_tier:
            t["active"] = True
    print(json.dumps({"tiers": tiers}, indent=2))


def cmd_tiers_set(key: str, model: str, threshold: int | None = None):
    """Create or update a tier. If key exists, update model (and threshold if given).
    If key doesn't exist, threshold is required to create it."""
    model = normalize_model(model)
    tiers = load_tiers()
    existing = next((t for t in tiers if t["key"] == key), None)

    if existing:
        existing["model"] = model
        if threshold is not None:
            if threshold < 0 or threshold > 100:
                die("Threshold must be 0-100")
            for t in tiers:
                if t["key"] != key and t["threshold"] == threshold:
                    die(f"Threshold {threshold}% is already used by tier '{t['key']}'")
            existing["threshold"] = threshold
        save_tiers(tiers)
        print(json.dumps({"ok": True, "action": "updated", "key": key,
                          "model": model, "threshold": existing["threshold"],
                          "tiers": sorted(tiers, key=lambda t: t["threshold"])}))
    else:
        if threshold is None:
            die(f"Tier '{key}' doesn't exist yet — provide a threshold: tiers set {key} {model} <pct>")
        if threshold < 0 or threshold > 100:
            die("Threshold must be 0-100")
        for t in tiers:
            if t["threshold"] == threshold:
                die(f"Threshold {threshold}% is already used by tier '{t['key']}'")
        tiers.append({"threshold": threshold, "key": key, "model": model})
        save_tiers(tiers)
        print(json.dumps({"ok": True, "action": "created", "key": key,
                          "model": model, "threshold": threshold,
                          "tiers": sorted(tiers, key=lambda t: t["threshold"])}))


def cmd_tiers_remove(key: str):
    tiers = load_tiers()
    new_tiers = [t for t in tiers if t["key"] != key]
    if len(new_tiers) == len(tiers):
        die(f"Tier '{key}' not found")
    if not new_tiers:
        die("Cannot remove the last tier")
    save_tiers(new_tiers)
    print(json.dumps({"ok": True, "action": "removed", "key": key,
                      "tiers": new_tiers}))


def cmd_tiers_reset():
    save_tiers(list(DEFAULT_TIERS))
    print(json.dumps({"ok": True, "action": "reset", "tiers": DEFAULT_TIERS}))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("--help", "-h", "help"):
        print(__doc__.strip())
        raise SystemExit(0)

    cmd = sys.argv[1]

    if cmd == "status":
        cmd_status()
    elif cmd == "set":
        if len(sys.argv) < 3:
            die("Usage: set <amount>")
        cmd_set(parse_float(sys.argv[2], "Budget"))
    elif cmd == "auto":
        days = parse_int(sys.argv[2], "Days") if len(sys.argv) > 2 else DEFAULT_TARGET_DAYS
        cmd_auto(days)
    elif cmd == "tiers":
        if len(sys.argv) < 3:
            cmd_tiers()
        elif sys.argv[2] == "set":
            if len(sys.argv) < 5:
                die("Usage: tiers set <key> <model> [<threshold_pct>]")
            key = sys.argv[3]
            model = sys.argv[4]
            threshold = parse_int(sys.argv[5], "Threshold") if len(sys.argv) > 5 else None
            cmd_tiers_set(key, model, threshold)
        elif sys.argv[2] == "remove":
            if len(sys.argv) < 4:
                die("Usage: tiers remove <key>")
            cmd_tiers_remove(sys.argv[3])
        elif sys.argv[2] == "reset":
            cmd_tiers_reset()
        else:
            die(f"Unknown tiers subcommand: {sys.argv[2]}")
    else:
        die(f"Unknown command: {cmd}. Run with --help for usage.")


if __name__ == "__main__":
    main()
