"""
guided_pair.py -- GUIDED two-execution SFS pair search.

The unguided find_collision (pin input-word diffs + assert final collision) is a
hard SAT instance for some DCs even at O3=1. This guided version additionally
pins the DC's per-step state-difference ACTIVITY: for every step i it asserts
    BVXOR(aM_i, aP_i) = mask_A_i ,   BVXOR(eM_i, eP_i) = mask_E_i ,
where mask_A_i / mask_E_i are the A/E difference masks read from the DC .out.
This collapses the search to filling conforming free bits along the known trail
(the technique that solved the SS 24-step pair in ~33s earlier), and additionally
certifies that THIS specific characteristic (not merely the input difference) is
realized. Independent verification by verify_collision is unchanged.

Usage: python3 -u guided_pair.py <dc_out> <R> [timeout_s] [threads]
"""
import os, sys, subprocess, time, json
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "src"))
from constrains import k_constant_256
from parse_dc import get_fixed_differences
from find_collision import (rotr, shr, xor3, big_sigma0, big_sigma1,  # noqa
                            small_sigma0, small_sigma1, ch, maj, hx,
                            reg_diff, word_diff, load_words)
from verify_collision import verify_pair

def log(m): print("[%s] %s" % (time.strftime("%H:%M:%S"), m), flush=True)

def build_guided_cvc(R, fixed):
    decls, asserts = [], []
    def new(n): decls.append("%s : BITVECTOR(32);\n" % n); return n
    def eq(n, e): asserts.append("ASSERT %s = %s;\n" % (n, e))

    cv = [new("cv_%s" % r) for r in "abcdefgh"]
    masks = {}
    for j in range(16):
        m, s = word_diff(fixed, j)
        masks[j] = m
        wm = new("wM_%d" % j)
        for b, val in s.items():
            asserts.append("ASSERT %s[%d:%d] = 0bin%d;\n" % (wm, b, b, val))
    for j in range(16):
        eq(new("wP_%d" % j), "BVXOR(wM_%d,%s)" % (j, hx(masks[j])))

    def expand(tag):
        for i in range(16, R):
            eq(new("w%s_%d" % (tag, i)), "BVPLUS(32,%s,%s,%s,%s)" % (
                small_sigma1("w%s_%d" % (tag, i-2)), "w%s_%d" % (tag, i-7),
                small_sigma0("w%s_%d" % (tag, i-15)), "w%s_%d" % (tag, i-16)))
    expand("M"); expand("P")

    def run_exec(tag):
        a, b, c, d, e, f, g, h = cv
        A, E = {}, {}
        for i in range(R):
            w = "w%s_%d" % (tag, i)
            s1 = new("s1%s_%d" % (tag, i)); eq(s1, big_sigma1(e))
            cc = new("ch%s_%d" % (tag, i)); eq(cc, ch(e, f, g))
            s0 = new("s0%s_%d" % (tag, i)); eq(s0, big_sigma0(a))
            mj = new("mj%s_%d" % (tag, i)); eq(mj, maj(a, b, c))
            t1 = new("t1%s_%d" % (tag, i)); eq(t1, "BVPLUS(32,%s,%s,%s,%s,%s)" % (h, s1, cc, hx(k_constant_256[i]), w))
            t2 = new("t2%s_%d" % (tag, i)); eq(t2, "BVPLUS(32,%s,%s)" % (s0, mj))
            na = new("a%s_%d" % (tag, i)); eq(na, "BVPLUS(32,%s,%s)" % (t1, t2))
            ne = new("e%s_%d" % (tag, i)); eq(ne, "BVPLUS(32,%s,%s)" % (d, t1))
            A[i], E[i] = na, ne
            a, b, c, d, e, f, g, h = na, a, b, c, ne, e, f, g
        return [a, b, c, d, e, f, g, h], A, E

    finM, AM, EM = run_exec("M")
    finP, AP, EP = run_exec("P")

    # GUIDANCE: pin per-step A/E difference activity to the DC's masks.
    for i in range(R):
        mA, _ = reg_diff(fixed, "xv", "xd", i)
        mE, _ = reg_diff(fixed, "yv", "yd", i)
        asserts.append("ASSERT BVXOR(%s,%s) = %s;\n" % (AM[i], AP[i], hx(mA)))
        asserts.append("ASSERT BVXOR(%s,%s) = %s;\n" % (EM[i], EP[i], hx(mE)))
    # final collision
    for rm, rp in zip(finM, finP):
        asserts.append("ASSERT %s = %s;\n" % (rm, rp))
    return "".join(decls) + "".join(asserts), masks

R       = int(sys.argv[2])
dc_out  = sys.argv[1]
TIMEOUT = int(sys.argv[3]) if len(sys.argv) > 3 else 1800
THREADS = sys.argv[4] if len(sys.argv) > 4 else str(os.cpu_count() or 4)

fixed = get_fixed_differences(dc_out)
body, masks = build_guided_cvc(R, fixed)
WORK = os.path.join(HERE, "results_dc", "_work")
cvc = os.path.join(WORK, "guided_R%d.cvc" % R)
open(cvc, "w").write(body + "\nQUERY FALSE;\nCOUNTEREXAMPLE;")
log("guided CVC built for R=%d (per-step A/E activity pinned); solving (timeout %ds, %s threads)..." % (R, TIMEOUT, THREADS))

t0 = time.time()
try:
    out = subprocess.check_output(["stp", cvc, "--cryptominisat", "--threads", THREADS],
                                  stderr=subprocess.STDOUT, timeout=TIMEOUT).decode()
except subprocess.TimeoutExpired:
    log("guided solve TIMEOUT after %.0fs" % (time.time() - t0)); sys.exit(2)
dt = time.time() - t0

if out.strip() == "Valid.":
    log("guided solve UNSAT (invalid_dc) after %.0fs" % dt); sys.exit(3)

asn = load_words(out)
cv = [asn.get("cv_%s" % r, 0) for r in "abcdefgh"]
wM = [asn.get("wM_%d" % j, 0) for j in range(16)]
wP = [asn.get("wP_%d" % j, 0) for j in range(16)]
collides, sM, sMp = verify_pair(cv, wM, wP, R)
log("SAT after %.0fs; independent verifier collide=%s" % (dt, collides))
rec = {"R": R, "status": "found" if collides else "found_unverified", "verified": collides,
       "local_collision": [10,11,12,13,17,18], "guided": True,
       "cv_in_hex": ["%08x" % x for x in cv],
       "W_M_hex": ["%08x" % x for x in wM],
       "W_Mprime_hex": ["%08x" % x for x in wP],
       "final_state_M": ["%08x" % x for x in sM],
       "message_diff_input_words": [j for j in range(16) if wM[j] != wP[j]]}
json.dump(rec, open(os.path.join(HERE, "results_dc", "collision_R%d_oneLC.json" % R), "w"), indent=2)
if collides:
    log("*** VERIFIED SFS COLLIDING PAIR ***")
    log("CV_in = " + " ".join(rec["cv_in_hex"]))
    log("W_M   = " + " ".join(rec["W_M_hex"]))
    log("W_Mp  = " + " ".join(rec["W_Mprime_hex"]))
    log("diff input words: %s" % rec["message_diff_input_words"])
log("GUIDED DONE status=%s verified=%s" % (rec["status"], collides))
