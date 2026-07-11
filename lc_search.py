"""
Searches for the local collisions: which words have active message 
difference to return no difference at a further round.
"""

import os
import subprocess
import json
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS_LC = os.path.join(HERE, "results_lc")
WORK = os.environ.get(
    "SHA2_WORK_DIR",
    os.path.join(RESULTS_LC, "_work"),
)
os.makedirs(WORK, exist_ok=True)

# The 27 valid word-level (W[i-2],W[i-7],W[i-15],W[i-16],W[i],ConditionNum) transitions.
CONSTRAINTS_UPDATE = ['000000', '000110', '001010', '001101', '001110', '010010',
                      '010101', '010110', '011001', '011010', '011101', '011110',
                      '100010', '100101', '100110', '101001', '101010', '101101',
                      '101110', '110001', '110010', '110101', '110110', '111001',
                      '111010', '111101', '111110']

THREADS = os.environ.get("SHA2_THREADS", str(os.cpu_count() or 4))


def log(message):
    print(
        "[%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), message),
        flush=True,
    )

# just a utility
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
    """
    Args:
        start_step: first step with difference
        spans_step: words till last difference
        message_bound: number of rounds
    
    Returns:
        STP declaration of variables
        STP constraints on variables: first and last of span need difference, outside span 0 diff
        Word variable names
        Condition variable names
    """

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

    # boundary conditions, difference must be in the start, and end step
    for i in range(message_bound):
        if i < start_step:
            constraints.append("ASSERT %s = 0bin0;\n" % W[i])
        elif i > start_step + spans_step - 1:
            constraints.append("ASSERT %s = 0bin0;\n" % W[i])
        elif i == start_step or i == start_step + spans_step - 1:
            constraints.append("ASSERT %s = 0bin1;\n" % W[i])

    return "".join(declare), "".join(constraints), W, Cond


def obj_str(object_value, start_step, spans_step, message_bound, W, Cond):
    """Generate the STP objective for minimizing the conditions, i.e. active Words + cancellation steps"""

    obj = "active: BITVECTOR(7);\n"

    terms = []

    # cancellation steps
    for i in range(message_bound - 16):
        terms.append("0bin000000@%s" % Cond[i])

    # active words
    for i in range(start_step, start_step + spans_step):
        terms.append("0bin000000@%s" % W[i])

    obj += "ASSERT active = BVPLUS(7," + ",".join(terms) + ");\n"
    obj += "ASSERT BVLE(active, 0bin%s);\n" % bin(object_value)[2:].zfill(7)

    return obj


def solve_config(start_step, spans_step, message_bound):
    """Descend on the objective for one (start, span); return (active_words, cond_total) or None."""

    declare, constraints, W, Cond = build_model(start_step, spans_step, message_bound)

    query = "\nQUERY FALSE;\nCOUNTEREXAMPLE;"

    cvc = os.path.join(WORK, "lc_%s_%s_%s.cvc" % (message_bound, spans_step, start_step))

    active = spans_step + 1
    best = None

    while True:
        log(
            "LC solve R=%d start=%d span=%d active_bound=%d"
            % (message_bound, start_step, spans_step, active)
        )
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

        # break if solution found
        if R.strip() == "Valid.":
            break

        # parse counterexample
        data = R.replace("ASSERT( ", "").replace(" );", "").replace("\nInvalid.", "").split("\n")
        w_val = {}
        cond_total = 0
        new_active = None

        for line in data:
            base = 2 if "0b" in line else 16 if "0x" in line else None
            if base is None:
                continue

            idx, v = handle(line)
            if idx is None or v is None:
                continue

            value = int(v, base)
            if idx[0] == "ConditionNum":
                cond_total += value
            elif idx[0] == "W":
                w_val[int(idx[1])] = value
            elif idx[0] == "active":
                new_active = value

        active_words = sorted(i for i, v in w_val.items() if v == 1)
        best = {"active_words": active_words, "cond_total": cond_total,
                "objective": new_active if new_active is not None else (active - 1)}
        if new_active is None:
            break
        active = new_active

    return best



def search_round(R, span_lo=6, span_hi=None, start_lo=4):
    """searches multiple spans, from span_lo to span_hi with various start rounds
    
    Returns
        ranked: full description of the best LCs found, ordered by active words,
          cancellation steps and span. 
    """

    # NOTE: hard-coded to 24 max => Possibly cause of condition explosion beyond round 16 in A
    # TODO: Fix it probably, or make it more generalised

    if span_hi is None:
        span_hi = min(R - start_lo, 24)

    candidates = []

    for span in range(span_lo, span_hi + 1):

        # since for a given span, the latest start will be when last difference is at round end
        for start in range(start_lo, R - span + 1):
            res = solve_config(start, span, R)

            if res and res["active_words"]:
                cand = {
                    "R": R, 
                    "start_step": start, 
                    "span": span,
                    "active_words": res["active_words"],
                    "num_active": len(res["active_words"]),
                    "cond_total": res["cond_total"]
                }
                
                candidates.append(cand)
                log("  R=%d start=%d span=%d -> active=%s cond=%d" % (
                    R, start, span, res["active_words"], res["cond_total"]))

    if not candidates:
        return []

    # order: fewest active words, then fewest conditions, then smallest span.
    candidates.sort(key=lambda c: (c["num_active"], c["cond_total"], c["span"]))
    seen = set()
    ranked = []

    for c in candidates:
        key = tuple(c["active_words"])

        # remove identical active-word sets
        if key in seen:
            continue
        seen.add(key)
        ranked.append(c)

    return ranked

def run_for(R):
    os.makedirs(RESULTS_LC, exist_ok=True)

    log("=== Local-collision search for R=%d ===" % R)

    ranked = search_round(R)

    if not ranked:
        log("  no local collision found for R=%d" % R)
        return None

    # chooses the best local collision, saves separately
    best = ranked[0]

    out = os.path.join(RESULTS_LC, "lc_%d.json" % R)

    # saves 2 to 30 as alternates.
    with open(out, "w") as f:
        json.dump({"best": best, "alternates": ranked[1:30]}, f, indent=2)

    log("  BEST R=%d: start=%d span=%d active=%s cond=%d (%d found) -> %s" % (
        R, 
        best["start_step"], 
        best["span"], 
        best["active_words"], 
        best["cond_total"],
        len(ranked), 
        out)
    )

    return best


def main():
    # just runs for multiple rounds in the arguments
    rounds = [int(x) for x in sys.argv[1:]] or list(range(18, 25))

    for R in rounds:
        run_for(R)


if __name__ == "__main__":
    main()