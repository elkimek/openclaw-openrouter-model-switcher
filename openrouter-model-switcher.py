#!/usr/bin/env python3

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
STATE_DIR = Path.home() / ".openclaw"
LOG_FILE = Path(
    os.environ.get("OR_SWITCH_LOG_FILE", str(STATE_DIR / "or-switch.log"))
).expanduser()
STATE_FILE = Path(
    os.environ.get("OR_SWITCH_STATE_FILE", str(STATE_DIR / "or-switch-state.json"))
).expanduser()
DEFAULT_BALANCE_SCRIPT = SCRIPT_DIR / "openrouter_balance.py"
DEFAULT_OPENCLAW_BIN = Path.home() / ".npm-global" / "bin" / "openclaw"
DEFAULT_ENV_FILE = SCRIPT_DIR / ".env"

# Daily budget in USD. When daily spend reaches this, you're at 100%.
DEFAULT_DAILY_BUDGET = 3.0
DEFAULT_TARGET_DAYS = 30
OVERRIDE_FILE = STATE_DIR / "or-budget-override.json"
TIERS_FILE = STATE_DIR / "or-tiers.json"

# Default tiers used when or-tiers.json doesn't exist.
DEFAULT_TIERS = [
    {"threshold": 0,  "key": "sonnet", "model": "openrouter/anthropic/claude-sonnet-4.6"},
    {"threshold": 40, "key": "gpt",    "model": "openrouter/openai/gpt-5.4"},
    {"threshold": 70, "key": "kimi",   "model": "openrouter/moonshotai/kimi-k2.5"},
    {"threshold": 90, "key": "cheap",  "model": "openrouter/qwen/qwen3.5-9b"},
]


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Switch the default OpenClaw model based on OpenRouter daily spend."
    )
    parser.add_argument(
        "--query-sessions", action="store_true",
        help="Always query and patch sessions even when tier unchanged.",
    )
    parser.add_argument(
        "--daily-budget", type=float, default=None,
        help=f"Daily budget in USD (default: ${DEFAULT_DAILY_BUDGET:.0f}, or OR_DAILY_BUDGET env).",
    )
    return parser.parse_args()


LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)


def fail(message: str, exit_code: int = 1):
    log.error(message)
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


def parse_json_from_output(stdout: str) -> object:
    decoder = json.JSONDecoder()
    for marker in ("{", "["):
        idx = stdout.find(marker)
        if idx >= 0:
            obj, _ = decoder.raw_decode(stdout, idx)
            return obj
    raise ValueError("no JSON payload found in stdout")


def run_command(command: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout,
            env={**os.environ, "NO_COLOR": "1"},
        )
    except subprocess.TimeoutExpired as exc:
        fail(f"command timed out after {timeout}s: {' '.join(command)}")
    if result.returncode != 0:
        fail(
            f"command failed ({result.returncode}): {' '.join(command)} | "
            f"stderr={result.stderr.strip()[:300]!r}"
        )
    return result


def openclaw_bin() -> str:
    configured = os.environ.get("OPENCLAW_BIN")
    if configured:
        return configured
    discovered = shutil.which("openclaw")
    if discovered:
        return discovered
    return str(DEFAULT_OPENCLAW_BIN)


def get_daily_spend() -> float:
    result = run_command(
        [sys.executable, str(DEFAULT_BALANCE_SCRIPT), "--daily-usage"], timeout=30
    )
    return float(result.stdout.strip())


def get_remaining_credits() -> float:
    result = run_command(
        [sys.executable, str(DEFAULT_BALANCE_SCRIPT), "--remaining"], timeout=30
    )
    return float(result.stdout.strip())


def load_budget_override() -> dict | None:
    if not OVERRIDE_FILE.exists():
        return None
    try:
        return json.loads(OVERRIDE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def resolve_daily_budget(args, remaining: float) -> float:
    # CLI flag takes highest priority
    if args.daily_budget is not None:
        return args.daily_budget
    # Check override file (set by budget-ctl.py)
    override = load_budget_override()
    if override:
        if override.get("mode") == "fixed":
            return float(override["budget"])
        if override.get("mode") == "auto":
            target_days = int(override.get("target_days", DEFAULT_TARGET_DAYS))
            if remaining > 0 and target_days > 0:
                return round(remaining / target_days, 2)
    # Env var fallback
    env_val = os.environ.get("OR_DAILY_BUDGET", "").strip()
    if env_val:
        return float(env_val)
    # Default: auto-scale over 30 days
    if remaining > 0:
        return round(remaining / DEFAULT_TARGET_DAYS, 2)
    return DEFAULT_DAILY_BUDGET


def get_target_tier(spent_pct: float, tiers: list[dict]) -> tuple[str, str]:
    """Return (tier_key, model_id) for the given spend percentage."""
    target_key = tiers[0]["key"]
    target_model = tiers[0]["model"]
    for t in tiers:
        if spent_pct >= t["threshold"]:
            target_key = t["key"]
            target_model = t["model"]
    return target_key, target_model


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {"last_default_tier": None, "last_session_patch_tier": None, "last_spent_pct": 0.0}
    raw = json.loads(STATE_FILE.read_text())
    if not isinstance(raw, dict):
        fail(f"invalid state in {STATE_FILE}")
    ct = raw.get("current_tier")
    return {
        "last_default_tier": raw.get("last_default_tier", ct),
        "last_session_patch_tier": raw.get("last_session_patch_tier", ct),
        "last_spent_pct": float(raw.get("last_spent_pct", 0.0)),
    }


def save_state(default_tier, session_patch_tier, spent_pct: float) -> None:
    STATE_FILE.write_text(json.dumps({
        "current_tier": default_tier,
        "last_default_tier": default_tier,
        "last_session_patch_tier": session_patch_tier,
        "last_spent_pct": spent_pct,
        "updated_at": datetime.now().isoformat(),
    }, indent=2))


def gateway_call(method: str, params: dict, timeout_ms: int = 60000) -> dict:
    command = [
        openclaw_bin(), "--no-color", "gateway", "call", method,
        "--json", "--timeout", str(timeout_ms),
        "--params", json.dumps(params, separators=(",", ":")),
    ]
    timeout = max(120, int(timeout_ms / 1000) + 30)
    result = run_command(command, timeout=timeout)
    payload = parse_json_from_output(result.stdout)
    if not isinstance(payload, dict):
        fail(f"{method} did not return a JSON object")
    return payload


def set_default_model(model: str) -> None:
    run_command([openclaw_bin(), "--no-color", "models", "set", model], timeout=120)


def list_sessions() -> list[dict]:
    payload = gateway_call("sessions.list", {})
    sessions = payload.get("sessions")
    if not isinstance(sessions, list):
        fail("sessions.list did not return a sessions array")
    return sessions


def patch_session_model(key: str, model: str) -> dict:
    payload = gateway_call("sessions.patch", {"key": key, "model": model})
    if not payload.get("ok"):
        fail(f"sessions.patch failed for {key}")
    return payload


def normalize_model(session: dict) -> str:
    return str(session.get("modelOverride") or session.get("model") or "").strip()


def is_openrouter_session(session: dict) -> bool:
    provider = str(
        session.get("providerOverride") or session.get("modelProvider") or ""
    ).strip()
    if provider == "openrouter":
        return True
    return normalize_model(session).startswith("openrouter/")


def main() -> int:
    args = parse_args()
    env_file = Path(os.environ.get("OR_SWITCH_ENV_FILE", str(DEFAULT_ENV_FILE))).expanduser()
    load_env_file(env_file)

    daily_spend = get_daily_spend()
    remaining = get_remaining_credits()
    daily_budget = resolve_daily_budget(args, remaining)
    tiers = load_tiers()

    if remaining <= 0:
        log.warning("No credits remaining ($%.2f). Forcing cheapest tier.", remaining)
        spent_pct = 100.0
    else:
        spent_pct = min(100.0, (daily_spend / daily_budget) * 100)

    state = load_state()
    target_tier, target_model = get_target_tier(spent_pct, tiers)

    log.info(
        "daily $%.2f / $%.2f budget (%.0f%%) | remaining $%.2f | tier=%s -> %s | model=%s",
        daily_spend, daily_budget, spent_pct, remaining,
        state.get("last_default_tier"), target_tier, target_model,
    )

    current_default_tier = state.get("last_default_tier")
    current_session_patch_tier = state.get("last_session_patch_tier")

    # Detect daily reset: spent went from high to near-zero
    last_pct = float(state.get("last_spent_pct", 0))
    if last_pct > 30 and spent_pct < 10:
        log.info("Daily reset detected (%.0f%% -> %.0f%%); forcing best tier", last_pct, spent_pct)
        target_tier = tiers[0]["key"]
        target_model = tiers[0]["model"]

    if current_default_tier != target_tier:
        log.info("Switching default model to %s", target_model)
        set_default_model(target_model)
        current_default_tier = target_tier
    else:
        log.info("Tier unchanged; skipping default model switch")

    should_query = args.query_sessions or current_session_patch_tier != current_default_tier
    if should_query:
        log.info("Reconciling sessions for tier %s", current_default_tier)
        try:
            sessions = list_sessions()
            patches = []
            for session in sessions:
                key = str(session.get("key") or "").strip()
                if not key or not is_openrouter_session(session):
                    continue
                current = normalize_model(session)
                if current == target_model:
                    continue
                patches.append((key, current or "(unset)", target_model))

            if not patches:
                log.info("No session patches needed")
            else:
                for key, current, desired in patches:
                    log.info("Patching %s: %s -> %s", key, current, desired)
                    patch_session_model(key, desired)
        except SystemExit:
            save_state(current_default_tier, current_session_patch_tier, spent_pct)
            raise
        current_session_patch_tier = current_default_tier
    else:
        log.info("Tier unchanged; skipping session query")

    save_state(current_default_tier, current_session_patch_tier, spent_pct)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
