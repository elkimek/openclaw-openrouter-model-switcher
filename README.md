# OpenClaw OpenRouter Model Switcher

Automatically switch OpenClaw models based on daily OpenRouter spend. Starts with the best model and degrades to cheaper ones as you approach your daily budget.

Inspired by [jooray/openclaw-venice-model-switcher](https://github.com/jooray/openclaw-venice-model-switcher), adapted for OpenRouter's credit-based billing.

## How it works

- `openrouter_balance.py` queries the OpenRouter billing API (`/auth/key` and `/credits`).
- `openrouter-model-switcher.py` maps daily spend to a model tier, sets the default OpenClaw model, and patches active sessions when the tier changes.
- `budget-ctl.py` lets you view and change the budget from the CLI or via the included OpenClaw `/budget` skill.

## Budget modes

**Auto (default):** Divides remaining credits by a target number of days.

```
$17.14 remaining / 30 days = $0.57/day budget
```

As credits deplete, the daily budget shrinks automatically, making the tiers more aggressive and stretching what's left.

**Fixed:** A flat daily budget you set manually.

## Model tiers

| Daily spend | Tier | Model |
|---|---|---|
| 0-40% | sonnet | `openrouter/anthropic/claude-sonnet-4.6` |
| 40-70% | gpt | `openrouter/openai/gpt-5.4` |
| 70-90% | kimi | `openrouter/moonshotai/kimi-k2.5` |
| 90%+ | cheap | `openrouter/qwen/qwen3.5-9b` |

These are the defaults. Change them at runtime via `budget-ctl.py tiers` or the `/budget` skill — no file editing needed.

## Setup

1. Make sure `python3` is installed.
2. Make sure `openclaw` is on your `PATH`, or set `OPENCLAW_BIN`.
3. Copy `.env.example` to `.env` and add your OpenRouter API key:

```bash
cp .env.example .env
# edit .env
```

4. Run it manually once:

```bash
python3 openrouter-model-switcher.py
```

## Scripts

### `openrouter_balance.py`

Raw OpenRouter balance without changing any settings.

```bash
python3 openrouter_balance.py              # full JSON
python3 openrouter_balance.py --daily-usage # today's spend in USD
python3 openrouter_balance.py --remaining   # remaining credits in USD
```

### `openrouter-model-switcher.py`

The main switcher. Reads daily spend, computes tier, patches the default model and active sessions.

```bash
python3 openrouter-model-switcher.py                    # normal run
python3 openrouter-model-switcher.py --query-sessions   # force session reconciliation
python3 openrouter-model-switcher.py --daily-budget 5   # override budget for this run
```

State file: `~/.openclaw/or-switch-state.json`
Log file: `~/.openclaw/or-switch.log`

### `budget-ctl.py`

View and change the budget and model tiers at runtime.

```bash
python3 budget-ctl.py status                              # budget, spend, tiers, days-left estimate
python3 budget-ctl.py set 5                               # fixed $5/day budget
python3 budget-ctl.py auto                                # auto-scale over 30 days
python3 budget-ctl.py auto 60                             # auto-scale over 60 days
python3 budget-ctl.py tiers                               # show current tiers (active marked)
python3 budget-ctl.py tiers set cheap google/gemini-3-flash          # change a tier's model
python3 budget-ctl.py tiers set mid minimax/minimax-m2.5 55          # add tier at 55%
python3 budget-ctl.py tiers remove mid                               # remove a tier
python3 budget-ctl.py tiers reset                                    # restore defaults
```

Model IDs auto-prefix `openrouter/` — just use `provider/model` (e.g. `anthropic/claude-sonnet-4.6`).

Tiers are stored in `~/.openclaw/or-tiers.json`. Duplicate thresholds are rejected.

### OpenClaw `/budget` skill

Copy `skill/SKILL.md` to your OpenClaw workspace skills directory:

```bash
mkdir -p ~/.openclaw/workspace/skills/budget
cp skill/SKILL.md ~/.openclaw/workspace/skills/budget/SKILL.md
```

Then use `/budget`, `/budget set 5`, `/budget tiers`, etc. from any connected channel (Matrix, SimpleX, etc.). The skill handles natural language — saying "change cheap to gemini flash" or "add a tier at 50%" works.

**Note:** The skill references absolute paths. Update the paths in `SKILL.md` if your install location differs from `~/.openclaw/openrouter-model-switcher/`.

## Scheduling

Run the switcher every 5-10 minutes.

### cron

```cron
*/10 * * * * /usr/bin/python3 /path/to/openrouter-model-switcher.py >> /tmp/openrouter-model-switcher.log 2>&1
```

### systemd

Example unit files are in `systemd/`. They are user units.

```bash
mkdir -p ~/.config/systemd/user
cp systemd/openrouter-model-switcher.service ~/.config/systemd/user/
cp systemd/openrouter-model-switcher.timer ~/.config/systemd/user/
# Edit the paths in the .service file to match your install location
systemctl --user daemon-reload
systemctl --user enable --now openrouter-model-switcher.timer
```

On unattended hosts:

```bash
loginctl enable-linger "$USER"
```

## Environment variables

| Variable | Description |
|---|---|
| `OPENROUTER_API_KEY` | Required. Your OpenRouter API key. |
| `OPENCLAW_BIN` | Optional path to the OpenClaw binary. |
| `OR_DAILY_BUDGET` | Optional fallback daily budget in USD. |
| `OR_SWITCH_ENV_FILE` | Optional path to `.env` for the switcher. |
| `OR_SWITCH_LOG_FILE` | Optional log file path. |
| `OR_SWITCH_STATE_FILE` | Optional state file path. |
| `OPENROUTER_BALANCE_ENV_FILE` | Optional path to `.env` for the balance script. |

## Credits

- Based on [jooray/openclaw-venice-model-switcher](https://github.com/jooray/openclaw-venice-model-switcher) by [Juraj Bednar](https://github.com/jooray)
- OpenRouter model switching adapted from the Venice DIEM tiering concept

## Related

- [OpenClaw setup guide](https://juraj.bednar.io/en/blog-en/2026/03/21/openclaw-the-cypherpunk-ish-way/)
- [Venice model switcher (original)](https://github.com/jooray/openclaw-venice-model-switcher)
