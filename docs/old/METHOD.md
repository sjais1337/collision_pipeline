# Method and math

## Signed differences

Each bit of each register/message word carries a signed difference `∇κ = (κv, κd)`
encoding the relationship between the bit in the two parallel hash executions:

| (v,d) | symbol | meaning (first -> second) |
|-------|--------|---------------------------|
| (0,0) | `=`    | no difference |
| (0,1) | `n`    | 0 -> 1 |
| (1,1) | `u`    | 1 -> 0 |

The probability that a random conforming pair follows a characteristic is governed
by two quantities: the **Hamming weight** (number of active `n`/`u` bits) and the
number of **bit conditions** imposed by the Boolean functions.

## Bit conditions

A Boolean transition `f(∇x,∇y,∇z) -> ∇w` is often value-dependent: the output
difference holds only if certain conditions on the actual input bits hold. The
2026 tool counts these with `(t1,t2)` and variable-specific models; `config_gen`
turns these on only over the uncontrolled window (steps >= 16, after the first 16
free message words). `parse_dc.py` reports them from the `ned_xor`/`ned_if`/`nev_if`
counters in the solution. The minimized count is the exponent in the probability
estimate `2^-conditions`.

## Two-horizon indexing

Mirroring the shipped tool:
- `message_bound = R` is the number of attack steps (length of the message schedule).
- `end_step = start + span` is where the state difference returns to zero (the
  collision point inside the window). For small R with small spans the active
  collision occupies fewer than R steps.

## Local collisions

A SHA-2 local collision is a perturbation in one message word plus corrections in
later words so the state difference cancels. The word-level auto search
(`lc_search.py`) finds expansion-consistent active-word supports; for small R these
degenerate to over-sparse 2-word supports, so we prefer structured presets:
- **Sanadhya-Sarkar 9-step LC** (`collision_attacks_upto_24_step_sanadhya_2008.pdf`,
  Table 2 Column I): active words `{i,i+1,i+2,i+3,i+7,i+8}`; paper placement for
  24 steps is `i=10` -> `{10,11,12,13,17,18}`.
- **dense_classic**: a contiguous correction span (textbook shape) for rounds with
  no published LC.

## Why the value model needs two executions

The single most important subtlety. To obtain an actual conforming pair, one might
try: fix the DC's signed differences, compute the first message's arithmetic, and
bind values to differences with `derive_cond`. This is **insufficient** -- it
enforces the conditions from Boolean gates (whose monitors are bound) but **not**
the modular-addition (carry) conditions, because the difference-model additions use
a carry-*difference* `Δc` that is never tied to the first message's real carries.
Consequently `M' = M ⊕ Δ` need not follow the trail, and the state difference
explodes after the first step (we observed exactly this).

The faithful, robust finder therefore models **both** executions explicitly:

    EXISTS  CV, W :  SHA_window(CV, W)  ==  SHA_window(CV, W ⊕ Δ_W),

with `W`'s active bits pinned to the DC's signs and the per-step state-difference
*activity* pinned to the characteristic (to guide the solver). Because both real
executions are present, a SAT result is a genuine conforming pair, independently
re-checked by `verify_collision.py`.

This is also a concrete demonstration of the "addition condition leak" that makes a
difference-model DC potentially invalid: if no `(CV, W)` satisfies the two-execution
model, the DC has no conforming pair (`find_collision` reports `invalid_dc`).

## Semi-free-start collisions

These window-confined DCs zero the state difference before `start` and in the tail,
but the actual register *values* entering the window are free. A conforming pair is
therefore a **semi-free-start collision**: a freely chosen input chaining value
`CV_in` plus two messages that collide over the window (and hence over all R steps,
since the message words are identical after the window). This matches the SFS
instances reported in the 2026 paper. Converting to a full-IV collision requires the
two-block message-connection method and is out of scope.

## The declaration-bug fix

`src/unit_function_256.py:sha2_value` built the A-register difference names `xv_/xd_`
but declared `yv_/yd_`, so a standalone value model left `xv_/xd_` unresolved. The
two declaration lines were corrected to `xv_/xd_`. (With the original `op9=0` flow
this code path was never exercised, so the DC search results are unaffected.)
