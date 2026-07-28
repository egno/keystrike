#!/usr/bin/env python3
"""Dev-only: build data/<lang>_markov.json.gz from a local word list.

Order-2 letter transitions are counted over every lowercase alphabetic word in
the corpus: for each character, its context is the (up to) 2 preceding chars,
including the empty context for a word's first letter. The context space is
bounded (27 + 27^2 possible contexts for a 26-letter alphabet) regardless of
corpus size, so the output stays small no matter how big the word list is.

Usage:
    uv run python scripts/build_markov.py [wordlist_path] [--lang en]

Defaults to macOS's /usr/share/dict/words. Re-run whenever the corpus or
`ORDER` changes; commit the resulting .json.gz, since it's bundled with the
package (see pyproject.toml wheel `packages` for this data directory).
"""

from __future__ import annotations

import argparse
import gzip
import json
from collections import defaultdict
from pathlib import Path

ORDER = 2
DEFAULT_WORDLIST = Path("/usr/share/dict/words")
DATA_DIR = Path(__file__).parent.parent / "src/keystrike/infrastructure/languages/data"


def build_transitions(words: list[str]) -> dict[str, dict[str, int]]:
    counts: defaultdict[str, defaultdict[str, int]] = defaultdict(lambda: defaultdict(int))
    for word in words:
        for i, ch in enumerate(word):
            context = word[max(0, i - ORDER) : i]
            counts[context][ch] += 1
    return {ctx: dict(next_counts) for ctx, next_counts in counts.items()}


def load_words(wordlist_path: Path) -> list[str]:
    raw_words = wordlist_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    # Keep common lowercase words only — this drops proper nouns (capitalized
    # in most system word lists) and anything with punctuation/digits.
    return [w for w in raw_words if w.isalpha() and w.islower()]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wordlist", nargs="?", type=Path, default=DEFAULT_WORDLIST)
    parser.add_argument("--lang", default="en")
    args = parser.parse_args()

    words = load_words(args.wordlist)
    if not words:
        raise SystemExit(f"no usable words found in {args.wordlist}")

    transitions = build_transitions(words)
    payload = {"order": ORDER, "transitions": transitions}

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    output = DATA_DIR / f"{args.lang}_markov.json.gz"
    output.write_bytes(gzip.compress(json.dumps(payload).encode("utf-8")))

    print(
        f"wrote {output} ({output.stat().st_size} bytes) from {len(words)} words, "
        f"{len(transitions)} contexts"
    )


if __name__ == "__main__":
    main()
