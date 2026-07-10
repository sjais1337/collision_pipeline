"""
===============================================================================
File      : lc_search.py
Purpose   : Local-collision search -- the FIRST and SOLE source of local
            collisions in the faithful preset-free pipeline. This is the 2026
            paper's Section 3 / Algorithm 1 tool: a word-level model of the
            message expansion that minimizes (number of nonzero-difference words
            + cancellation conditions) over a (start V, span K) sweep for a fixed
            attack step R. There are no presets and no hardcoded patterns; every
            local collision the DC stage uses is produced here from scratch.

Differences from src/search_local_collision_model.py:
  - attackStep (R) is a parameter, not hardcoded to 37.
  - The hardcoded `index_i=[5,7,8,13,21,22]` override in assign_value is REMOVED,
    so the tool genuinely searches per (start, span) instead of being pinned to
    the published 36-step pattern.
  - It writes the best local collision (and a few LC-search alternates, all
    discovered here -- not presets) to results_lc/lc_<R>.json:
        {"best": {start_step, span, active_words, ...}, "alternates": [...]}
    for config_gen.py / dc_search.py to consume.

The word-level model itself (the 27 valid expansion-activity transitions and the
ConditionNum bookkeeping) is identical to the original 2026 tool. The objective
`active = sum(ConditionNum) + sum(active W)` is the paper's Algorithm 1 objective.

Running: python3 lc_search.py [R1 R2 ...]   (default: 18..24)
===============================================================================
"""

import os
import subprocess
import re
import json
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS_LC = os.path.join(HERE, "results_lc")
WORK = os.path.join(RESULTS_LC, "_work")

# The 27 valid word-level (W[i-2],W[i-7],W[i-15],W[i-16],W[i],ConditionNum) transitions.
CONSTRAINTS_UPDATE = ['000000', '000110', '001010', '001101', '001110', '010010',
                      '010101', '010110', '011001', '011010', '011101', '011110',
                      '100010', '100101', '100110', '101001', '101010', '101101',
                      '101110', '110001', '110010', '110101', '110110', '111001',
                      '111010', '111101', '111110']

THREADS = os.environ.get("SHA2_THREADS", str(os.cpu_count() or 4))


def handle(s):
    if "0b" in s:
        temp = s.replace("0b", "").split(" = ")
    elif "0x" in s:
        temp = s.replace("0x", "").split(" = ")
    else:
        return None, None
    index = temp[0].split("_")
    return index, temp[1]


def build_model(start_step, spans_step, message_bound):
    """Returns (declare_str, constraints_str) for one (start, span) configuration."""
    declare = []
    constraints = []

    def save(name, length=1):
        line = "%s: BITVECTOR(%s);\n" % (name, length)
        if line not in declare:
            declare.append(line)
        return name

    W = [save("W_%s" % i) for i in range(message_bound)]
    Cond = [save("ConditionNum_%s" % (i + 16)) for i in range(message_bound - 16)]

    # word-level expansion-activity propagation constraints
    temp = ""
    for i in range(16, message_bound):
        clauses = []
        for pat in CONSTRAINTS_UPDATE:
            clauses.append("%s@%s@%s@%s@%s@%s = 0bin%s" % (
                W[i - 2], W[i - 7], W[i - 15], W[i - 16], W[i], Cond[i - 16], pat))
        temp += "ASSERT " + " OR ".join(clauses) + ";\n"
    constraints.append(temp)

    # boundary conditions (the FIRST loop of the original assign_value only;
    # the hardcoded index_i override loop is intentionally NOT included).
    for i in range(message_bound):
        if i < start_step:
            constraints.append("ASSERT %s = 0bin0;\n" % W[i])
        elif i > start_step + spans_step - 1:
            constraints.append("ASSERT %s = 0bin0;\n" % W[i])
        elif i == start_step or i == start_step + spans_step - 1:
            constraints.append("ASSERT %s = 0bin1;\n" % W[i])

    return "".join(declare), "".join(constraints), W, Cond


def obj_str(object_value, start_step, spans_step, message_bound, W, Cond):
    obj = "active: BITVECTOR(7);\n"
    terms = []
    for i in range(message_bound - 16):
        terms.append("0bin000000@%s" % Cond[i])
    for i in range(start_step, start_step + spans_step):
        terms.append("0bin000000@%s" % W[i])
    obj += "ASSERT active = BVPLUS(7," + ",".join(terms) + ");\n"
    obj += "ASSERT BVLE(active, 0bin%s);\n" % bin(object_value)[2:].zfill(7)
    return obj


def solve_config(start_step, spans_step, message_bound):
    """Descend on the objective for one (start, span); return (active_words, cond_total) or None."""
    declare, constraints, W, Cond = build_model(start_step, spans_step, message_bound)
    query = "\nQUERY FALSE;\nCOUNTEREXAMPLE;"
    os.makedirs(WORK, exist_ok=True)
    cvc = os.path.join(WORK, "lc_%s_%s_%s.cvc" % (message_bound, spans_step, start_step))

    active = spans_step + 1
    best = None
    while True:
        with open(cvc, "w") as f:
            f.write(declare)
            f.write(constraints)
            f.write(obj_str(active - 1, start_step, spans_step, message_bound, W, Cond))
            f.write(query)
        try:
            R = subprocess.check_output(["stp", cvc, "--cryptominisat", "--threads", THREADS],
                                        stderr=subprocess.STDOUT).decode()
        except subprocess.CalledProcessError as e:
            return None
        if R.strip() == "Valid.":
            # no (further) solution at this bound
            break
        # parse counterexample
        data = R.replace("ASSERT( ", "").replace(" );", "").replace("\nInvalid.", "").split("\n")
        w_val = {}
        cond_total = 0
        new_active = None
        for line in data:
            if "ConditionNum_" in line:
                idx, v = handle(line)
                if v is not None:
                    cond_total += int(v.replace("0b", "").replace("0x", ""), 2 if "b" in line else 16) if v else 0
            elif line.startswith("ASSERT") is False and " = " in line and line.split(" = ")[0].strip().startswith("W_"):
                idx, v = handle(line)
                if idx is not None:
                    w_val[int(idx[1])] = v
            elif "active" in line and " = " in line:
                t = line.split(" = ")[1]
                if "0x" in t:
                    new_active = int(t, 16)
                elif "0b" in t:
                    new_active = int(t, 2)
        active_words = sorted([i for i, v in w_val.items() if v == "1"])
        best = {"active_words": active_words, "cond_total": cond_total,
                "objective": new_active if new_active is not None else (active - 1)}
        if new_active is None:
            break
        active = new_active
    return best


def search_round(R, span_lo=6, span_hi=None, start_lo=4):
    if span_hi is None:
        span_hi = min(R - start_lo, 24)
    candidates = []
    for span in range(span_lo, span_hi + 1):
        for start in range(start_lo, R - span + 1):
            res = solve_config(start, span, R)
            if res and res["active_words"]:
                cand = {"R": R, "start_step": start, "span": span,
                        "active_words": res["active_words"],
                        "num_active": len(res["active_words"]),
                        "cond_total": res["cond_total"]}
                candidates.append(cand)
                print("  R=%d start=%d span=%d -> active=%s cond=%d" % (
                    R, start, span, res["active_words"], res["cond_total"]))
    if not candidates:
        return []
    # Prefer: fewest active words, then fewest conditions, then smallest span.
    # De-duplicate identical active-word sets (keep the sparsest-span instance).
    candidates.sort(key=lambda c: (c["num_active"], c["cond_total"], c["span"]))
    seen = set()
    ranked = []
    for c in candidates:
        key = tuple(c["active_words"])
        if key in seen:
            continue
        seen.add(key)
        ranked.append(c)
    return ranked

def run_for(R):
    os.makedirs(RESULTS_LC, exist_ok=True)

    print("=== Local-collision search for R=%d ===" % R)

    ranked = search_round(R)

    if not ranked:
        print("  no local collision found for R=%d" % R)
        return None

    # chooses the best local collision, saves separately
    best = ranked[0]

    out = os.path.join(RESULTS_LC, "lc_%d.json" % R)

    # saves 2 to 30 as alternates.
    with open(out, "w") as f:
        json.dump({"best": best, "alternates": ranked[1:30]}, f, indent=2)

    print("  BEST R=%d: start=%d span=%d active=%s cond=%d (%d found) -> %s" % (
        R, best["start_step"], best["span"], best["active_words"], best["cond_total"],
        len(ranked), out))

    return best


def main():
    rounds = [int(x) for x in sys.argv[1:]] or list(range(18, 25))
    for R in rounds:
        run_for(R)


if __name__ == "__main__":
    main()
