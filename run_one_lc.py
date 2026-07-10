"""
run_one_lc.py -- run the full faithful pipeline for ONE explicit local collision
(bypassing the sparsity ranking), then attempt + verify an SFS colliding pair.

Usage:
  python3 -u run_one_lc.py R start span "w1,w2,..." [full_call_to] [stage_budget] [oracle_to] [o5_value]
  e.g. python3 -u run_one_lc.py 24 10 9 "10,11,12,13,17,18" 300 120 1800 0
"""
import os, sys, json, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dc_search, find_collision, parse_dc

def log(m): print("[%s] %s" % (time.strftime("%H:%M:%S"), m), flush=True)

R          = int(sys.argv[1])
start      = int(sys.argv[2])
span       = int(sys.argv[3])
active     = [int(x) for x in sys.argv[4].split(",")]
full_to    = int(sys.argv[5]) if len(sys.argv) > 5 else 300
budget     = int(sys.argv[6]) if len(sys.argv) > 6 else 120
oracle_to  = int(sys.argv[7]) if len(sys.argv) > 7 else 1800
o5_value   = bool(int(sys.argv[8])) if len(sys.argv) > 8 else False

log("R=%d explicit LC start=%d span=%d active=%s" % (R, start, span, active))
cfg = dc_search.gen_config(R, start, start + span, active)

log("running O1->O5 cascade...")
res = dc_search.solve_cascade(cfg, "one_R%d" % R, timeout=full_to, o5_value=o5_value, budget=budget)
opt = res.get("stage_optima", {})
log("cascade status=%s  O1..O5=%s  O3(conditions)=%s" % (
    res["status"], [opt.get(k) for k in ("o1","o2","o3","o4","o5")], opt.get("o3")))
out_file = res.get("out_file")
if not out_file:
    log("no DC produced; aborting"); sys.exit(1)

# print the characteristic + faithful probability
parsed = parse_dc.parse(out_file, R, start=start, end=start+span,
                        lo=max(0,start-4), hi=min(start+span+1, R),
                        stored_o3=opt.get("o3"))
print(parse_dc.pretty(parsed), flush=True)

# attempt + verify the SFS pair
log("attempting SFS colliding pair (timeout %ds)..." % oracle_to)
coll = find_collision.solve_dc(R, out_file, timeout=oracle_to)
log("pair status=%s verified=%s" % (coll.get("status"), coll.get("verified")))
coll["R"] = R; coll["local_collision"] = active
json.dump(coll, open(os.path.join(HERE, "results_dc", "collision_R%d_oneLC.json" % R), "w"), indent=2)
if coll.get("verified"):
    log("*** VERIFIED SFS COLLIDING PAIR ***")
    log("CV_in = %s" % " ".join(coll["cv_in_hex"]))
    log("W (M ) = %s" % " ".join(coll["W_M_hex"]))
    log("W (M') = %s" % " ".join(coll["W_Mprime_hex"]))
    log("differing input words: %s" % coll.get("message_diff_input_words"))
log("DONE")
