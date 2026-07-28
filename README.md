# keystrike

Offline, cross-platform terminal typing tutor. Adaptive drills inspired by
[keybr](https://www.keybr.com/), code-typing mode, free practice on your own
text files, per-layout stats — all locally on disk, no network.

## Status

Pre-alpha (M1). The MVP runs a fixed-text typing session and reports WPM and
accuracy at the end.

## Install

Runtime deps live in `[project] dependencies`. Dev tools are uv
`dependency-groups` — `dev` (pure Python, synced by default) and `lint`
(Ruff; desktop only).

### Runtime only

```bash
uv sync --no-dev
uv run keystrike run
```

### Dev (tests + typecheck)

Includes the `dev` group (pytest, pyright, …). Safe on Android/Termux — all
pure-Python wheels, no Ruff/maturin:

```bash
uv sync
uv run keystrike run
uv run pytest -q
```

### Full dev (desktop)

Also installs the `lint` group (Ruff). Skip on Android — Ruff has no Android
wheels and its sdist build pulls `maturin`, which also fails there:

```bash
uv sync --all-groups
uv run ruff check
```

Keep native-wheel dev tools out of `dev` (e.g. `pytest-textual-snapshot` →
`markupsafe`; Ruff → `maturin`).

## Development

```bash
uv run pytest -q         # tests
uv run pyright           # type check
uv run ruff check        # lint (requires `--all-groups` or `--group lint`)
uv run ruff format       # format
```

## License

MIT
