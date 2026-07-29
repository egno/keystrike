# Typing pedagogy research

Research-backed principles for effective typing skill acquisition, and how they relate to keystrike's lesson/curriculum design (`src/keystrike/domain/learn_order.py`, `src/keystrike/domain/confidence.py`, `src/keystrike/application/build_lesson.py`, `src/keystrike/presentation/widgets/kb_heatmap.py`).

## Core principles

1. **Touch typing over hunt-and-peck** — fixed finger-to-key mapping anchored on home row builds procedural muscle memory and outperforms visually-guided typing long-term.
2. **Accuracy first, speed follows** — pushing speed before accuracy is high trains error-correction habits instead of automaticity; speed drills work best only after error rate is already low.
3. **Spaced/distributed practice beats cramming** — short frequent sessions (~15-20 min/day) outperform long infrequent ones, per the general spacing effect in motor learning.
4. **Deliberate practice targeting weak points** — practice concentrated on a learner's specific error-prone keys/bigrams/finger transitions, with immediate feedback, beats generic full-keyboard drills.
5. **Progressive/incremental key introduction** — introduce keys in small groups (starting from home row, expanding outward), advancing only once a group is mastered.
6. **Chunking at word/bigram level, not just letters** — real typing speed is bottlenecked by common letter sequences and words, so practice reinforcing frequent bigrams/trigrams/whole words transfers better than isolated keystroke drills.
7. **Immediate, specific feedback** — knowing which keystroke was wrong and correcting it right away accelerates learning more than aggregate end-of-session stats.
8. **Plateaus need varied practice** — after initial rapid gains, progress slows sharply; overcoming plateaus generally requires varying practice (new text sources, mixed difficulty) rather than repeating the same drills.

Where this maps onto the code: `learn_order.py` (progressive key introduction) and `kb_heatmap.py` (visualizing weak keys) already align with points 4-6. When reviewing or extending `build_lesson.py`, `learn_order.py`, or practice-screen logic, check design choices against these principles — e.g. does key/lesson progression stay incremental (5), does weak-key data drive targeted practice (4), does the app avoid demanding speed before accuracy is stable (2).

## Sources backing key-increment design

- **Keybr's real-world algorithm**: unlocks one new letter at a time only once the learner clears speed *and* accuracy thresholds on the current set, plus adaptive per-letter frequency weighting based on personal error/latency history. Closest real analog to `compute_unlocked` in `confidence.py:39-57`.
  - [Keybr Review 2026: Adaptive Typing Practice Analyzed](https://cosmickeys.app/en/blog/keybr-review)
  - [How to Practice and Improve Touch Typing at Keybr.com](https://lifetips.alibaba.com/tech-efficiency/practice-and-improve-touch-typing-at-keybr-com)
- **SlimStampen** (ACT-R-based adaptive scheduling, validated for typing transfer): uses *reaction time* as the primary mastery signal (better proxy for memory/motor-trace strength than accuracy alone), and re-tests items right before they'd be forgotten (spacing effect) rather than on a fixed timer. Suggests `confidence_of` should weight speed at least as heavily as accuracy.
  - [Benefits of Adaptive Learning Transfer From Typing-Based Learning to Speech-Based Learning (PMC)](https://pmc.ncbi.nlm.nih.gov/articles/PMC8689065/)
  - [An Individual's Rate of Forgetting Is Stable Over Time but Differs Across Materials](https://www.researchgate.net/publication/289970940_An_Individual's_Rate_of_Forgetting_Is_Stable_Over_Time_but_Differs_Across_Materials)
- **Crump & Logan** (Vanderbilt): typing control is hierarchical at the *word* level, not per-keystroke — scrambling letter order within words slows skilled typists; transfer experiments showed fastest performance on trained words, then new words made of trained letters, slowest on words with untrained letters. Direct evidence that newly-unlocked keys should appear embedded in real words/bigrams (as `generator.py`/`markov.py` already do), not drilled in isolation.
  - [Hierarchical Control and Skilled Typing: Evidence for Word-Level](http://www.psy.vanderbilt.edu/faculty/logan/Crump%20Logan%20JEPLMC2010.pdf)
  - [Episodic Contributions to Sequential Control: Learning From a Typist's Touch](http://www.psy.vanderbilt.edu/faculty/logan/CrumpLoganHPP2010.pdf)
  - [Typing expertise in a large student population (Springer)](https://link.springer.com/article/10.1186/s41235-022-00424-3)
- **Controlled study in higher-ed students** (with/without learning disabilities): structured touch-typing programs significantly improved speed while accuracy stayed above 95%, validating structured training over ad hoc practice generally.
  - [The effect of a touch-typing program on keyboarding skills of higher education students with and without learning disabilities (PubMed)](https://pubmed.ncbi.nlm.nih.gov/26447834/)

## Row-order vs. finger-order for key unlock sequencing

Row-based ordering (distance from home position) is the literature- and convention-backed axis for *which single key unlocks next* — not finger identity:

- Interkey-timing research found that for within-hand keystrokes, timing is a function of **distance between keys**: the farther a key sits from the resting/home position, the longer the interval — a reach-distance effect, which is exactly what row-tiering (home < top < everything else) captures. This is what `learn_order.py`'s `_row_weight`/`keyboard_order()` already implements.
- Standard typing curricula (typing.com, how-to-type.com, etc.) independently converge on row-based lesson structure (Lesson 1 = home row all fingers, Lesson 2 = top row, ...) rather than finger-grouped structure (e.g. "all of the index finger's keys across every row first").
- Finger identity's real, well-supported effect is on **sequence/transition speed, not single-key unlock difficulty**: hand-alternating keystrokes are faster than same-hand repetitions, and letter pairs split across different fingers/hands predict typing speed better than repeated-letter pairs. This is an argument for biasing *generated practice text* (bigram selection in `generator.py`/`markov.py`) toward hand-alternating pairs — not for reordering the unlock queue by finger.
- Caveat: no source found is a controlled trial specifically comparing row-first vs. finger-first *curriculum* sequencing head-to-head — the row conclusion is strong converging evidence (biomechanics + universal pedagogical convention), not a single definitive RCT.

Sources:
- [Determinants of Interkey Times in Typing (Ostry)](https://www.psych.mcgill.ca/labs/mcl/pdf/typing1983.pdf)
- [Observations on Typing from 136 Million Keystrokes (CHI 2018)](https://userinterfaces.aalto.fi/136Mkeystrokes/resources/chi-18-analysis.pdf)
- [How We Type: Movement Strategies and Performance in Everyday Typing](https://userinterfaces.aalto.fi/how-we-type/resources/HowWeType_CHI16.pdf)
- [Interkey Timing in Piano Performance and Typing](https://www.researchgate.net/publication/13888297_Interkey_timing_in_piano_performance_and_typing)
- [Chapter 3: The mechanics of efficient typing](https://typetest.io/ebook/chapter/chapter-3-the-mechanics-of-efficient-typing/)

## Gap found in current implementation

~~`confidence_of`/`key_confidence` (`confidence.py:18-36`) compute mastery purely from `mean_time_ns` vs. target speed. `KeyStats.error_count` is tracked and persisted (`aggregate.py:55`, `models.py:34`) but never read by `confidence_of`, `compute_unlocked`, or `select_focus` — so a key typed fast but frequently wrong currently reads as "confident" and can unlock the next key prematurely, contradicting Keybr's dual speed+accuracy threshold and the accuracy-first principle (point 2 above).~~ **Fixed**: `confidence_of` uses `min(speed, accuracy)` where speed is `target_ms / actual_ms` and accuracy is `samples / (samples + error_count)`. Fast-but-sloppy or slow-but-accurate keys no longer compensate each other (unlike a product). Windowed aggregates also recency-weight mean time, accuracy, and attempt counts so stale practice doesn't mask recent sloppiness. `compute_unlocked`/`select_focus`/`GetHeatmap` all inherit this via `confidence_of`.

~~`AdaptiveGenerator.generate_lesson` (`generator.py:30-37`) sampled every word from the plain language-frequency Markov table and only guaranteed the focus key appeared *once* across the whole lesson (via `_inject_focus`) — everything else was generic full-alphabet text, unlike Keybr's "adaptive per-letter frequency weighting based on personal error/latency history" (line 20 above) and short of the deliberate-practice principle (point 4).~~ **Fixed**: `confidence.py` now has `practice_weight(confidence, max_bias=3.0)` — weak keys get up to 4x sampling weight, mastered keys (confidence ≥ 1.0) get baseline weight 1.0. `TransitionTable.sample` (`markov.py`) takes an optional `char_weights` map that multiplies each candidate's language-frequency weight before `rng.choices`; `AdaptiveGenerator.generate_word`/`generate_lesson` thread it through. `BuildLesson` (`build_lesson.py`) computes `char_weights` from each unlocked key's live confidence, so generated text is now generally biased toward weak keys, not just guaranteed to touch the single focus key once.
