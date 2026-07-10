"""
Rules (L = array length, default 45; indices are absolute SHA-256 steps):
  start_step           = local-collision start
  end_step             = local-collision start + span   (where state diff returns to 0)
  message_bound        = R                               (number of attack steps)
  message_differential = local-collision active words

  op0 (Sigma1 cond-count, sha_e):  1 on the uncontrolled window [17, end_step)
  op1 (IF model, sha_e):           17 -> 3 (x-based), 18 -> 2 ((x,y)-based),
                                   [19, end_step) -> 1 (full+conditions); else 0
  op2 (E expansion method, sha_e): 1 on [start_step, end_step-4)   (method 1)
  op3 (Sigma0 cond-count, sha_a):  0  (A-side conditions not counted, as in the paper)
  op4 (MAJ model, sha_a):          0
  op5 (A expansion method, sha_a): 1 on [start_step, 16)           (controlled region)
  op6 (W sigma1 cond-count):       0
  op7 (W sigma0 cond-count):       0
  op8 (W expansion method):        1 on the active words (only steps > 15 are used)
  op9 (value transition):          0  (faithful to the validated 37-step config;
                                       see note in the DC driver about the sha2_value bug)

Rationale for the universal "17" and "16" boundaries: the controlled region is always
the first 16 message words (steps 0-15), so E16 is always the first uncontrolled state
register and step 17 is always where it is first read as the primary IF/Sigma1 input.
===============================================================================
"""

import json
import sys

ARRAY_LEN = 45

# first 16 (0...15) rounds are controlled, thus 16 is the first uncontrolled word.
CONTROLLED_WORDS = 16
COND_START = CONTROLLED_WORDS + 1


def gen_config(R, start_step, end_step, message_differential, L=ARRAY_LEN):
    # The condition-counting objective (see dc_search.obj_value) references
    # Boolean-condition counters for every step in [COND_START, end_step); those
    # counters only exist for steps that are actually modelled, i.e. steps >=
    # start_step. So the local collision must start within the controlled region.
    
    if not (0 <= start_step < CONTROLLED_WORDS):
        raise ValueError(
            "start_step must satisfy 0 <= start_step < %d (got %d); the "
            "condition window [%d, end) would otherwise reference counters at "
            "steps that are never modelled." % (CONTROLLED_WORDS, start_step, COND_START))
    if end_step > L or end_step <= start_step:
        raise ValueError("end_step %d out of range (start=%d, L=%d)" % (end_step, start_step, L))

    op0 = [0] * L
    op1 = [0] * L
    op2 = [0] * L
    op3 = [0] * L
    op4 = [0] * L
    op5 = [0] * L
    op6 = [0] * L
    op7 = [0] * L
    op8 = [0] * L
    op9 = [0] * L

    # op0: Sigma1 condition counting on the uncontrolled window [COND_START, end)
    for i in range(COND_START, end_step):
        if 0 <= i < L:
            op0[i] = 1

    # op1: IF variable-specific / full+condition models on the uncontrolled window.
    # The first uncontrolled IF input (E16) appears at COND_START -> x-based; the
    # next (E17, E16) at COND_START+1 -> (x,y)-based; deeper steps -> full+cond.
    for i in range(COND_START, end_step):
        if not (0 <= i < L):
            continue
        if i == COND_START:
            op1[i] = 3      # x-based  (counts only E16)
        elif i == COND_START + 1:
            op1[i] = 2      # (x,y)-based (counts E17, E16)
        else:
            op1[i] = 1      # full model + conditions

    # op2: E-side modular-difference expansion method 1 over [start, end-4)
    # (the last 4 E registers are forced difference-free in the collision tail).
    for i in range(start_step, end_step - 4):
        if 0 <= i < L:
            op2[i] = 1

    # op5: A-side expansion method 1 over the controlled region
    # [start, min(CONTROLLED_WORDS, end)). (op5 only selects the modular-difference
    # expansion method, which is soundness-neutral; this mirrors the shipped tool.)
    for i in range(start_step, min(CONTROLLED_WORDS, end_step)):
        if 0 <= i < L:
            op5[i] = 1

    # op8: W-side expansion method 1 on the active (local-collision) words
    for i in message_differential:
        if 0 <= i < L:
            op8[i] = 1

    cfg = {
        "R": R,
        "start_step": start_step,
        "end_step": end_step,
        "message_bound": R,
        "message_differential": list(message_differential),
        "op0": op0, "op1": op1, "op2": op2, "op3": op3, "op4": op4,
        "op5": op5, "op6": op6, "op7": op7, "op8": op8, "op9": op9,
    }
    _check_consistency(cfg)
    return cfg


def _check_consistency(cfg):
    """Every Boolean-condition counter the objective will sum must belong to a
    modelled step (start <= i < end) and have its declaring op set. This is the
    invariant that, if violated, makes STP raise 'Unresolved symbol'."""
    start, end = cfg["start_step"], cfg["end_step"]
    for i in range(COND_START, end):
        # objective references ned_xor at i  -> needs op0[i] == 1 (declares it)
        assert cfg["op0"][i] == 1, "op0[%d] must be 1 to declare ned_xor_%d" % (i, i)
        # objective references ned_if (and nev_if for op1==1) at i -> needs op1 set
        assert cfg["op1"][i] in (1, 2, 3), "op1[%d] must declare IF counters" % i
        # the step must actually be modelled by sha_e/sha_a
        assert start <= i < end, "condition step %d outside modelled range [%d,%d)" % (i, start, end)
    # op8 must mark exactly the active message words
    active = set(cfg["message_differential"])
    for i in range(len(cfg["op8"])):
        assert (cfg["op8"][i] == 1) == (i in active), "op8 mismatch at word %d" % i


def gen_from_lc(R, lc):
    """lc: a dict with start_step, span, active_words (one candidate)."""
    start_step = lc["start_step"]
    end_step = lc["start_step"] + lc["span"]
    return gen_config(R, start_step, end_step, lc["active_words"])


def with_value_transitions(cfg):
    """Return a copy of cfg with op9 (the value-transition / sha2_value model)
    enabled over the whole modelled state window [start, end). This is the O5
    stage's faithful validity model in the 2026 procedure ("we also incorporate
    a model for value transitions"). Kept OUT of gen_config so that the default
    config (and config_gen --validate against the shipped 37-step arrays, whose
    op9 is all-zero) is unaffected; the cascade calls this only for O5.

    sha2_value at step i reads registers [i-4, i] (declared by sha_e) and, for
    i > 15, message_expand_value derives the expanded word values -- both handled
    per-step by dc_search.DCModel.main()."""
    import copy
    out = copy.deepcopy(cfg)
    op9 = [0] * len(out["op9"])
    for i in range(out["start_step"], out["end_step"]):
        if 0 <= i < len(op9):
            op9[i] = 1
    out["op9"] = op9
    return out


# ---------------------------------------------------------------------------
# Validation: the exact op arrays from the shipped 37-step config.
# ---------------------------------------------------------------------------
def _shipped_37():
    return {
        "start_step": 6, "end_step": 24, "message_bound": 37,
        "message_differential": [6, 7, 9, 14, 22, 23],
        "op0": [0]*17 + [1, 1, 1, 1, 1, 1, 1] + [0]*21,
        "op1": [0]*17 + [3, 2, 1, 1, 1, 1, 1] + [0]*21,
        "op2": [0]*6 + [1]*14 + [0]*25,
        "op3": [0]*45,
        "op4": [0]*45,
        "op5": [0]*6 + [1]*10 + [0]*29,
        "op6": [0]*45,
        "op7": [0]*45,
        "op8": [1 if i in (6, 7, 9, 14, 22, 23) else 0 for i in range(45)],
        "op9": [0]*45,
    }


def validate():
    ship = _shipped_37()
    gen = gen_config(37, 6, 24, [6, 7, 9, 14, 22, 23])
    ok = True
    for key in ["op0", "op1", "op2", "op3", "op4", "op5", "op6", "op7", "op8", "op9"]:
        if gen[key] != ship[key]:
            ok = False
            print("MISMATCH %s" % key)
            print("  shipped: %s" % ship[key])
            print("  gen    : %s" % gen[key])
            diffs = [i for i in range(45) if gen[key][i] != ship[key][i]]
            print("  differing indices: %s" % diffs)
    for key in ["start_step", "end_step", "message_bound", "message_differential"]:
        if gen[key] != ship[key]:
            ok = False
            print("MISMATCH %s: gen=%s shipped=%s" % (key, gen[key], ship[key]))
    if ok:
        print("VALIDATION PASS: config_gen reproduces the shipped 37-step config exactly.")
    else:
        print("VALIDATION FAIL")

    # Synthetic configs: not ground-truth arrays, but they must build without
    # error and satisfy the internal consistency invariant (_check_consistency
    # runs inside gen_config). They also exercise the boundary rules for ranges
    # other than the 37-step one.
    synthetic = [
        (24, 10, 19, [10, 11, 12, 13, 17, 18]),   # Sanadhya-Sarkar 24-step
        (23, 8, 17, [8, 9, 10, 11, 15, 16]),       # Sanadhya-Sarkar 23-step
        (22, 7, 16, [7, 8, 10, 15]),               # Sanadhya-Sarkar 22-step (Col II)
        (18, 4, 13, [4, 5, 6, 7, 8, 9, 10, 11, 12]),  # dense-classic w9
    ]
    syn_ok = True
    for (R, s, e, md) in synthetic:
        try:
            gen_config(R, s, e, md)
        except (ValueError, AssertionError) as ex:
            syn_ok = False
            print("SYNTHETIC FAIL (R=%d start=%d end=%d): %s" % (R, s, e, ex))
    # the guard must reject start_step >= CONTROLLED_WORDS
    try:
        gen_config(30, 16, 26, [16, 17, 24, 25])
        syn_ok = False
        print("SYNTHETIC FAIL: start_step=16 was not rejected")
    except ValueError:
        pass
    if syn_ok:
        print("SYNTHETIC PASS: %d configs build consistently; out-of-regime start rejected." % len(synthetic))
    else:
        ok = False
    return ok


if __name__ == "__main__":
    if "--validate" in sys.argv:
        sys.exit(0 if validate() else 1)
    # otherwise: emit a config for a round given an LC json
    if len(sys.argv) >= 3:
        R = int(sys.argv[1])
        lc = json.load(open(sys.argv[2]))["best"]
        print(json.dumps(gen_from_lc(R, lc), indent=2))
