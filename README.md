# keystrike

Offline, cross-platform terminal typing tutor. Adaptive drills inspired by
[keybr](https://www.keybr.com/), code-typing mode, free practice on your own
text files, per-layout stats — all locally on disk, no network.

## Status

Pre-alpha (M1). The MVP runs a fixed-text typing session and reports WPM and
accuracy at the end.

## Install (dev)

```bash
uv sync
uv run keystrike run
```

On Android (Termux, etc.), runtime deps are pure Python — no native wheels
required. Avoid adding dev tools that pull `markupsafe` (e.g.
`pytest-textual-snapshot`) until snapshot tests are implemented; MarkupSafe has
no PyPI wheels for the Android platform tag on Python 3.12.

## Development

```bash
uv run pytest -q         # tests
uv run ruff check        # lint
uv run ruff format       # format
uv run pyright           # type check
```

## License

MIT
