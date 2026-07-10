# Small-round SHA-256 differential trail experiments

This directory contains a SAT/SMT model for experimenting with local collisions
and signed differential characteristics in reduced-round SHA-256. The main
reference is Zhang, Li, Gao, and Wang, *Collision Attacks on SHA-256 up to 37
Steps with Improved Trail Search* (2026), available at
[`../papers/zhang_li_gao_2026_37_steps.pdf`](../papers/zhang_li_gao_2026_37_steps.pdf).

The paper targets 36 and 37 steps. The code here keeps the same broad search
structure but makes the round count, local-collision position, and active message
words configurable. This is useful for testing the model on smaller instances and
for running many independent local-collision candidates.

This is research code rather than a packaged application. It writes STP models
and counterexamples directly into `results_lc/` and `results_dc/`.

## What is being searched

There are three separate objects in the workflow.

1. A **local collision** says which message words may contain a difference. It is
   a word-level activity pattern, not a complete differential trail.
2. A **differential characteristic (DC)** assigns signed bit differences to the
   message and state words while satisfying the SHA-256 propagation model.
3. A **conforming message pair** gives two concrete messages and a common input
   chaining value that follow the signed DC and collide after the selected number
   of steps.

The distinction matters. A sparse pattern found by the local-collision search may
be valid for the message expansion but still be unable to support a state
collision.

## Relation to the 2026 paper

Section 3 of the paper models message expansion using one activity bit per word.
For an expanded word `Wi`, the model considers the activity of `Wi-2`, `Wi-7`,
`Wi-15`, and `Wi-16`. The 27 allowed transitions determine whether `Wi` must be
active and whether a cancellation condition is needed. The local-collision
objective is

```text
number of active message words + number of cancellation conditions
```

This is the model implemented by `lc_search.py`.

The paper then searches for a signed DC with a lexicographic sequence of
objectives. `dc_search.py` follows the same O1--O5 structure:

- **O1** minimizes the weight of the final one or two active message words. In
  the paper's 37-step trail these are `W22` and `W23`.
- **O2** minimizes the total message-difference weight.
- **O3** minimizes the uncontrolled `E` conditions. It includes both difference
  weight and bit conditions introduced by `Sigma1` and `IF`.
- **O4** minimizes the total `A`-difference weight.
- **O5** minimizes the total `E`-difference weight. The value-transition model
  can be enabled at this stage.

The special `IF` choices in `config_gen.py` also come from the paper's Step 3:
step 17 counts only conditions on `E16`, step 18 counts conditions on `E17` and
`E16`, and later steps use the full model. This avoids charging the objective for
conditions in the controlled part of the trail.

The full two-block message-modification attack from the paper is not implemented
here. The concrete-pair code searches for a semi-free-start collision: both
executions share a freely chosen input chaining value.

## Files

### Search code

`lc_search.py`
: Implements the paper's word-level local-collision search. It sweeps start/span
  choices, repeatedly lowers the objective bound, and writes ranked candidates to
  `results_lc/lc_<rounds>.json`.

`config_gen.py`
: Converts a round count and local-collision description into the `op0`--`op9`
  arrays used by the bit-level model. The flags select condition-counting and
  propagation models for `A`, `E`, and `W`. In particular, `op5` selects the
  A-side expansion model; it is not an on/off switch for A differences.

`dc_search.py`
: Builds the signed differential model and minimizes O1 through O5. Every stage
  fixes its best value before the next stage begins. STP counterexamples are kept
  under `results_dc/_work/`, and higher-level runs write JSON summaries under
  `results_dc/`.

`parse_dc.py`
: Reads an STP counterexample and prints the signed differences for `A`, `E`, and
  `W`. It also recomputes O3 and the overall Hamming weights. The symbols are `=`
  for no difference, `n` for `0 -> 1`, and `u` for `1 -> 0`.

### Concrete pair and verification code

`guided_pair.py`
: Builds two concrete SHA-256 executions and pins them to the complete signed DC.
  It enforces the real message schedule, the state relations, and equality of the
  final states. A SAT result is checked again in Python before it is accepted.

`collision_search_utils.py`
: Shared STP-expression and signed-difference helpers used by `guided_pair.py`.

`verify_collision.py`
: Pure-Python reduced-round SHA-256 implementation. It expands the message
  schedule from `W0` through `W15` and verifies that a reported pair reaches the
  same final state. It does not trust the STP model.

### Model sources and generated files

`src/unit_function_256.py`
: Emits the bit-level STP declarations and constraints for the state update,
  message expansion, Boolean functions, modular addition, and value transitions.

`src/constrains.py`
: Transition tables and SHA-256 constants used by the generated model. The
  filename is inherited from the original source.

`results_lc/_work/`
: Generated word-level `.cvc` files.

`results_dc/_work/`
: Generated DC and concrete-pair `.cvc` files plus STP `.out` counterexamples.
  These files can become large during long searches.

`run_one_lc.py`
: Older all-in-one wrapper. It still imports `find_collision.py`, which is not in
  the current directory. Use `dc_search.solve_cascade()` followed by
  `guided_pair.py` instead.

## Requirements

- Python 3
- STP with CryptoMiniSat support
- Enough disk space for generated `.cvc` and `.out` files

No third-party Python packages are required.

Check the solver installation with:

```bash
stp --version
```

The number of CryptoMiniSat threads is controlled by `SHA2_THREADS`. If it is not
set, the scripts use the machine's reported CPU count.

```bash
SHA2_THREADS=4 python3 lc_search.py 24
```

## A known 24-round test

The useful regression case in this directory is the local collision

```text
[10, 11, 12, 13, 17, 18]
```

with `start=10`, `span=9`, and `end=19`. The current model reaches `O3 = 1` for
this case.

Run the search through O3 with:

```bash
SHA2_THREADS=4 python3 -u - <<'PY'
from config_gen import gen_config
from dc_search import solve_cascade

active = [10, 11, 12, 13, 17, 18]
cfg = gen_config(24, 10, 19, active)

result = solve_cascade(
    cfg,
    "ss_R24",
    timeout=600,
    o5_value=False,
    stop_after="o3",
)

print("status:", result["status"])
print("optima:", result["stage_optima"])
print("DC output:", result["out_file"])
PY
```

The output path identifies the most recent STP witness. Inspect it with:

```bash
python3 parse_dc.py <dc-output-file> 24 10 19
```

To search for a concrete pair following that exact signed characteristic:

```bash
python3 -u guided_pair.py <dc-output-file> 24 1800 4
```

If successful, the pair is written to
`results_dc/collision_R24_oneLC.json`. Verify it independently with:

```bash
python3 verify_collision.py results_dc/collision_R24_oneLC.json
```

## Running the local-collision search

To generate candidates for one or more round counts:

```bash
python3 lc_search.py 24
python3 lc_search.py 24 25 26
```

The output contains a best candidate and a ranked list of alternatives. For the
smallest round counts, the objective often prefers two-word patterns. Those
patterns may be perfectly valid message-expansion activities but structurally too
short to produce a state collision. The paper's original search focuses on much
longer spans and attack sizes of at least 32 steps, so the ranking should not be
read as a guarantee that the top small-round candidate has a satisfiable DC.

## Solver output and optimality

Each objective is minimized by repeatedly asking STP for a solution below the
current bound. A stage is proven optimal when either:

- it reaches zero, or
- the next lower bound is UNSAT.

If a call ends through a timeout or a stage budget, the last SAT witness is only
the best value found so far. Check the final entries in the returned `iters` list
before describing a value as a proven optimum.

`parse_dc.py` reports O3 as a probability exponent, giving an estimate of
`2^-O3` for satisfying the uncontrolled differential conditions. This is a trail
estimate, not the cost of the paper's complete collision attack.

## Long and parallel runs

One DC search is sequential, but searches for different local collisions are
independent. Set `SHA2_THREADS` explicitly when launching several jobs so that
each CryptoMiniSat process does not claim every core.

The filenames under `results_dc/_work/` are derived from the `tag` passed to
`solve_cascade()`. Two concurrent jobs using the same tag can overwrite each
other's models and counterexamples. For long campaigns, use a unique tag and a
separate project copy or result directory for each job.

Keep an eye on `results_dc/_work/`: the generated DC models are several megabytes
each, and repeated objective bounds leave multiple counterexamples behind.
