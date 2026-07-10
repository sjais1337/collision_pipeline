"""
Usage:
    python3 run_pipeline.py R [per_call_timeout_s] [oracle_timeout_s] [o5_value 0|1] [stage_budget_s]

`stage_budget_s` (optional) caps each cascade stage's descent wall-time: O1->O5

Artifacts:
    results_lc/lc_R.json           local collision 
    results_dc/dc_R.json, dc_R.txt differential characteristic + cascade optima
    results_dc/collision_R.json    SFS colliding pair (CV_in, W0..W15 for M, M')
===============================================================================
"""

import os
import sys
import json

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import lc_search
import dc_search
import parse_dc


def run_pipeline(R, timeout=300, oracle_timeout=300, o5_value=True,
                 max_attempts=8, solve_budget=None):
    print("#" * 70)
    print("# Faithful preset-free pipeline  (SFS regime)   R = %d" % R)
    print("#" * 70)

    # --- 1. Local collision (sole source, no presets) ---
    best = lc_search.run_for(R)
    if best is None:
        print("No local collision for R=%d; aborting." % R)
        return {"R": R, "status": "no_local_collision"}

    # --- 2. DC search (O1->O5 cascade) + SFS pair validation ---
    summary = dc_search.run_round(
        R, timeout=timeout, max_attempts=max_attempts, validate=True,
        oracle_timeout=oracle_timeout, o5_value=o5_value, solve_budget=solve_budget)
    chosen = summary.get("chosen")
    if not chosen:
        print("No differential characteristic found for R=%d." % R)
        return {"R": R, "status": "no_dc", "summary": summary}

    # --- 3. Probability report (faithful O3) ---
    print("\n" + "=" * 70)
    out_file = summary.get("chosen_out") or chosen.get("out_file")
    cand = chosen.get("candidate", {})
    start = cand.get("start_step")
    span = cand.get("span")
    end = (start + span) if (start is not None and span is not None) else R
    stored = chosen.get("stage_optima", {}).get("o3", chosen.get("min_conditions"))
    parsed = parse_dc.parse(out_file, R, start=start, end=end,
                            lo=max(0, (start or 0) - 4), hi=min(end + 1, R),
                            stored_o3=stored)
    print(parse_dc.pretty(parsed))
    print("Local collision : %s  active=%s" % (cand.get("source"), cand.get("active_words")))

    coll = summary.get("collision")
    if coll:
        print("\nSFS colliding pair : status=%s  verified=%s  diff input words=%s" % (
            coll.get("status"), coll.get("verified"), coll.get("message_diff_input_words")))

    return {"R": R, "status": "ok", "local_collision": best,
            "O3": parsed["O3"], "probability_exponent": parsed["O3"],
            "collision_status": (coll or {}).get("status"),
            "verified": (coll or {}).get("verified"),
            "dc_summary": os.path.join("results_dc", "dc_R%d.json" % R)}


if __name__ == "__main__":
    R = int(sys.argv[1])
    timeout = int(sys.argv[2]) if len(sys.argv) > 2 else 300
    oracle_timeout = int(sys.argv[3]) if len(sys.argv) > 3 else 300
    o5_value = bool(int(sys.argv[4])) if len(sys.argv) > 4 else True
    budget = int(sys.argv[5]) if len(sys.argv) > 5 else None
    res = run_pipeline(R, timeout=timeout, oracle_timeout=oracle_timeout,
                       o5_value=o5_value, solve_budget=budget)
    print("\nPIPELINE RESULT:", json.dumps(res, default=str))
