"""
===============================================================================
File      : parse_dc.py
Purpose   : Parser / pretty-printer / probability reporter for a differential
            characteristic produced by the dc_search O1->O5 cascade.

Reads an STP COUNTEREXAMPLE .out file (and, optionally, the dc_R{R}.json summary)
and produces:
  - per-step signed-difference strings for the A, E and W registers,
  - the FAITHFUL O3 differential-condition count, computed with the EXACT same
    terms and window as dc_search.obj/the 2026 objective:
        O3 = sum_{17<=i<end}(ned_xor + nev_if + ned_if)   (Boolean BD)
           + sum_{16<=i<end-4} yd                          (H(dE), uncontrolled)
    (The previous version dropped nev_if and the H(dE) term and used the wrong
    window, so its "probability" was meaningless -- e.g. it reported 2^-0 for a
    trail the search scored at O3=25.)
  - the differential probability estimate 2^-O3, plus an SFS attack-cost note,
  - the total Hamming weights HA/HE/HW over the whole trail [0,R),
  - get_fixed_differences(): the raw (var, bit) difference assignments, used by
    find_collision.py to pin the characteristic.

Signed-difference encoding (matching the 2026 tool): (v,d) in {(0,0),(0,1),(1,1)}
    (0,0) -> '='   no difference            (1,1) -> 'u'   1 -> 0
    (0,1) -> 'n'   0 -> 1                    (stray (1,0) shown as '?')
Note: a bit is active iff d == 1, so H = sum of the d-variables -- the same
quantity the objective sums.

Usage: python3 parse_dc.py 24        # parse results_dc/dc_R24.json's chosen .out
       python3 parse_dc.py <out_file> <R> [start] [end]
===============================================================================
"""

import os
import re
import sys
import json

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS_DC = os.path.join(HERE, "results_dc")
BLOCK = 32

_ASSIGN = re.compile(r"([A-Za-z0-9_]+)\s*=\s*0(b|x)([0-9a-fA-F]+)")


def load_assignment(out_file):
    """Parse 'ASSERT( var = 0bN );' (and 0xN) lines into {var: int}."""
    asn = {}
    for line in open(out_file):
        m = _ASSIGN.search(line)
        if m:
            asn[m.group(1)] = int(m.group(3), 2 if m.group(2) == "b" else 16)
    return asn


def symbol(v, d):
    if (v, d) == (0, 0):
        return "="
    if (v, d) == (0, 1):
        return "n"
    if (v, d) == (1, 1):
        return "u"
    return "?"


def _reg_string(asn, prefix_v, prefix_d, step):
    """Signed-difference string for one register at one step, MSB->LSB."""
    chars = []
    active = 0
    for bit in range(BLOCK - 1, -1, -1):
        v = asn.get("%s_%d_%d" % (prefix_v, step, bit))
        d = asn.get("%s_%d_%d" % (prefix_d, step, bit))
        if v is None or d is None:
            chars.append(".")  # not present in this model
            continue
        s = symbol(v, d)
        chars.append(s)
        if s != "=":
            active += 1
    return "".join(chars), active


def _count_counter(asn, name, step):
    return sum(asn.get("%s_%d_%d" % (name, step, b), 0) for b in range(BLOCK))


def parse(out_file, R, start=None, end=None, lo=None, hi=None, stored_o3=None):
    """Parse a DC .out. `end` = local-collision end (start+span) defines the
    uncontrolled window; defaults to R. Computes O3 with the exact objective
    terms/window used by dc_search."""
    asn = load_assignment(out_file)
    if end is None:
        end = R
    # display window
    if lo is None:
        lo = 0
    if hi is None:
        hi = R
    rows = []
    for step in range(lo, hi):
        a_str, _ = _reg_string(asn, "xv", "xd", step)
        e_str, _ = _reg_string(asn, "yv", "yd", step)
        w_str, _ = _reg_string(asn, "wv", "wd", step)
        rows.append({"step": step, "A": a_str, "E": e_str, "W": w_str,
                     "cond_xor": _count_counter(asn, "ned_xor", step),
                     "cond_if": _count_counter(asn, "ned_if", step)
                              + _count_counter(asn, "nev_if", step)})

    # Full-trail Hamming weights (active iff d==1), over [0,R) -> consistent with
    # dc_search.count_hamming (no window-dependent disagreement).
    HA = sum(_count_counter(asn, "xd", i) for i in range(R))
    HE = sum(_count_counter(asn, "yd", i) for i in range(R))
    HW = sum(_count_counter(asn, "wd", i) for i in range(R))

    # O3 -- EXACTLY the objective's Boolean-condition + H(dE) terms and window.
    bd_xor = sum(_count_counter(asn, "ned_xor", i) for i in range(17, end))
    bd_if = sum(_count_counter(asn, "ned_if", i) + _count_counter(asn, "nev_if", i)
                for i in range(17, end))
    he_unc = sum(_count_counter(asn, "yd", i) for i in range(16, max(16, end - 4)))
    O3 = bd_xor + bd_if + he_unc

    return {
        "R": R, "start": start, "end": end, "out_file": out_file, "rows": rows,
        "HA": HA, "HE": HE, "HW": HW,
        "bd_xor": bd_xor, "bd_if": bd_if, "bd_total": bd_xor + bd_if,
        "he_uncontrolled": he_unc,
        "O3": O3, "stored_O3": stored_o3,
    }


def pretty(parsed):
    out = []
    out.append("Differential characteristic for %d-step SHA-256" % parsed["R"])
    out.append("=" * 78)
    out.append("%-4s %-34s %-34s" % ("i", "dA (x)", "dE (y)"))
    out.append("-" * 78)
    for r in parsed["rows"]:
        if r["A"].strip(".=") == "" and r["E"].strip(".=") == "" and r["W"].strip(".=") == "":
            continue
        out.append("%-4d %-34s %-34s" % (r["step"], r["A"], r["E"]))
    out.append("-" * 78)
    out.append("%-4s %-34s" % ("i", "dW (w)"))
    for r in parsed["rows"]:
        if r["W"].strip(".=") == "":
            continue
        out.append("%-4d %-34s  (cond: xor=%d if=%d)" % (
            r["step"], r["W"], r["cond_xor"], r["cond_if"]))
    out.append("-" * 78)
    out.append("Hamming weights (whole trail) : HA=%d  HE=%d  HW=%d" % (
        parsed["HA"], parsed["HE"], parsed["HW"]))
    out.append("O3 differential conditions [16,%s) : Boolean(Sigma=%d, IF=%d) + H(dE)_unc=%d = %d" % (
        parsed["end"], parsed["bd_xor"], parsed["bd_if"],
        parsed["he_uncontrolled"], parsed["O3"]))
    if parsed["stored_O3"] is not None and parsed["stored_O3"] != parsed["O3"]:
        out.append("  WARNING: stored O3=%s disagrees with recomputed O3=%d" % (
            parsed["stored_O3"], parsed["O3"]))
    out.append("Differential probability  : 2^-%d" % parsed["O3"])
    out.append("SFS search cost (approx)  : 2^%d random pairs to conform" % parsed["O3"])
    return "\n".join(out)


def get_fixed_differences(out_file):
    """Return {var_name: bit} for all signed-difference vars (xv/xd/yv/yd/wv/wd)
    present in the solution, for pinning the characteristic in the value model."""
    asn = load_assignment(out_file)
    fixed = {}
    for var, bit in asn.items():
        for pref in ("xv_", "xd_", "yv_", "yd_", "wv_", "wd_"):
            if var.startswith(pref):
                fixed[var] = bit
                break
    return fixed


def _resolve(arg):
    """Accept either an R (-> dc_R{R}.json's chosen out) or a direct .out path.
    Returns (out_file, R, candidate dict, stored_O3)."""
    if arg.isdigit():
        R = int(arg)
        d = json.load(open(os.path.join(RESULTS_DC, "dc_R%d.json" % R)))
        chosen = d.get("chosen")
        if not chosen:
            raise SystemExit("R=%d has no found DC" % R)
        out_file = d.get("chosen_out") or chosen.get("out_file")
        stored = chosen.get("stage_optima", {}).get("o3", chosen.get("min_conditions"))
        return out_file, R, chosen.get("candidate", {}), stored
    return arg, int(sys.argv[2]), {}, None


if __name__ == "__main__":
    out_file, R, cand, stored = _resolve(sys.argv[1])
    start = cand.get("start_step") if cand else (int(sys.argv[3]) if len(sys.argv) > 3 else None)
    span = cand.get("span") if cand else None
    end = (start + span) if (start is not None and span is not None) else \
          (int(sys.argv[4]) if len(sys.argv) > 4 else R)
    lo = max(0, (start - 4)) if start is not None else 0
    hi = min(end + 1, R) if end is not None else R
    parsed = parse(out_file, R, start=start, end=end, lo=lo, hi=hi, stored_o3=stored)
    print(pretty(parsed))
    if cand:
        print("Local collision : %s  active=%s" % (cand.get("source"), cand.get("active_words")))
