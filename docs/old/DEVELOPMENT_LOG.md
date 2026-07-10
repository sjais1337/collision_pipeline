# Development log: small-round SHA-256 DC search + SFS collision finder

A chronological, honest account of how this toolkit was built, including the
conceptual and implementation problems hit along the way, how each was diagnosed
and fixed, and the questions asked at each fork. Read alongside ARCHITECTURE.md
(what the pieces are) and METHOD.md (the math).

---

## Phase 0 - Goal and starting point

**Goal.** Take the released 2026 (`zhang_li_gao`) SHA-2 SAT/SMT framework -
hardwired to its published 37-step attack - and make it run and be benchmarked for
*small* numbers of attack steps (R ~ 18-24), then produce and verify colliding
message pairs for the resulting characteristics.

**Starting material.** `../2026/` contains three tools: `local_collision_search/`,
`differential_search/`, and `attack_validation/` (C++ verifiers). The whole thing
depends on STP + CryptoMiniSat.

**First questions I asked:**
- Is the solver stack even present? -> `stp --version` / `which cryptominisat5`:
  yes, STP 2.3.3 + CryptoMiniSat 5, 16 cores. Good, this is config work not setup.
- How hardwired is "37 steps"? -> Reading `search_differential_trail.py`, the
  answer was "very": `start_step/end_step/message_bound/message_differential`, the
  `op0..op9` per-step model arrays, and two hardcoded Hamming-weight bounds in
  `assign_value` were all 37-specific.

**Decision.** Copy the four sources into `src/` untouched and build *driver* scripts
around them, so the originals stay pristine.

---

## Phase 1 - Retargeting the DC search to small rounds

### Step 1: local-collision search (`lc_search.py`)

`search_local_collision_model.py` searches the message expansion for active-word
supports. Reading it, I found `assign_value` had a second loop hardcoding
`index_i=[5,7,8,13,21,22]` (the 36-step pattern), which *overrode* the span logic -
so as shipped it does not actually search, it re-derives the published pattern.

- **Fix:** removed that override loop in the working copy; parameterized
  `attackStep=R`; swept `(start, span)`; saved a ranked candidate list per round.

- **Conceptual problem discovered:** for small R the message expansion has only a
  couple of steps (`i in [16,R)`), so the word-level model is under-constrained and
  returns degenerate 2-word supports like `[6,11]`. These are valid for the
  *schedule* but cannot host a *state* collision.
  - *Question I asked:* "Is minimizing active words the right objective here?" -
    Answer: it is for long expansions (37 steps), but at small R it pushes toward
    over-sparse, useless supports. So I kept the auto search but saved the full
    candidate list and planned to prefer structured presets.

### Step 2: config generator (`config_gen.py`) + validation gate

I reverse-engineered the per-step rules by staring at the shipped 37-step arrays:
- `op8` (W expansion) = 1 exactly on the active words.
- `op0/op1` (condition counting) on only the uncontrolled window `[17, end)`, with
  `op1=3` (x-based) at step 17 and `op1=2` ((x,y)-based) at 18 - matching the
  paper's "count only E16 at step 17, only (E17,E16) at step 18" argument.
- `op2/op5` (E/A expansion method) over `[start, end-4)` and `[start, 16)`.

- **Implementation safeguard:** a `--validate` mode that regenerates the 37-step
  arrays and diffs them against the shipped values. It passed bit-for-bit, which
  was the green light that the retargeting logic was trustworthy.
  - *Question:* "Are the `end-4` / `16` boundaries real or coincidental from one
    example?" - I couldn't be fully sure from a single example, so I treated them as
    heuristics, documented as such, and relied on empirical runs to catch problems.

### Step 3: DC search driver (`dc_search.py`)

Reused the unit functions; removed the 37-specific Hamming bounds; wrapped each
`stp` call in a timeout; logged per-iteration solve times.

**Implementation problem 1 - "Unresolved symbol: wv_7_0".** First small-round runs
errored in ~0.8s. Cause: `assign_value` zeroed message words for *all* `i in
range(message_bound)`, but words in gaps (e.g. word 7 when a candidate starts at
step 8) are never *declared* by `sha_e`/`message_expand`, so STP saw an assertion on
an undeclared symbol.
- **Fix:** only zero *declared* message words (scan `self.declare` for `wv_`).

**Conceptual problem 2 - the degenerate supports were UNSAT/timeout.** The sparse
2-3 word supports the auto search produced either timed out or were unsatisfiable.
- *Question:* "What does a *real* local collision look like?" - I read a 2026
  `pattern_*.txt`: the published 37-step LC is `{6,7,9,14,22,23}` with the expansion
  keeping `W24..W36` difference-free. The structure is a perturbation + contiguous
  corrections, not isolated words.
- **Fix:** added `known_local_collisions.py` with a `dense_classic` generator (a
  contiguous correction span - the textbook SHA-2 local-collision shape). Seeding
  the DC search with `dense-classic-w9` immediately produced a real DC: R=18
  minimized to 5 conditions.

**Implementation problem 3 - a value-parse crash.** The descent printed
`int('0b0001011001 );', 2)` errors - I was slicing the `pro` line wrong.
- **Fix:** strip the ` );` suffix and the `0b/0x` prefix before `int(...)`.

At this point R=18,19,20 produced minimized DCs (5,5,7 conditions).

### Step 4: the Sanadhya-Sarkar local collision (user steer)

The user pointed out (a) I shouldn't brute-force rounds myself and should use known
local collisions from the papers, and (b) the tool wasn't using all cores. Two
threads:

- **Cores.** `ps -o nlwp` showed `stp` single-threaded early (its bit-blasting phase)
  but `%CPU=344` later (CMS solving uses several cores). The real issues were (i) my
  `min(16, ...)` cap (removed; now `SHA2_THREADS`/`os.cpu_count()`), and (ii) a
  single query never saturates 16 cores -> the fix for "use all cores" is to run
  independent solves in parallel.
  - I also found and killed **orphan `stp` processes**: when I `pkill`'d a sweep, the
    `subprocess` `stp` children were orphaned (reparented to systemd) and kept
    burning cores. Lesson: kill the whole tree / the `stp` children too.

- **SS local collision.** Found `papers/old/collision_attacks_upto_24_step_sanadhya_2008.pdf`,
  extracted Table 2 Column I: a 9-step LC with active words `{i,i+1,i+2,i+3,i+7,i+8}`
  (words `i+4..i+6` carry no difference), and the paper's 24-step placement `i=10`.
  Added it as a preset. Running R=24 with it gave a DC minimized to **1 condition**
  in ~2 minutes - the cleanest result of the whole exercise.

**Implementation problem 4 - lost background output.** A parallel `timeout 600 ...`
sweep produced empty logs and no results: Python block-buffers stdout to a file, so
the `timeout` kill discarded everything.
- **Fix:** run background jobs with `python3 -u` (unbuffered) and size the timeout to
  the job; re-ran 21/22/23 sequentially and reliably.

Benchmark (`benchmark.py`) aggregates everything; since `matplotlib` wasn't installed
and the network was restricted, I added a dependency-free SVG plotter.

---

## Phase 2 - DC parser, SFS collision finder, docs

### Step 5: the parser (`parse_dc.py`)

Straightforward: parse the `.out` assignment, map `(v,d)` to `=`/`n`/`u`, print the
per-step `∇A/∇E/∇W` table, count conditions from the `ned_xor`/`ned_if`/`nev_if`
counters, report HA/HE/HW and a `2^-conditions` probability estimate. Worked first
try on R=24.

### Step 6: the collision finder - the big debugging saga

This is where the deep conceptual work happened. The plan (and the user's choice) was
a "STP value model": fix the DC's signed differences, bind values via `derive_cond`,
solve for real `W`.

**Prerequisite fix.** `sha2_value` built A-register names `xv_/xd_` but *declared*
`yv_/yd_`, so a standalone value model left `xv_/xd_` unresolved. Fixed the two
declaration lines. (Harmless to prior runs, where `op9=0`.)

**Attempt A - value-only model + pinned differences.** SAT, but the independent
verifier said **collide=False**.
- *Question:* "Is my verifier wrong, or my extraction, or the model?" I debugged by
  replaying the *first* message `M` through my Python SHA-256 and comparing each step
  to the solver's own `x_/y_` state values: **all matched exactly**. So extraction,
  endianness, register mapping, and the SHA-256 functions were all correct for `M`.
- So the problem was `M'`. I replayed `M'=M⊕Δ` and watched the state difference:
  it was tiny at step 10 then **exploded** at step 11 onward.

**The conceptual root cause (the key insight).** This is exactly the
modular-addition condition leak. Pinning the differences and computing only `M`'s
arithmetic enforces the Boolean-gate conditions (their monitors are value-bound) but
**not** the addition (carry) conditions, because the difference model's additions use
a carry-*difference* `Δc` that is never tied to `M`'s real carries. So nothing forces
`M⊕Δ` to actually follow the trail. The "SAT" only meant "a first message consistent
with the pinned differences exists," not "a conforming pair exists."

**Attempt B - full coupled model (`op9=1`).** I reused `DCModel` with value
transitions on for all steps, plus pinned differences. Still **collide=False**.
- *Question:* "Doesn't the coupled difference+value model guarantee a conforming
  pair?" - No, and this sharpened my understanding: the value model computes only
  *one* execution; the additions in the two models still aren't value-linked across
  `M` and `M'`. The coupled model checks a kind of validity but does not, by itself,
  hand you a `M` for which `M⊕Δ` collides.

**Attempt C - two-execution model.** The faithful, bulletproof solver formulation:
model *both* SHA-256 executions over the window with a shared (free) chaining value,
tie the two messages by `W' = W ⊕ Δ_W`, and assert the final states are equal.
- First try (assert only final collision): **timeout** - with no trail to guide it,
  the solver was searching for a collision from scratch.
  - **Fix:** also pin the per-step state-difference *activity* (`BVXOR(A_M_i,A_P_i) =
    mask_i`) to the DC, collapsing the search to filling conforming free bits. Now
    SAT in seconds - but still **collide=False** in the verifier.

**Implementation problem - the real culprit all along.** I isolated it with a
one-step CVC test (feed known inputs, assert the step equals the Python result):
the CVC arithmetic *matched* Python. So the model was right; the **output parser**
was wrong. STP prints 32-bit values as `0x42F751E7` (uppercase, `0x`), but my
`load_words` regex only matched `0hex`/`0bin` - so it parsed nothing and the verifier
replayed all-zero garbage.
- **Fix:** accept `0x`/`0hex`/`0bin` in the parser. R=24 then verified
  **collide=True** - two messages differing in `{10,11,12,13,17,18}` producing an
  identical state.

*Lesson:* when a model and an independent checker disagree, bisect aggressively -
verify the checker against ground truth first (it was correct), then the per-unit
arithmetic (correct), which left only I/O parsing.

### Step 7: the verifier (`verify_collision.py`)

Pure-Python reduced-round SHA-256 over the window from a custom chaining value. Caught
one self-inflicted bug immediately: `Ch = (x&y)^(~x&z)&MASK` has wrong precedence in
Python; fixed to `((x&y)^((~x)&z))&MASK`.

### Step 8: run on all DCs + docs

Ran the finder+verifier across R=18-24. Every round yielded a **verified** SFS
colliding pair. Wrote `docs/{ARCHITECTURE,METHOD,USAGE,RESULTS,LIMITATIONS}.md` and
expanded the README.

---

## Final outcome

| R | DC conditions | local collision | pair |
|---|---------------|-----------------|------|
| 18 | 5 | dense (w9) | verified SFS |
| 19 | 5 | dense (w9) | verified SFS |
| 20 | 7 | dense (w9) | verified SFS |
| 21 | 7 | dense (w9) | verified SFS |
| 22 | 9 | Sanadhya-Sarkar i=8 | verified SFS |
| 23 | 12 | Sanadhya-Sarkar i=8 | verified SFS |
| 24 | 1 | Sanadhya-Sarkar i=10 | verified SFS |

## Recurring lessons

1. **Reproduce the known config first.** The `config_gen --validate` gate (match the
   shipped 37-step arrays bit-for-bit) caught retargeting mistakes cheaply.
2. **Structured beats sparse at small R.** The word-level auto search degenerates;
   real (dense / Sanadhya-Sarkar) local collisions are what actually host state
   collisions.
3. **The addition-condition leak is real and operational.** It is the reason the
   single-execution value model cannot hand you a conforming pair, and the reason the
   two-execution model is necessary.
4. **An independent verifier is non-negotiable.** It is what exposed both the
   conceptual leak and the `0x` parser bug; never trust "solver said SAT" as proof of
   a collision.
5. **Background-job hygiene:** `python3 -u`, size timeouts, and kill orphaned `stp`
   children.
