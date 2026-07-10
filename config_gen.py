"""Generate the operation flags used by the differential model.

All ranges below are half-open: [start, end).

op0  Count Sigma1 bit conditions from step 17 to end. Step 17 is where the
     first uncontrolled state word, E16, is used.
op1  Select the IF condition model over the same window: x-based at step 17,
     (x, y)-based at step 18, and the full model from step 19 onward.
op2  Model E differences on [start, end - 4); the final four E words are zero.
op3  Sigma0 conditions are not counted, so this stays zero.
op4  MAJ conditions are not counted, so this stays zero.
op5  Select the A-side difference expansion model. This is not an A-difference
     on/off flag: the collision constraints determine the differences. For the
     collisions considered here, A cancels inside the controlled window, so
     op5 is limited to [start, min(16, end - 8)).
op6  Message-schedule Sigma1 conditions are not counted, so this stays zero.
op7  Message-schedule Sigma0 conditions are not counted, so this stays zero.
     O1 and O2 already optimize the message-difference weight.
op8  Mark the message words selected by the local collision.
op9  Keep the real value model off during DC finding; it is enabled separately
     when value transitions are required.
"""
import json
import sys
import copy

# Message words 0..15 form the controlled region. E16 is first used at step 17.
CONTROLLED_WORDS = 16
COND_START = CONTROLLED_WORDS + 1

ARRAY_LEN = 45

def gen_config(R, start_step, end_step, message_differential, L=ARRAY_LEN):

    if not (0 <= start_step < CONTROLLED_WORDS):
        raise ValueError("start_step must satisfy 0 <= start_step < 16.")
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

    # Sigma1 conditions: step 17 reads the first uncontrolled state word, E16.
    for i in range(COND_START, end_step):
        if 0 <= i < L:
            op0[i] = 1

    # IF conditions: x-based, then (x, y)-based, then the full model.
    for i in range(COND_START, end_step):
        if not (0 <= i < L):
            continue
        if i == COND_START:
            op1[i] = 3      
        elif i == COND_START + 1:
            op1[i] = 2      
        else:
            op1[i] = 1      

    # E differences stop four steps before the collision ends.
    for i in range(start_step, end_step - 4):
        if 0 <= i < L:
            op2[i] = 1

    # op3/op4 stay zero: Sigma0 and MAJ conditions are not counted.

    # op5 selects the A expansion model; it does not switch A differences on.
    # Here A cancels within the controlled region and is zero in the last 8 steps.
    for i in range(start_step, min(CONTROLLED_WORDS, end_step - 8)):
        if 0 <= i < L:
            op5[i] = 1

    # op8 follows the active message words supplied by the local collision.
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
    return cfg

def gen_from_lc(R, lc):
    """lc: a dict with start_step, span, active_words (one candidate)."""
    start_step = lc["start_step"]
    end_step = lc["start_step"] + lc["span"]
    return gen_config(R, start_step, end_step, lc["active_words"])


def with_value_transitions(cfg):
    """Return a copy of cfg with op9"""
    out = copy.deepcopy(cfg)
    op9 = [0] * len(out["op9"])

    for i in range(out["start_step"], out["end_step"]):
        if 0 <= i < len(op9):
            op9[i] = 1

    out["op9"] = op9
    return out


if __name__ == "__main__":
    if len(sys.argv) >= 3:
        R = int(sys.argv[1])
        lc = json.load(open(sys.argv[2]))["best"]
        print(json.dumps(gen_from_lc(R, lc), indent=2))
