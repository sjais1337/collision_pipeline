# Limitations and references

## Limitations

- **Semi-free-start only.** The colliding pairs share a freely chosen input chaining
  value; they are SFS collisions over the attack window, not full collisions from the
  SHA-256 IV. A full collision needs the two-block message-connection method, which is
  not implemented here.
- **Small rounds.** The toolkit targets R ~ 18-24. The word-level auto local-collision
  search degenerates for small R (short message expansion), so structured presets
  (Sanadhya-Sarkar, dense_classic) are the reliable drivers there.
- **Single-query parallelism.** STP+CryptoMiniSat does not saturate many cores on one
  query; core utilization comes from running independent solves in parallel.
- **DC validity.** A DC found with the difference model alone (value transitions off)
  may be invalid; `find_collision.py` is the definitive validity check -- `invalid_dc`
  means no conforming pair exists for that characteristic's message difference.
- **Probability estimate.** `parse_dc.py` reports `2^-(uncontrolled bit-conditions)` as
  a first-order estimate; it does not model message-modification degrees of freedom or
  the full two-block attack complexity.

## Provenance

- The four files in `src/` are verbatim copies of `../2026/differential_search/` and
  `../2026/local_collision_search/`, except the one A-register declaration fix in
  `sha2_value` (see METHOD.md).
- `config_gen.py --validate` proves the retargeting reproduces the shipped 37-step
  `op0..op9` arrays bit-for-bit.

## References

- Zhang, Li, Gao et al., *Collision Attacks on SHA-256 up to 37 Steps with Improved
  Trail Search*, ASIACRYPT 2026 (`papers/zhang_li_gao_2026_37_steps.pdf`).
- Li, Liu, Wang et al., *The first practical collision for 31-step SHA-256*,
  ASIACRYPT 2024; *New collision attacks on round-reduced SHA-512*, CRYPTO 2025.
- Sanadhya, Sarkar, *New Collision Attacks against Up to 24-step SHA-2*, INDOCRYPT
  2008 (`papers/old/collision_attacks_upto_24_step_sanadhya_2008.pdf`) - source of the
  9-step local collision and the 24-step placement i=10.
- De Canniere, Rechberger, *Finding SHA-1 Characteristics*, ASIACRYPT 2006 - origin of
  signed/generalized conditions and automatic search.
- Mendel, Nad, Schlaffer, *Finding SHA-2 Characteristics* (ASIACRYPT 2011) and
  *Improving Local Collisions* (EUROCRYPT 2013).
