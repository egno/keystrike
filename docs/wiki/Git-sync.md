# Git sync

Back up Keystrike settings and typing sessions to a **private git repository** you control. Sync is **opt-in**, **CLI-only**, and runs only when you invoke it — there is no Keystrike cloud, no background daemon, and no automatic upload when a session ends.

## What it is (and is not)

| | |
| --- | --- |
| **Is** | A git-backed backup and manual multi-device sync via `keystrike sync` |
| **Is not** | Cloud sync, real-time sync, or a Keystrike-hosted service |

Your data stays in your git remote (GitHub, GitLab, self-hosted, etc.). Keystrike never talks to that remote except when you run a sync command.

## Prerequisites

- **Keystrike** with git sync support (see [CHANGELOG](https://github.com/egno/keystrike/blob/main/docs/CHANGELOG.md)).
- **`git` on your PATH** — sync shells out to the git CLI for clone, pull, and push.
- **Git credentials** configured for your remote:
  - **SSH** — e.g. `git@github.com:you/keystrike-backup.git` (SSH key loaded in your agent).
  - **HTTPS** — e.g. `https://github.com/you/keystrike-backup.git` (credential helper or personal access token).
- **A private remote repository** (strongly recommended). Session logs contain your typing history.

Optional but recommended: set `git config user.name` and `git config user.email` on each machine so sync commits have sensible authorship.

## One-time setup

### 1. Create a private backup repo

On GitHub (or elsewhere), create an **empty private** repository, e.g. `keystrike-backup`. Do not add a README if you want a truly empty repo — an empty repo works fine; Keystrike initializes the layout on first push.

### 2. Initialize sync on each machine

```bash
keystrike sync init git@github.com:you/keystrike-backup.git
# or
keystrike sync init https://github.com/you/keystrike-backup.git
```

This command:

1. Writes your remote URL to `sync.toml` (see [File locations](#file-locations)).
2. Clones the remote (or runs `git init` locally if the remote is empty).
3. Merges local and remote data using Keystrike's merge rules (below).
4. Pushes the merged snapshot to the remote.

Run `init` once per machine. On a second device, use the **same remote URL** so both machines share one backup repo.

## Daily workflow

| Command | When to use |
| --- | --- |
| `keystrike sync push` | After practice on this machine — upload new sessions and settings. |
| `keystrike sync pull` | Before practice on this machine — download sessions from other devices and rebuild local stats. |
| `keystrike sync status` | Check remote URL, session counts, and whether the clone has uncommitted changes. |

Typical multi-device habit:

1. **Before** opening Keystrike: `keystrike sync pull`
2. Practice as usual (the TUI does not sync by itself).
3. **After** a session (or end of day): `keystrike sync push`

Example output:

```text
$ keystrike sync status
remote: git@github.com:you/keystrike-backup.git
sessions: local=42 clone=40 (only local=2, only remote=0)
git: (clean)

$ keystrike sync push
push complete

$ keystrike sync pull
pull complete: 3 session(s) imported
```

## What gets synced

| Synced | Not synced |
| --- | --- |
| `settings.toml` | `cache/` (derived stats — rebuilt locally) |
| `layouts/*.toml` (custom layouts) | Bundled layouts shipped with Keystrike |
| `sessions/index.jsonl` | Logs outside the sessions tree |
| `sessions/**/*.jsonl` (session keystroke logs) | |

After a successful **pull**, Keystrike replays all sessions in the merged index and rebuilds the stats cache for every layout it finds. You do not need to sync cache files.

## Merge behavior

Keystrike applies its own merge logic before every push and pull. Git is used only for transport; JSONL session files are **not** left to git's native merge.

### Sessions — union by `session_id`

- Sessions are identified by `session_id` in `sessions/index.jsonl`.
- **Missing sessions are imported** — if the remote has a session ID your machine lacks, the session file and index entry are copied in.
- **Existing IDs are never overwritten** — if both sides have the same `session_id`, the local copy wins and the remote copy is left unchanged on import.

This means you can practice on two machines offline and merge later without losing sessions, as long as each session has a unique ID (Keystrike generates UUIDs).

### Settings — last-write-wins

- Keystrike compares `updated_at` in `settings.toml` (ISO timestamp, written on every save).
- The newer file is copied to **both** local and clone before push/pull.
- If `updated_at` is missing on either side, file modification time is used instead.

Whichever machine saved settings most recently wins globally after the next sync.

### Layouts — additive on pull, full copy on push

- **Pull:** remote layout TOML files that are **missing locally** are copied in. Existing local files with the same name are not overwritten.
- **Push:** all local custom layout files are copied into the clone (overwriting same-named files in the clone).

If two machines edit the **same** layout filename differently, the last **push** wins on the remote; the other machine won't see those edits until it pulls and may keep its local copy until you resolve the conflict manually.

## Multi-device tips

1. **Pull before push** on each machine to reduce divergent git history.
2. **Use a private remote** — session JSONL is sensitive.
3. **Same remote on every device** — one backup repo for all machines.
4. **Check status** when unsure: `only local` / `only remote` counts show what still needs a push or pull.

## Known limitations

- **Fast-forward pull only** — `keystrike sync pull` runs `git pull --ff-only`. If you pushed from two machines without pulling in between, the remote history can diverge and pull will fail. Fix on the clone: `cd ~/.config/keystrike/sync/repo` (paths vary by OS), resolve with `git pull --rebase` or merge manually, then retry `keystrike sync pull`.
- **No automatic sync** — nothing runs when a session ends; you must run push/pull yourself.
- **Layout name conflicts** — same filename, different content: last push to remote wins; pull does not overwrite existing local layouts.
- **Settings conflicts** — no three-way merge; newest `updated_at` (or mtime) wins outright.
- **Session duplicates** — same `session_id` on both sides keeps the local version on import; design assumes IDs are unique.

## File locations

Paths use [platformdirs](https://github.com/tox-dev/platformdirs) (same roots as other Keystrike data):

| File / directory | Purpose |
| --- | --- |
| `{config_dir}/sync.toml` | Remote URL written by `sync init` |
| `{config_dir}/sync/repo/` | Local git clone used for push/pull |
| `{config_dir}/settings.toml` | Synced settings |
| `{config_dir}/layouts/` | Synced custom layouts |
| `{data_dir}/sessions/` | Synced session logs |

Typical `{config_dir}` / `{data_dir}`:

| OS | Config | Data (sessions) |
| --- | --- | --- |
| Linux | `~/.config/keystrike/` | `~/.local/share/keystrike/` |
| macOS | `~/Library/Application Support/keystrike/` | same tree under Application Support |
| Windows | `%LOCALAPPDATA%\keystrike\` | same tree under Local AppData |

`sync.toml` contains only the remote URL, for example:

```toml
remote_url = "git@github.com:you/keystrike-backup.git"
```

## Troubleshooting

### `sync not configured`

Run one-time setup:

```bash
keystrike sync init <repo-url>
```

### Authentication failed (SSH)

- Test: `ssh -T git@github.com`
- Ensure your SSH key is loaded (`ssh-add -l`) and added to your GitHub account.

### Authentication failed (HTTPS)

- Use a credential helper or embed a PAT in the URL (less ideal): `https://<token>@github.com/you/keystrike-backup.git`
- Prefer `gh auth login` or Git Credential Manager.

### Empty or new remote

`sync init` handles empty remotes: if `git clone` fails, Keystrike runs `git init`, adds `origin`, merges local data, and pushes.

### `git pull --ff-only` failed / diverged history

Two machines pushed without pulling. On the affected machine:

```bash
cd ~/.config/keystrike/sync/repo   # adjust for your OS
git fetch origin
git log --oneline --graph --all -5   # inspect
git pull --rebase origin main        # or master — match your default branch
keystrike sync pull
```

When in doubt, **back up** `{config_dir}` and `{data_dir}` before fixing git history manually.

### `git commit` failed — user.name / user.email

Configure git on that machine:

```bash
git config --global user.name "Your Name"
git config --global user.email "you@example.com"
```

Then retry `keystrike sync push`.

### Pull succeeded but stats look stale

Pull rebuilds aggregates from the session index. If something still looks wrong, check `keystrike sync status` session counts and confirm session files exist under `{data_dir}/sessions/`.

## See also

- [Keystrike README — Backup sync](https://github.com/egno/keystrike#backup-sync)
- [Confidence tuning](Confidence-Tuning) — advanced fields in `settings.toml` (not the Settings screen)
- [Home](Home)
