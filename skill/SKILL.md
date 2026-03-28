---
name: budget
description: "View or change the OpenRouter daily spending budget and model tiers. Use when: user asks about budget, spending, credits, model tier, or says /budget. Examples: '/budget', '/budget set 5', '/budget auto', '/budget tiers', '/budget tiers set cheap=openrouter/google/gemini-3-flash'."
user-invocable: true
metadata: { "openclaw": { "requires": { "bins": ["python3"] } } }
---

# Budget Skill

Manage the OpenRouter daily spending budget and model tier switching.

## Usage

The user says `/budget` with an optional subcommand. Parse their intent and run the matching command below.

## Commands

### Status (default)

Show current budget mode, daily spend, remaining credits, and active tier.

```bash
python3 /home/elkim/.openclaw/openrouter-model-switcher/budget-ctl.py status
```

Present the JSON output to the user in a readable format like:
- **Mode**: auto ($0.57/day over 30d) or fixed ($5.00/day)
- **Today**: $0.82 spent (27% of budget)
- **Credits**: $17.14 remaining
- **Tier**: sonnet (openrouter/anthropic/claude-sonnet-4.6)

### Set fixed budget

User says `/budget set 5` or `/budget 5` (a number).

```bash
python3 /home/elkim/.openclaw/openrouter-model-switcher/budget-ctl.py set <amount>
```

### Switch to auto mode

User says `/budget auto` or `/budget auto 20`.

```bash
python3 /home/elkim/.openclaw/openrouter-model-switcher/budget-ctl.py auto [days]
```

Default target is 30 days if not specified.

### Show tiers

User says `/budget tiers`.

```bash
python3 /home/elkim/.openclaw/openrouter-model-switcher/budget-ctl.py tiers
```

Show the tiers as a table with threshold %, tier name, and model.

### Change a tier's model

User says `/budget tiers set <key>=<model>`, e.g. `/budget tiers set cheap=openrouter/google/gemini-3-flash`.

```bash
python3 /home/elkim/.openclaw/openrouter-model-switcher/budget-ctl.py tiers set "<key>=<model>"
```

The key must match an existing tier name (sonnet, gpt, kimi, cheap, etc.).

### Add a new tier

User says `/budget tiers add <pct> <key>=<model>`, e.g. `/budget tiers add 50 mid=openrouter/google/gemini-3-flash`.

```bash
python3 /home/elkim/.openclaw/openrouter-model-switcher/budget-ctl.py tiers add <pct> "<key>=<model>"
```

### Remove a tier

User says `/budget tiers remove <key>`.

```bash
python3 /home/elkim/.openclaw/openrouter-model-switcher/budget-ctl.py tiers remove <key>
```

### Reset tiers to defaults

User says `/budget tiers reset`.

```bash
python3 /home/elkim/.openclaw/openrouter-model-switcher/budget-ctl.py tiers reset
```

## Default tiers

| Threshold | Key | Model |
|---|---|---|
| 0% | sonnet | openrouter/anthropic/claude-sonnet-4.6 |
| 40% | gpt | openrouter/openai/gpt-5.4 |
| 70% | kimi | openrouter/moonshotai/kimi-k2.5 |
| 90% | cheap | openrouter/qwen/qwen3.5-9b |

The tier changes automatically every 10 minutes via a systemd timer.
