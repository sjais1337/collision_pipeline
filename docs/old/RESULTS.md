# Results

All runs on a 16-core machine with STP 2.3.3 + CryptoMiniSat 5. Every colliding
pair below is **independently verified** by the pure-Python reduced-round SHA-256
in `verify_collision.py` (the two parallel messages produce an identical 8-register
state at the end of the window).

## Differential characteristics + semi-free-start collisions

| R  | DC conditions | HE | HW | local collision      | colliding pair |
|----|---------------|----|----|----------------------|----------------|
| 18 | 5             | 5  | 39 | dense-classic (w9)   | verified SFS   |
| 19 | 5             | 5  | 23 | dense-classic (w9)   | verified SFS   |
| 20 | 7             | 7  | 64 | dense-classic (w9)   | verified SFS   |
| 21 | 7             | 7  | 79 | dense-classic (w9)   | verified SFS   |
| 22 | 9             | 9  | 54 | Sanadhya-Sarkar i=8  | verified SFS   |
| 23 | 12            | 12 | 50 | Sanadhya-Sarkar i=8  | verified SFS   |
| 24 | 1             | 20 | 47 | Sanadhya-Sarkar i=10 | verified SFS   |

DC-search times ranged from ~5 to ~10 minutes per round (full minimization);
finding+verifying each colliding pair took seconds to ~40s. See
`bench/results.csv` and `bench/*.svg` for the timing/condition curves.

## Worked example: 24-step SHA-256 via the Sanadhya-Sarkar local collision

1. **Local collision (from the paper).** Sanadhya-Sarkar's 9-step LC, placed at the
   24-step position `i=10`, activates message words `{10,11,12,13,17,18}`
   (`known_local_collisions.sanadhya_sarkar`).

2. **Differential characteristic.** `config_gen` builds the window `start=10,
   end=19` with x-based / (x,y)-based IF condition counting at steps 17/18, and
   `dc_search` minimizes to **1 bit-condition** (HE/HW as in the table). Inspect with:

   ```
   python3 parse_dc.py 24
   ```

   which prints the per-step `∇A / ∇E / ∇W` strings, the conditions (IF=1), and the
   probability estimate `2^-1`.

3. **Colliding pair.** `find_collision.py 24` builds the two-execution value model,
   solves for a shared chaining value `CV_in` and a message whose `Δ`-shifted twin
   collides over the window, and `verify_collision.py 24` confirms it:

   ```
   R=24 window=[10,19) collide=True
     state(M )=8ec4cf2e 3edb820c a9727f79 44e36634 434fd0ac 68200b0d 24f6327c 9ee6cac1
     state(M')=8ec4cf2e 3edb820c a9727f79 44e36634 434fd0ac 68200b0d 24f6327c 9ee6cac1
     message difference present: True
   ```

   The two messages differ in words `{10,11,12,13,17,18}` yet yield an identical
   state after the window -- a semi-free-start collision for 24-step SHA-256.

## Notes

- For R=18-21 there is no published small-round local collision in the repo, so the
  `dense_classic` contiguous-correction preset is used; for R=22-24 the
  Sanadhya-Sarkar LC at the paper's placements is used.
- The exact `CV_in` and message words for each pair are stored in
  `results_dc/collision_R{R}.json` (`cv_in_hex`, `W_M_hex`, `W_Mprime_hex`).
