# Keystrike

Adaptive drills for your weakest keys — an offline terminal typing tutor inspired by
[keybr.com](https://www.keybr.com/). Stats stay on your machine; nothing phones home.

![Keystrike demo](https://raw.githubusercontent.com/egno/keystrike/v1.1.0/docs/assets/demo.gif)

## What it does

Keystrike tracks how fast and accurately you type each key, unlocks new letters as
you hit your targets, and generates practice text that overweight your current weak
spot. Switch keyboard layouts (QWERTY, Dvorak, Colemak, Colemak Mod-DH, or your own
TOML) and each layout keeps its own history.

## Features

- **Adaptive engine** — row-weighted key unlock order, speed+accuracy confidence
  gates, Markov word drills with a guaranteed focus letter.
- **Per-layout stats** — heatmap with per-key confidence and urgency; WPM/accuracy
  trends; press a key on the heatmap for that key's history.
- **Daily learn budget** — optional cap on adaptive minutes per calendar day.
- **Custom layouts** — drop `*.toml` files into your config layouts directory; no
  restart needed.
- **Git backup sync** — optional CLI to push/pull settings and sessions to a private
  remote (union-merge sessions, last-write-wins settings).
- **Offline by default** — JSONL session logs and a local stats cache under
  platformdirs paths; sync is opt-in.

## Install

Requires **Python 3.12+** and a terminal with **raw-mode keyboard input**
([Terminal setup](#terminal-setup)).

```bash
pipx install keystrike    # or: uv tool install keystrike
keystrike                 # launch TUI (default)
keystrike --version
```

Or from source:

```bash
git clone https://github.com/egno/keystrike
cd keystrike
uv sync --no-dev
uv run keystrike
```

## Usage

### Home

| Key | Action |
| --- | --- |
| `Enter` | Start adaptive practice |
| `s` | Stats |
| `o` | Settings |
| `l` | Cycle layout |
| `Ctrl+Q` | Quit |

On other screens, `Esc` / `q` goes back. Settings saves with `Ctrl+S`.

### Practice

Adaptive mode disables backspace — mistakes stay in the record so confidence scores
stay honest. The HUD shows live accuracy, remaining daily learn time, and the current
focus key. When a session ends, the next lesson starts automatically unless you go
back or hit your daily limit.

### Stats

Recent sessions are listed below the heatmap. **Press any key on the heatmap** to
drill into that key's confidence trend; `Esc` / `q` returns to the overview.

### Settings

| Setting | Default | Notes |
| --- | --- | --- |
| Layout | `qwerty` | Any bundled or custom layout |
| Target speed | 46 WPM | Or CPM — your unlock threshold |
| Letters unlocked up front | 16 | Force-unlocked before confidence gating |
| Daily learn limit | 10 min | `0` = unlimited |

## Backup sync

Opt-in git sync for backing up or moving data between machines. Requires `git` on
`PATH` and a **private** remote (sessions contain your typing history).

```bash
keystrike sync init git@github.com:you/keystrike-backup.git   # one-time
keystrike sync push      # local → remote
keystrike sync pull      # remote → local (rebuilds stats cache)
keystrike sync status    # diff summary
```

Sync merges sessions by `session_id` (union), resolves settings by `updated_at`
(last-write-wins), and copies layout files both ways. The stats cache is excluded —
pull triggers a rebuild.

## Data locations

| Path | Contents |
| --- | --- |
| `~/.config/keystrike/settings.toml` | User settings |
| `~/.config/keystrike/layouts/` | Custom layout TOML files |
| `~/.config/keystrike/sync.toml` | Sync remote config (after `sync init`) |
| `~/.local/share/keystrike/sessions/` | Session JSONL logs (Linux) |
| `~/Library/Application Support/keystrike/` | Same on macOS |

Windows uses `%APPDATA%` / `%LOCALAPPDATA%` equivalents via [platformdirs](https://github.com/tox-dev/platformdirs).

## Terminal setup

Keystrike captures every keystroke in raw mode via [Textual](https://textual.textualize.io/).

Works out of the box in **Terminal.app**, **iTerm2**, and most Linux terminals.

### Windows

Use **[Windows Terminal](https://apps.microsoft.com/store/detail/windows-terminal/9N0DX20HK701)** —
the legacy conhost host has unreliable raw-mode support. Run `keystrike` inside WT,
not cmd.exe. Raw mode is not verified on every Windows build; please
[open an issue](https://github.com/egno/keystrike/issues) if something breaks.

## Development

```bash
uv sync                  # runtime + dev (pytest, pyright)
uv run pytest -q
uv run pyright
uv sync --all-groups      # + ruff + snapshot tests (desktop only)
uv run ruff check
```

Dependency groups: `dev` (default, pure Python — safe on Termux), `lint` (Ruff),
`snapshot` (`pytest-textual-snapshot`). Keep native-wheel tools out of `dev`; see
`pyproject.toml` for why.

Regenerate the demo GIF after UI snapshot changes:

```bash
uv sync --group snapshot
uv run pytest tests/presentation/test_snapshots.py --snapshot-update
uv pip install pillow cairosvg   # one-off; system cairo on macOS/Linux
uv run python scripts/generate_demo_gif.py
```

## License

MIT
