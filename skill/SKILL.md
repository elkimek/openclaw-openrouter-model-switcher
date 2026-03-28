---
name: budget
description: "View or change the OpenRouter daily spending budget. Use when: user asks about budget, spending, credits, model tier, or says /budget. Examples: '/budget', '/budget status', '/budget set 5', '/budget auto', '/budget auto 20'."
user-invocable: true
metadata: { "openclaw": { "requires": { "bins": ["python3"] } } }
---

# Budget Skill

Manage the OpenRouter daily spending budget that controls automatic model tier switching.

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

Confirm the change to the user.

### Switch to auto mode

User says `/budget auto` or `/budget auto 20` (with optional target days).

Auto mode calculates: `remaining_credits / target_days = daily_budget`

```bash
python3 /home/elkim/.openclaw/openrouter-model-switcher/budget-ctl.py auto [days]
```

Default target is 30 days if not specified. Confirm the change and show the computed daily budget.

## Model tiers

The switcher uses these tiers based on % of daily budget spent:

| Daily spend % | Model |
|---|---|
| 0-40% | Claude Sonnet 4.6 |
| 40-70% | GPT-5.4 |
| 70-90% | Kimi K2.5 |
| 90%+ | Qwen3.5 9B |

The tier changes automatically every 10 minutes via a systemd timer.
