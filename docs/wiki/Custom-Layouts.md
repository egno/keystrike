# Custom layouts

Keystrike ships four bundled keyboard layouts (QWERTY, Dvorak, Colemak, Colemak
Mod-DH). Add your own by dropping a TOML file into the layouts directory — split
ortho boards, Workman, locale-specific variants, or anything else you want to
practice on its own terms.

Each layout keeps **separate stats, unlock progress, and session history**. Switch
layouts from the home screen or Settings; practice on one layout does not affect
another.

## Why use a custom layout

- **Non-bundled physical layouts** — Colemak Mod-DH matrix, Workman, Norman, etc.
- **Ortholinear / split boards** — set `ortholinear = true` so the Stats heatmap
  renders without ANSI row stagger.
- **Reduced or alternate key sets** — e.g. a minimal layout while learning a new
  alphabet.
- **Side-by-side comparison** — cycle between QWERTY and your custom layout with
  independent confidence scores.

Bundled layouts are compiled into the app. Custom layouts are plain TOML on disk and
can be synced with [Git sync](Git-sync).

## Quick start

1. Create the layouts directory if it does not exist (Keystrike creates it on first
   run, but you can make it yourself):

   ```bash
   mkdir -p ~/.config/keystrike/layouts    # Linux — see table below for your OS
   ```

2. Add a file named `<layout_id>.toml` (e.g. `workman.toml`).

3. While Keystrike is running, press **`l`** on the home screen to cycle layouts,
   or open **Settings** (`o`) and pick the new name from the Layout dropdown.

No app restart is required. New files are picked up the next time you cycle
layouts or open/resume the Settings screen.

## File location

Custom layouts live under `{config_dir}/layouts/` as `*.toml` files. Paths come
from [platformdirs](https://github.com/tox-dev/platformdirs) with
`appauthor=False` (same as other Keystrike config):

| OS | Layouts directory |
| --- | --- |
| Linux | `~/.config/keystrike/layouts/` |
| macOS | `~/Library/Application Support/keystrike/layouts/` |
| Windows | `%LOCALAPPDATA%\keystrike\layouts\` |

On macOS and Windows, config and data share one app directory; on Linux, session
logs and stats cache live under `~/.local/share/keystrike/` instead.

The **filename stem** (without `.toml`) is the layout ID used in Settings,
`settings.toml`, and stats — e.g. `workman.toml` → layout id `workman`.

## TOML schema

Top-level fields:

| Field | Required | Type | Notes |
| --- | --- | --- | --- |
| `name` | yes | string | Display/internal name stored in the `Layout` model. Should match the filename stem. |
| `learn_order` | yes | string | Unlock order: every character must appear in `[[keys]]`. |
| `ortholinear` | no | boolean | Default `false`. When `true`, Stats renders the heatmap without row stagger (for matrix/ortho boards). |
| `keys` | yes | array of tables | At least one `[[keys]]` entry. |

Each `[[keys]]` table:

| Field | Required | Type | Notes |
| --- | --- | --- | --- |
| `char` | yes | string | Exactly one character (the key you type). |
| `row` | yes | integer | Row index for heatmap placement (0 = top). |
| `col` | yes | integer | Column index within the row. |
| `finger` | yes | string | One of `PINKY`, `RING`, `MIDDLE`, `INDEX`, `THUMB`. |
| `hand` | yes | string | `L` or `R`. |
| `shifted` | no | boolean | Default `false`. Stored on the key model; bundled layouts leave this unset. |

`learn_order` controls which keys unlock first after the initial
[alphabet_size](Confidence-Tuning) force-unlock. Bundled layouts use English
letter frequency (`etaoinshrdlcumwfgypbvkjxqz`, then punctuation, then space).
Custom layouts can follow the same idea or any order that matches your curriculum.

### Minimal example

Two keys — enough to validate the file loads:

```toml
name = "mini"
learn_order = "ab"

[[keys]]
char = "a"
row = 1
col = 0
finger = "PINKY"
hand = "L"

[[keys]]
char = "b"
row = 1
col = 1
finger = "RING"
hand = "L"
```

Save as `{config_dir}/layouts/mini.toml`, then cycle layouts or open Settings.

### Fuller annotated example

Partial home-row slice showing typical fields (not a complete typing layout):

```toml
# Layout ID in settings: "sample" (from filename sample.toml)
name = "sample"
ortholinear = false

# Unlock order — only characters defined in [[keys]] below
learn_order = "asdf jkl;"

[[keys]]
char = "a"
row = 1          # home row
col = 0          # left pinky column
finger = "PINKY"
hand = "L"

[[keys]]
char = "s"
row = 1
col = 1
finger = "RING"
hand = "L"

[[keys]]
char = "d"
row = 1
col = 2
finger = "MIDDLE"
hand = "L"

[[keys]]
char = "f"
row = 1
col = 3
finger = "INDEX"
hand = "L"

[[keys]]
char = "j"
row = 1
col = 6
finger = "INDEX"
hand = "R"

[[keys]]
char = "k"
row = 1
col = 7
finger = "INDEX"
hand = "R"

[[keys]]
char = "l"
row = 1
col = 8
finger = "RING"
hand = "R"

[[keys]]
char = ";"
row = 1
col = 9
finger = "PINKY"
hand = "R"
shifted = true   # optional; default false
```

For a full ANSI-style Latin layout, mirror the row/column grid and finger
assignments from the bundled builders (physical column → finger/hand, same as
QWERTY/Dvorak/Colemak).

## Using a layout in the app

| Where | How |
| --- | --- |
| **Home** | Press **`l`** to cycle to the next available layout (alphabetical order, wraps). The hero line shows `Layout: … (l switch)`. |
| **Settings** | Press **`o`** from home, choose **Layout** from the dropdown, **`Ctrl+S`** to save. |
| **Stats** | Press **`s`** — stats, heatmap, and trends are for the **currently selected** layout only. |
| **Practice** | **`Enter`** on home starts adaptive drills for the current layout. |

**Cycle layout** is a no-op when fewer than two layouts exist (bundled-only install
with no custom files).

Layout choice is persisted in `{config_dir}/settings.toml` as `layout = "…"`.

### When new layouts appear

Keystrike rescans `{config_dir}/layouts/*.toml` whenever:

- You press **`l`** on the home screen (cycle uses a fresh `list_available()`).
- You open **Settings** (`on_mount` refreshes the Layout dropdown).
- You return to **Settings** from another screen (`on_screen_resume` refreshes again).

You do **not** need to restart the app. Editing or removing a file while the app
is open is reflected on the next cycle or Settings visit; the dropdown keeps your
previous selection if that layout still exists.

## Bundled layout reference

Study these for row/column grids, learn order, and ortholinear usage:

| Layout | Source file |
| --- | --- |
| QWERTY | [`src/keystrike/infrastructure/bundled_layouts/qwerty.py`](https://github.com/egno/keystrike/blob/main/src/keystrike/infrastructure/bundled_layouts/qwerty.py) |
| Dvorak | [`dvorak.py`](https://github.com/egno/keystrike/blob/main/src/keystrike/infrastructure/bundled_layouts/dvorak.py) |
| Colemak | [`colemak.py`](https://github.com/egno/keystrike/blob/main/src/keystrike/infrastructure/bundled_layouts/colemak.py) |
| Colemak Mod-DH (ortholinear) | [`colemak_dh.py`](https://github.com/egno/keystrike/blob/main/src/keystrike/infrastructure/bundled_layouts/colemak_dh.py) |

Shared grid logic (finger/hand by physical column, default learn order) lives in
[`_grid.py`](https://github.com/egno/keystrike/blob/main/src/keystrike/infrastructure/bundled_layouts/_grid.py).

The TOML parser and its docstring example are in
[`layout_toml.py`](https://github.com/egno/keystrike/blob/main/src/keystrike/infrastructure/layout_toml.py).

Test fixtures with valid minimal files:
[`tests/infrastructure/fixtures/layouts/good.toml`](https://github.com/egno/keystrike/blob/main/tests/infrastructure/fixtures/layouts/good.toml),
[`good_ortholinear.toml`](https://github.com/egno/keystrike/blob/main/tests/infrastructure/fixtures/layouts/good_ortholinear.toml).

## Name conflicts with bundled layouts

Bundled layout names: `qwerty`, `dvorak`, `colemak`, `colemak_dh`.

If you add `{config_dir}/layouts/qwerty.toml`, **the bundled QWERTY layout still
wins** — `CompositeLayoutRepository` checks bundled layouts before loading TOML.
Use a distinct filename (e.g. `my-qwerty.toml`) for a custom variant.

Discovery lists the filename stem even when bundled takes priority on `get()`, so
avoid reusing bundled names for custom files.

## Git sync

Custom layout TOML files sync with [Git sync](Git-sync):

- **Pull** — remote layouts missing locally are copied in; existing local files
  with the same name are **not** overwritten.
- **Push** — all local `*.toml` files are copied to the clone.

Bundled layouts are not synced (they ship with the app).

## Troubleshooting

### Layout missing from dropdown

- Confirm the file is `{config_dir}/layouts/<name>.toml` (not nested, not `.txt`).
- Press **`l`** or re-open **Settings** to rescan — no restart needed.
- Check the filename stem; that string is what appears in the list.

### App errors when selecting or practicing on a custom layout

Invalid TOML is **not** validated at discovery time — only when the layout is
loaded (`get()`). Fix the file and try again. Errors look like
`<path>: keys[0].finger must be one of ['PINKY', 'RING', …]`.

Common causes:

| Symptom / error | Fix |
| --- | --- |
| `TOMLDecodeError` / parse error | Fix TOML syntax (commas, quoting, `[[keys]]` headers). |
| `missing required string field 'name'` | Add non-empty `name = "…"`. |
| `missing required non-empty array of tables 'keys'` | Add at least one `[[keys]]` block. |
| `keys[i].char must be a single character` | Use exactly one character per `char`. |
| `requires integer 'row' and 'col'` | Both must be integers. |
| `finger must be one of …` | Use `PINKY`, `RING`, `MIDDLE`, `INDEX`, or `THUMB`. |
| `hand must be one of …` | Use `L` or `R`. |
| `learn_order references undefined keys` | Every character in `learn_order` needs a matching `[[keys]]` entry. |
| `'ortholinear' must be a boolean` | Use `true` / `false`, not a string. |

### `unknown layout` after sync or manual edit

If `settings.toml` references a layout that no longer exists, open Settings (if
possible), pick a valid layout, and save — or edit `layout = "qwerty"` directly.

### Filename vs `name` field mismatch

Settings and stats use the **filename stem** as the layout id. The `name` field
inside the TOML is stored on the `Layout` object but should match the filename to
avoid confusion.

## See also

- [Home](Home)
- [Git sync](Git-sync) — backing up custom layouts and sessions
- [Confidence tuning](Confidence-Tuning) — per-layout unlock thresholds in `settings.toml`
- [Keystrike README — Data locations](https://github.com/egno/keystrike#data-locations)
