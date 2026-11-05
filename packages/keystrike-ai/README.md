# keystrike-ai

LLM advisor plugin for [keystrike](../../README.md). It asks an Ollama or
OpenAI-compatible server for advice on the next lesson.

**It sends data off the device**: per-key statistics, mistyped keys and
errors per finger go to the server you configure. keystrike asks you to
confirm this once before it starts. Installing a plugin means trusting it.

What it sends: per-key error rates and times (median speed of clean presses),
common mistypes and errors per finger. It needs keystrike's raw keystroke files
for the speed numbers; without them it judges accuracy only.

It is not on PyPI yet. Install it from a clone of the repository, next to
keystrike (`uv sync` does this for you):

    pip install ./packages/keystrike-ai

Then pick "LLM" in keystrike's Settings. The plugin needs plugin API
version 2 (keystrike 2.3 or later).

The API key for OpenAI-compatible servers is read from
`KEYSTRIKE_AI_API_KEY`; it is never stored in a file.
