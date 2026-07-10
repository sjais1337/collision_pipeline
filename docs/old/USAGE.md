# Usage

Prerequisites: `stp` and `cryptominisat5` on `PATH` (verify with `stp --version`).
All commands are run from the `experiments_small_rounds/` directory.

## End-to-end for one round

```bash
# 1. (optional) auto-search local collisions for some rounds
python3 lc_search.py 18 19 20 21 22 23 24        # -> results_lc/lc_R.json

# 2. sanity: config generator reproduces the shipped 37-step config
python3 config_gen.py --validate

# 3. inspect the presets available for a round (incl. Sanadhya-Sarkar)
python3 known_local_collisions.py 24

# 4. search a differential characteristic  (args: R  per-call-timeout-s  max-attempts)
python3 dc_search.py 24 300 2                     # -> results_dc/dc_R24.json (+ .txt)

# 5. pretty-print the characteristic
python3 parse_dc.py 24

# 6. find a semi-free-start colliding pair    (args: R  timeout-s)
python3 find_collision.py 24 600                  # -> results_dc/collision_R24.json

# 7. independently verify the pair
python3 verify_collision.py 24

# 8. aggregate the DC benchmark
python3 benchmark.py                              # -> bench/results.csv + plots
```

## Driving the DC search

`dc_search.run_round(R)` tries local-collision specs best-first: structured presets
from `known_local_collisions.presets_for(R)` (Sanadhya-Sarkar where applicable, then
`dense_classic`) and then the auto-search candidates. It stops at the first spec that
yields a satisfiable DC and minimizes the bit-condition objective by descent. Per-call
timeout and max attempts are CLI args.

## Using all cores

A single STP+CMS query only reaches a few cores (and STP's bit-blasting phase is
single-threaded). Threads default to `os.cpu_count()`; override with `SHA2_THREADS`.
To saturate a many-core machine, run independent solves in parallel:

```bash
# different rounds in parallel, 5 threads each (run unbuffered so logs survive)
for R in 21 22 23; do SHA2_THREADS=5 python3 -u dc_search.py $R 300 2 > log_$R 2>&1 & done; wait
```

When backgrounding long runs, always use `python3 -u` (unbuffered) so that a
`timeout`/kill does not discard buffered progress.

## Outputs

- `results_lc/lc_R.json` - local-collision candidates for round R.
- `results_dc/dc_R.json` / `dc_R.txt` - the DC search result and readable trail.
- `results_dc/collision_R.json` - the SFS colliding pair (CV_in, W for M and M').
- `bench/results.csv`, `bench/*.svg` - benchmark table and plots.
