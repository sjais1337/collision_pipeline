# Architecture

This toolkit retargets the 2026 (`zhang_li_gao`) SHA-2 SAT/SMT framework so that
differential characteristics (DCs) and semi-free-start (SFS) colliding message
pairs can be produced and benchmarked for small numbers of attack steps. It is
built on STP + CryptoMiniSat. The pristine 2026 sources live in `src/`; every
tool here drives or extends them without modifying the originals (except one
declaration-bug fix documented in METHOD.md).

## Data flow

```
                         known_local_collisions.py
                         (published / repo / SS / dense presets)
                                     |
   lc_search.py  ----------------+   |
   (auto word-level LC search)   |   |
   results_lc/lc_R.json          v   v
                              config_gen.py
                  (start,end,message_bound,message_differential,op0..op9)
                                     |   validated to reproduce the
                                     |   shipped 37-step config exactly
                                     v
                              dc_search.py
                  (difference model + bit-condition objective; descent)
                       results_dc/dc_R.json  (+ dc_R.txt)
                                     |
                 +-------------------+--------------------+
                 v                                        v
           parse_dc.py                              find_collision.py
   (signed-diff table, conditions,        (two-execution STP value model:
    HW, probability; fixed-diff API)       EXISTS CV,W : window(CV,W)=window(CV,W^d))
                                            results_dc/collision_R.json
                                                     |
                                                     v
                                            verify_collision.py
                              (pure-Python R-step SHA-256; confirms the SFS pair)

                 benchmark.py  ->  bench/results.csv + SVG plots
```

## Components

| File | Responsibility |
|------|----------------|
| `src/` | Pristine 2026 sources: `unit_function_256.py` (step builders, value model), `constrains.py` (truth tables, `k_constant_256`), `search_differential_trail.py`, `search_local_collision_model.py`. |
| `lc_search.py` | Word-level local-collision search, retargeted to any round; emits ranked candidate supports. |
| `known_local_collisions.py` | Presets: published 36/37-step LCs, repo-found patterns, the Sanadhya-Sarkar 9-step LC, and a `dense_classic` generator. |
| `config_gen.py` | Maps `(R, LC spec)` to the `op0..op9` arrays + bounds. Self-validates against the shipped 37-step config. |
| `dc_search.py` | Builds and solves the difference-model SMT instance with the bit-condition objective; descent minimization; per-call timeout + timing. |
| `parse_dc.py` | Parses a solver `.out` into a readable characteristic; condition/HW/probability accounting; `get_fixed_differences()` API. |
| `find_collision.py` | Two-execution STP value model that yields a verified SFS colliding pair for a DC. |
| `verify_collision.py` | Independent pure-Python reduced-round SHA-256 verifier. |
| `benchmark.py` | Aggregates DC results into a CSV + plots. |

## Two solver stages

1. **Difference stage** (`dc_search.py`): variables are signed differences `(v,d)`;
   the objective minimizes Hamming weight + Boolean bit-conditions; output is a DC.
2. **Value stage** (`find_collision.py`): variables are real 32-bit words; two full
   SHA-256 executions are modeled and asserted to collide. This stage is where a
   concrete conforming pair is produced (see METHOD.md for why a single-execution
   value model is insufficient).
