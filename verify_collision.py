"""
===============================================================================
File      : verify_collision.py
Purpose   : Independent (pure-Python) verifier of a semi-free-start collision
            for reduced-round SHA-256, modelling the REAL compression function.

Given a freely-chosen input chaining value CV_in (the 8 registers a..h entering
step 0) and the 16 message words W0..W15, it runs the genuine SHA-256 message
schedule (expanding to W0..W_{R-1}) and the R-step state update, returning the
final 8-register state. Two messages that share CV_in and whose R-step outputs
are identical constitute a semi-free-start collision for R-step SHA-256.

This is independent of STP, so it cross-checks the solver's output. Unlike the
previous version it expands the message schedule (W16.. are derived, not free)
and starts from step 0, so it verifies a true reduced-round SHA-256 object.
===============================================================================
"""

import os
import sys
import json

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "src"))
from constrains import k_constant_256  # noqa: E402

MASK = 0xFFFFFFFF


def rotr(x, n):
    return ((x >> n) | (x << (32 - n))) & MASK


def shr(x, n):
    return (x >> n) & MASK


def Sigma0(x):
    return rotr(x, 2) ^ rotr(x, 13) ^ rotr(x, 22)


def Sigma1(x):
    return rotr(x, 6) ^ rotr(x, 11) ^ rotr(x, 25)


def sigma0(x):
    return rotr(x, 7) ^ rotr(x, 18) ^ shr(x, 3)


def sigma1(x):
    return rotr(x, 17) ^ rotr(x, 19) ^ shr(x, 10)


def Ch(x, y, z):
    return ((x & y) ^ ((~x) & z)) & MASK


def Maj(x, y, z):
    return (x & y) ^ (x & z) ^ (y & z)


def expand_schedule(words16, R):
    """Real SHA-256 message expansion: W0..W15 -> W0..W_{R-1}."""
    W = [w & MASK for w in words16[:16]]
    for i in range(16, R):
        W.append((sigma1(W[i - 2]) + W[i - 7] + sigma0(W[i - 15]) + W[i - 16]) & MASK)
    return W


def compression_trace(cv_in, words16, R):
    """Return the final state, schedule, and per-step A/E values."""
    a, b, c, d, e, f, g, h = [w & MASK for w in cv_in]
    W = expand_schedule(words16, R)
    A = []
    E = []
    for i in range(R):
        T1 = (h + Sigma1(e) + Ch(e, f, g) + k_constant_256[i] + W[i]) & MASK
        T2 = (Sigma0(a) + Maj(a, b, c)) & MASK
        h, g, f, e, d, c, b, a = g, f, e, (d + T1) & MASK, c, b, a, (T1 + T2) & MASK
        A.append(a)
        E.append(e)
    return (a, b, c, d, e, f, g, h), W, A, E


def compress_full(cv_in, words16, R):
    """Return the 8-register state after R reduced SHA-256 steps."""
    final_state, _, _, _ = compression_trace(cv_in, words16, R)
    return final_state


def verify_pair(cv_in, words16_M, words16_Mp, R):
    """Return (collides, state_M, state_Mp) for two 16-word messages over R steps."""
    sM = compress_full(cv_in, words16_M, R)
    sMp = compress_full(cv_in, words16_Mp, R)
    return sM == sMp, sM, sMp


def verify_from_json(coll_json):
    d = json.load(open(coll_json))
    if d.get("status") != "found":
        print("collision_json status = %s (nothing to verify)" % d.get("status"))
        return False
    R = d["R"]
    cv_in = [int(x, 16) for x in d["cv_in_hex"]]
    wM = [int(x, 16) for x in d["W_M_hex"]]
    wP = [int(x, 16) for x in d["W_Mprime_hex"]]
    collides, sM, sMp = verify_pair(cv_in, wM, wP, R)
    print("R=%d collide=%s" % (R, collides))
    print("  state(M )=%s" % " ".join("%08x" % x for x in sM))
    print("  state(M')=%s" % " ".join("%08x" % x for x in sMp))
    print("  input-word difference present: %s" % (wM != wP))
    print("  differing input words: %s" % [j for j in range(16) if wM[j] != wP[j]])
    return collides


if __name__ == "__main__":
    arg = sys.argv[1]
    coll = arg if arg.endswith(".json") else os.path.join(HERE, "results_dc", "collision_R%s.json" % arg)
    ok = verify_from_json(coll)
    sys.exit(0 if ok else 2)
