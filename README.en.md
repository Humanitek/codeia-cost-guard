# cost-guard

Measures, and helps to stop, the token spend of your agent fleet: **Claude Code, Codex, OpenCode, pi**.
It reads their local logs, discards duplicate turns, and shows the result in a panel and a menu bar
icon. Everything in **tokens**: the **five-hour window** (the one that runs out on subscription plans),
the week, the day, turns and cache. Dollar figures are an informative API equivalent, not your bill.

Built and maintained by [Asociación Humanitek](https://humanitek.org).

## Why

It is not the model's effort that ruins you: it is **how many times you send it the context**. About
75% of typical spend is cache read — the same context sent again turn after turn. And past
**272,000 tokens** the whole request is billed at a higher input rate. With this in front of you, a
working day is visible at a glance.

## Features

- **Five-hour window** and **week** in tokens, keeping Claude and OpenAI separate (they are different subscriptions).
- **Today**: input, output, cache read (with its share of input) and cache written.
- **Turns**: every round trip resends the context, and that is where the money goes.
- **Rate of the last hour**, with an alert when it crosses a limit.
- Breakdown **by day, by model and by project**.
- **Local SQLite store**, so history survives the thirty days after which Claude Code deletes its logs.
- **Encrypted backups** with verified restores.
- **Budgets** per project or per plan, monthly or weekly, with warnings at 80% and 100%.
- **Price estimation before sending** a request, including the 272k cliff, cache, Batch and Fast.
- **Saving rules** you can paste into your agents' global instruction files, in one idempotent command.
- **Metering only in the core**: the panel, the CLI report and the price calculator run on Python 3.9+ with no dependencies.

## Install

```bash
git clone https://github.com/Humanitek/codeia-cost-guard.git
cd codeia-cost-guard

# macOS: menu bar app + panel + optional saving rules
./install.sh

# Any system: meter and panel only (Python 3.9+)
python3 analizar_gasto.py      # terminal report
python3 panel.py               # writes panel.html and opens it in your browser
```

On Windows, `python instalar_windows.py` sets up a tray icon and start-up entry. The core scripts work
the same on macOS, Linux and Windows.

## How it counts

Two different log formats, and confusing them inflates the totals (learned the hard way):

- **Claude Code** writes **several lines per message** (one per block: thinking, text, tool) with the
  same input and cache and a growing output. The real message is the last line. It is counted **once
  per message**. Until the 2026-10-14 version every line was counted and Claude Code usage came out
  inflated by roughly 40%.
- **Codex** writes each turn **twice** (`token_usage_record` and `event_msg/token_count`, in the same
  second), and the file also carries `total_token_usage`, which is **cumulative**. The turn usage must
  be used, ignoring the cumulative figure, and `cached_input_tokens` sits **inside** `input_tokens`.

Logs are read from `~/.claude`, `~/.codex` and `~/.opencode`; only **unique** turns are kept, because
Claude Code forks copy their parent's turns and would be counted twice. List prices per model are applied.

**Dollar figures are API equivalent**, not your invoice: on a subscription you do not pay per token, but
what runs out is exactly what is measured here — tokens × turns. Agents running in the cloud leave no
local log: run the meter on those machines and add the totals.

## Configure your plans

Logs say which model was used, never which quota you have — only your provider knows that. Declare each
plan in `config.json` and the panel will measure **per plan**, with the percentage of the five-hour and
weekly window consumed:

```bash
python3 costbar.py --proveedores    # lists your models per provider and prints ready-to-paste config
```

API keys are stored in the system credential store (Keychain on macOS, Credential Manager on Windows),
never in `config.json` and never in git.

## Tests

```bash
python3 -m unittest discover tests
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Changes per release are in [CHANGELOG.md](CHANGELOG.md).

## Licence

MIT.
