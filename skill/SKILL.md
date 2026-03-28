---
name: budget
description: "View or change the OpenRouter daily spending budget and model tiers. Use when: user asks about budget, spending, credits, model tier, cost, or says /budget. Examples: '/budget', '/budget set 5', '/budget auto', '/budget tiers', '/budget tiers set cheap gemini-3-flash'."
user-invocable: true
metadata: { "openclaw": { "requires": { "bins": ["python3"] } } }
---

# Budget Skill

Manage the OpenRouter daily spending budget and model tier switching.

The base command is:
```
python3 /home/elkim/.openclaw/openrouter-model-switcher/budget-ctl.py
```

## Parsing user input

The user may say things casually. Map their intent to the right subcommand:

- "budget", "status", "how much", "spending" -> `status`
- a bare number like "/budget 5" -> `set 5`
- "auto", "auto 60 days" -> `auto [days]`
- "tiers", "models", "what models", "ladder" -> `tiers`
- "set cheap to gemini flash", "change cheap model to X" -> `tiers set cheap <model>`
- "add a tier at 50% called mid with gemini" -> `tiers set mid <model> 50`
- "remove the kimi tier" -> `tiers remove kimi`
- "reset tiers", "default tiers" -> `tiers reset`

## Commands

### status (default — no args)

```bash
budget-ctl.py status
```

Present the JSON response in a readable format:
- Mode and daily budget
- Today's spend and % of budget
- Remaining credits and estimated days left
- Current tier (marked with an arrow or star in the tier list)

### set <amount>

```bash
budget-ctl.py set 5
```

Sets a fixed daily budget. Confirm the new amount.

### auto [days]

```bash
budget-ctl.py auto 30
```

Auto-scales: remaining credits / target days = daily budget. Default 30 days.

### tiers

```bash
budget-ctl.py tiers
```

Show all tiers as a table. The active tier has `"active": true`.

### tiers set <key> <model> [<threshold>]

```bash
budget-ctl.py tiers set cheap "google/gemini-3-flash"
budget-ctl.py tiers set mid "minimax/minimax-m2.5" 55
```

Creates or updates a tier. Notes:
- Model auto-prefixes `openrouter/` — user can say just `anthropic/claude-sonnet-4.6` or `google/gemini-3-flash`
- If the key already exists, updates the model (and threshold if provided)
- If the key is new, threshold is required
- Duplicate thresholds are rejected

### tiers remove <key>

```bash
budget-ctl.py tiers remove kimi
```

### tiers reset

```bash
budget-ctl.py tiers reset
```

Restores the 4 default tiers (sonnet/gpt/kimi/cheap).
