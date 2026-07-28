# Word lists

Optional real-word drills for adaptive practice. By default Keystrike generates
**Markov** word-like chunks from bundled letter transitions. Import a remote word
list to practice with **dictionary words** instead — filtered to your currently
unlocked letters and biased toward weak keys, same as Markov mode.

## Why use a word list

- **Familiar words** — easier to read and type than pseudo-words; closer to real typing.
- **Same adaptive engine** — focus key, weak-key weighting, and bigram practice still apply.
- **Optional** — no import means Markov mode; clearing the list returns to Markov.

Keystrike ships no bundled dictionary. Import downloads a list once and caches it locally.

## Default list

The Settings URL field is pre-filled with the default source (not active until you import):

```text
https://raw.githubusercontent.com/first20hours/google-10000-english/master/google-10000-english-usa-no-swears.txt
```

Leave the field as-is and press **Import** to use this list. It is a common English frequency list (lowercase, one word per line).

## Import and clear

Open **Settings** from the home screen (`o`), then:

| Key | Action |
| --- | --- |
| **Ctrl+I** | Download the URL, cache the list, save the URL to settings |
| **Ctrl+X** | Clear the saved URL and return to Markov mode |

Steps to enable word-list drills:

1. Open Settings.
2. Optionally edit the URL (see [Custom URL](#custom-url)).
3. Press **Ctrl+I** (Import).
4. Confirm the status line shows `N words cached.`

**Ctrl+S** saves layout, speed, and other settings — it does **not** import or persist the word-list URL. Only **Import** writes `wordlist_url` to `settings.toml`.

After **Clear**, the URL field resets to the default pre-fill and status shows `Markov words.` The cached file remains on disk but is ignored until you import again (same or different URL).

## How lessons use the list

When a URL is saved **and** the cache file exists, Keystrike:

1. Loads the cached list from disk.
2. Keeps words that are 3–10 letters and use **only** letters in your current unlocked set.
3. Samples lesson words from that pool, overweighting words that contain weak keys.

If any step yields no usable words, the lesson falls back to **Markov** generation for that session (or per word when sampling fails). Status `Not cached.` means a URL is saved but the cache file is missing — lessons use Markov until you import again.

### Early unlock and sparse pools

With few letters unlocked (or an unusual unlocked set), most dictionary words are filtered out — English words often need letters you have not unlocked yet. A small matching pool is fine; an **empty** pool triggers Markov fallback. Raising **Letters unlocked up front** widens the alphabet but does not guarantee more dictionary matches.

## Persistence

| Stored | Location |
| --- | --- |
| Saved URL | `{config_dir}/settings.toml` (`wordlist_url`) |
| Downloaded list | `{data_dir}/cache/wordlist-{hash}.txt` |

Cache filenames use the first 12 hex digits of SHA-256 of the URL. Lists persist across app restarts; re-import only when you change URL or the cache was deleted.

Typical paths (see [platformdirs](https://github.com/tox-dev/platformdirs)):

| OS | Config (`settings.toml`) | Data (`cache/`) |
| --- | --- | --- |
| Linux | `~/.config/keystrike/` | `~/.local/share/keystrike/cache/` |
| macOS | `~/Library/Application Support/keystrike/` | same tree |
| Windows | `%APPDATA%\keystrike\` | `%LOCALAPPDATA%\keystrike\cache\` |

## Git sync caveat

[Git sync](Git-sync) copies `settings.toml`, so **`wordlist_url` syncs** between machines. **`cache/` is not synced** — it is rebuilt locally (same as stats aggregates).

After `keystrike sync pull` on a new device you may have a saved URL but no cached file. Settings shows `Not cached.` Run **Ctrl+I** once on that machine to download the list. No need to re-enter the URL if it synced correctly.

## Custom URL

Any **http** or **https** URL pointing to plain text works:

- One word per line.
- Lowercase letters only (same filter as the bundled Markov corpus builder).
- Lines with digits, punctuation, or uppercase are skipped.
- Download limit: 5 MB.

Example minimal list:

```text
the
and
for
are
but
```

Paste your URL into the Settings field, then **Ctrl+I**. Invalid URLs or empty downloads show an error on the settings screen.

## See also

- [Home](Home)
- [Git sync](Git-sync) — what syncs with `keystrike sync`
- [Keystrike README — Settings](https://github.com/egno/keystrike#settings)
