# Small-Round SHA-256 DC-Search Experiments

A retargeting of the 2026 (`zhang_li_gao`) SAT/SMT toolkit so the differential-characteristic
(DC) search can be run and benchmarked for small numbers of attack steps (R ~ 18-24),
instead of only the published 36/37-step configuration. Built on STP + CryptoMiniSat.

Originals are untouched in `../2026/`; working copies live in `src/`.

## Pipeline

```
target round R
   |
   v
[lc_search.py]            word-level local-collision search (retargeted to R)
   |   results_lc/lc_R.json  (best + ranked candidate supports)
   |
   +  [known_local_collisions.py]   published / repo-found / dense-classic presets
   |
   v
[config_gen.py]          (start, end, message_bound, message_differential, op0..op9)
   |   validated to reproduce the shipped 37-step config exactly
   v
[dc_search.py]           retargeted DC search; descent that minimizes the
   |                     bit-condition objective; per-call timeout + timing
   |   results_dc/dc_R.json  (+ dc_R.txt human-readable characteristic)
   v
[benchmark.py]           bench/results.csv + time/conditions-vs-steps plots
```

## Files

| File | Role |
|------|------|
| `src/` | Pristine copies of the four 2026 sources (`unit_function_256.py`, `constrains.py`, `search_differential_trail.py`, `search_local_collision_model.py`). |
| `lc_search.py` | Retargeted local-collision search. `attackStep=R` parameterized; the hardcoded `index_i=[5,7,8,13,21,22]` override in the original `assign_value` is removed so it actually searches; emits ranked candidate supports to `results_lc/lc_R.json`. |
| `known_local_collisions.py` | Presets sourced from the repo/papers: the published 36/37-step LCs, every `pattern_*.txt` the 2026 tool emitted, and a `dense_classic` generator (contiguous correction span - the textbook SHA-2 local-collision shape). |
| `config_gen.py` | Builds the per-step `op0..op9` arrays + bounds from `(R, LC spec)`. Run `python3 config_gen.py --validate` to confirm it reproduces the shipped 37-step config exactly. |
| `dc_search.py` | Retargeted DC search. Removes the 37-step-specific Hamming bounds, only zeroes *declared* message words, wraps each `stp` call with a timeout, and logs per-iteration solve times + final conditions / HE / HW. |
| `parse_dc.py` | Parses a solver `.out` into a readable per-step `∇A/∇E/∇W` characteristic with bit-condition counts, Hamming weights, and a probability estimate; exposes `get_fixed_differences()`. |
| `find_collision.py` | Two-execution STP value model that produces a verified semi-free-start colliding message pair for a DC. |
| `verify_collision.py` | Independent pure-Python reduced-round SHA-256 verifier of a colliding pair. |
| `benchmark.py` | Aggregates `results_dc/dc_R*.json` into `bench/results.csv` and plots. |

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) - modules and data flow
- [docs/METHOD.md](docs/METHOD.md) - signed differences, bit conditions, the two-execution value model, SFS collisions
- [docs/USAGE.md](docs/USAGE.md) - end-to-end commands and core utilization
- [docs/RESULTS.md](docs/RESULTS.md) - DC + collision results and the Sanadhya-Sarkar 24-step worked example
- [docs/LIMITATIONS.md](docs/LIMITATIONS.md) - limitations, provenance, references
- [docs/DEVELOPMENT_LOG.md](docs/DEVELOPMENT_LOG.md) - step-by-step build history: every problem (conceptual and implementation), how it was fixed, and the questions worked through

## Usage

```bash
# 1. local-collision search for some rounds (fast)
python3 lc_search.py 18 19 20 21 22 23 24

# 2. validate the config generator against the shipped 37-step arrays
python3 config_gen.py --validate

# 3. inspect presets for a round
python3 known_local_collisions.py 22

# 4. run the DC search for one round  (args: R  per-call-timeout-s  max-attempts)
python3 dc_search.py 18 60 3

# 4b. a 24-step collision using the Sanadhya-Sarkar local collision (paper placement i=10)
python3 dc_search.py 24 600 1            # tries the SS preset [10,11,12,13,17,18] first

# 5. aggregate the benchmark
python3 benchmark.py
```

### Using all cores

Each `stp` invocation is single-threaded during its bit-blasting/CNF phase and then
uses CryptoMiniSat with `--threads N` for solving; `N` defaults to `os.cpu_count()`
(override with `SHA2_THREADS=N`). A *single* query's CMS portfolio scales sublinearly
(~3-4 effective cores here), so to saturate a many-core machine, run *independent*
solves in parallel. Example (3 rounds x 5 threads = 15 cores):

```bash
for R in 21 22 23; do SHA2_THREADS=5 python3 dc_search.py $R 300 2 & done; wait
```

`dc_search.run_round(R)` tries local-collision specs best-first: presets
(`known_local_collisions.presets_for(R)`) first, then the auto-search candidates.
It stops at the first spec that yields a satisfiable DC and then minimizes the
bit-condition objective by descent.

## Key findings / notes

- **The word-level auto search is degenerate at small R.** With only a couple of
  expansion steps (`i in [16, R)`), the tool returns very sparse 2-word supports
  (e.g. `[6,11]`) that are valid for the message schedule but cannot host a
  *state* collision, so the DC search times out / is UNSAT on them. This is an
  inherent property of short message expansions, not a bug.
- **Dense, contiguous local collisions work.** Seeding the DC search with a
  textbook contiguous correction span (`dense_classic`) - the shape real SHA-2
  local collisions take (Sanadhya-Sarkar; Mendel et al.) - yields valid
  characteristics. Example: R=18 with the `dense-classic-w9` support
  `[4..12]` minimizes to 5 conditions (HE=5, HW=39) in ~6 minutes.
- **The Sanadhya-Sarkar local collision gives a clean 24-step DC.** Using the
  9-step SS local collision (`collision_attacks_upto_24_step_sanadhya_2008.pdf`,
  Table 2 Column I) at the paper's 24-step placement i=10 -> active words
  `[10,11,12,13,17,18]`, the search returns a valid 24-step characteristic that
  minimizes to **1** differential condition (HE=30, HW=24), first SAT in ~36s,
  full minimization in ~2 min. This is the recommended way to drive the tool:
  feed it a real, paper-sourced local collision.
- **Core utilization.** A single STP+CMS query only reaches ~3-4 cores; the
  `min(16, ...)` cap in the original copies was removed and threads now default
  to all cores, but real saturation comes from running independent solves in
  parallel (see "Using all cores").
- **`config_gen` is validated**: it reproduces the shipped 37-step `op0..op9`
  arrays bit-for-bit (`--validate`), so the retargeting logic is trustworthy.
- **`op9` (value transitions) is kept off**, faithful to the validated 37-step
  config. Note: `src/unit_function_256.py:sha2_value` declares `yv/yd` where it
  should declare `xv/xd` for the A registers, so enabling `op9` would require
  fixing that first. With `op9` off, a found DC should be cross-checked for
  validity (e.g. via the `../2026/attack_validation` C++ verifiers).
- **Two-horizon indexing** (mirrors the shipped tool): `message_bound = R` (the
  message schedule length), while `end_step = start + span` is where the state
  difference is forced back to zero. For small R with small spans the collision
  effectively occupies fewer than R steps.
