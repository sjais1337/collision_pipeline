"""
guided_pair.py -- GUIDED two-execution SFS pair search.

The unguided find_collision model pinned only input-word differences. This
guided model pins the complete signed DC relation for every declared message and
state word. For each bit, '=' enforces equality, 'n' enforces 0 -> 1, and 'u'
enforces 1 -> 0. Expanded words satisfy both the real message schedule and their
signed DC relation. A SAT result therefore realizes this specific characteristic,
not merely its activity masks. Independent verification is unchanged.

Usage: python3 -u guided_pair.py <dc_out> <R> [timeout_s] [threads]
"""
import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "src"))

from constrains import k_constant_256
from collision_search_utils import (
    big_sigma0,
    big_sigma1,
    ch,
    has_reg_diff,
    hx,
    load_words,
    maj,
    reg_diff,
    small_sigma0,
    small_sigma1,
)
from parse_dc import get_fixed_differences
from verify_collision import compression_trace


def log(message):
    print(
        "[%s] %s" % (time.strftime("%H:%M:%S"), message),
        flush=True,
    )


def signed_relation_matches(
    first,
    second,
    fixed,
    value_prefix,
    difference_prefix,
    step,
    missing_means_equal=False,
):
    """Check two concrete words against one signed DC relation."""
    present = has_reg_diff(
        fixed,
        value_prefix,
        difference_prefix,
        step,
    )
    if not present:
        return first == second if missing_means_equal else True

    mask, source_bits = reg_diff(
        fixed,
        value_prefix,
        difference_prefix,
        step,
    )
    if (first ^ second) != mask:
        return False
    return all(
        ((first >> bit) & 1) == source_value
        and ((second >> bit) & 1) == 1 - source_value
        for bit, source_value in source_bits.items()
    )


def validate_signed_trace(fixed, schedule_m, schedule_p, state_m, state_p):
    """Return labels for concrete words that do not conform to the signed DC."""
    errors = []

    for step in range(16):
        if not signed_relation_matches(
            schedule_m[step],
            schedule_p[step],
            fixed,
            "wv",
            "wd",
            step,
            missing_means_equal=True,
        ):
            errors.append("W%d" % step)

    for step in range(16, len(schedule_m)):
        if not has_reg_diff(fixed, "wv", "wd", step):
            errors.append("W%d (missing from DC)" % step)
        elif not signed_relation_matches(
            schedule_m[step],
            schedule_p[step],
            fixed,
            "wv",
            "wd",
            step,
        ):
            errors.append("W%d" % step)

    for register, values_m, values_p, value_prefix, difference_prefix in (
        ("A", state_m["A"], state_p["A"], "xv", "xd"),
        ("E", state_m["E"], state_p["E"], "yv", "yd"),
    ):
        for step, (first, second) in enumerate(zip(values_m, values_p)):
            if not has_reg_diff(
                fixed,
                value_prefix,
                difference_prefix,
                step,
            ):
                continue
            if not signed_relation_matches(
                first,
                second,
                fixed,
                value_prefix,
                difference_prefix,
                step,
            ):
                errors.append("%s%d" % (register, step))

    return errors


def build_guided_cvc(rounds, fixed):
    declarations = []
    assertions = []

    def declare(name):
        declarations.append("%s : BITVECTOR(32);\n" % name)
        return name

    def assert_equal(name, expression):
        assertions.append(
            "ASSERT %s = %s;\n" % (name, expression)
        )

    def pin_signed_relation(
        first,
        second,
        value_prefix,
        difference_prefix,
        step,
        missing_means_equal=False,
    ):
        """Constrain two words to the complete signed relation in the DC."""
        present = has_reg_diff(
            fixed, value_prefix, difference_prefix, step
        )
        if not present and not missing_means_equal:
            return False

        mask, source_bits = reg_diff(
            fixed, value_prefix, difference_prefix, step
        )
        assertions.append(
            "ASSERT BVXOR(%s,%s) = %s;\n"
            % (first, second, hx(mask))
        )
        for bit, source_value in source_bits.items():
            assertions.append(
                "ASSERT %s[%d:%d] = 0bin%d;\n"
                % (first, bit, bit, source_value)
            )
            assertions.append(
                "ASSERT %s[%d:%d] = 0bin%d;\n"
                % (second, bit, bit, 1 - source_value)
            )
        return True

    cv = [declare("cv_%s" % register) for register in "abcdefgh"]
    masks = {}
    words_m = [declare("wM_%d" % step) for step in range(16)]
    words_p = [declare("wP_%d" % step) for step in range(16)]
    for step in range(16):
        # Input words not represented by the DC are outside its local collision
        # and therefore equal in the two executions.
        pin_signed_relation(
            words_m[step],
            words_p[step],
            "wv",
            "wd",
            step,
            missing_means_equal=True,
        )
        masks[step], _ = reg_diff(fixed, "wv", "wd", step)

    def expand(tag):
        for step in range(16, rounds):
            assert_equal(
                declare("w%s_%d" % (tag, step)),
                "BVPLUS(32,%s,%s,%s,%s)"
                % (
                    small_sigma1("w%s_%d" % (tag, step - 2)),
                    "w%s_%d" % (tag, step - 7),
                    small_sigma0("w%s_%d" % (tag, step - 15)),
                    "w%s_%d" % (tag, step - 16),
                ),
            )

    expand("M")
    expand("P")

    # Expanded words must obey both the schedule and their exact signed DC.
    for step in range(16, rounds):
        if not pin_signed_relation(
            "wM_%d" % step,
            "wP_%d" % step,
            "wv",
            "wd",
            step,
        ):
            raise ValueError(
                "DC is missing the expanded-word relation for W%d" % step
            )

    def run_exec(tag):
        a, b, c, d, e, f, g, h = cv
        A, E = {}, {}
        for step in range(rounds):
            word = "w%s_%d" % (tag, step)

            sigma1 = declare("s1%s_%d" % (tag, step))
            choose = declare("ch%s_%d" % (tag, step))
            sigma0 = declare("s0%s_%d" % (tag, step))
            majority = declare("mj%s_%d" % (tag, step))
            t1 = declare("t1%s_%d" % (tag, step))
            t2 = declare("t2%s_%d" % (tag, step))
            next_a = declare("a%s_%d" % (tag, step))
            next_e = declare("e%s_%d" % (tag, step))

            assert_equal(sigma1, big_sigma1(e))
            assert_equal(choose, ch(e, f, g))
            assert_equal(sigma0, big_sigma0(a))
            assert_equal(majority, maj(a, b, c))
            assert_equal(
                t1,
                "BVPLUS(32,%s,%s,%s,%s,%s)"
                % (
                    h,
                    sigma1,
                    choose,
                    hx(k_constant_256[step]),
                    word,
                ),
            )
            assert_equal(
                t2,
                "BVPLUS(32,%s,%s)" % (sigma0, majority),
            )
            assert_equal(
                next_a,
                "BVPLUS(32,%s,%s)" % (t1, t2),
            )
            assert_equal(
                next_e,
                "BVPLUS(32,%s,%s)" % (d, t1),
            )

            A[step], E[step] = next_a, next_e
            a, b, c, d, e, f, g, h = (
                next_a,
                a,
                b,
                c,
                next_e,
                e,
                f,
                g,
            )
        return [a, b, c, d, e, f, g, h], A, E

    finM, AM, EM = run_exec("M")
    finP, AP, EP = run_exec("P")

    # Pin every state word represented by the DC, including n/u directions.
    pinned_state_words = 0
    for step in range(rounds):
        pinned_state_words += int(
            pin_signed_relation(
                AM[step],
                AP[step],
                "xv",
                "xd",
                step,
            )
        )
        pinned_state_words += int(
            pin_signed_relation(
                EM[step],
                EP[step],
                "yv",
                "yd",
                step,
            )
        )
    if pinned_state_words == 0:
        raise ValueError("DC contains no A/E state relations")

    # final collision
    for rm, rp in zip(finM, finP):
        assertions.append("ASSERT %s = %s;\n" % (rm, rp))
    return "".join(declarations) + "".join(assertions), masks

def main():
    parser = argparse.ArgumentParser(
        description="Find a pair conforming to an exact signed SHA-256 DC.",
    )
    parser.add_argument("dc_out", help="STP counterexample containing the DC")
    parser.add_argument("rounds", type=int, help="reduced SHA-256 round count")
    parser.add_argument(
        "timeout",
        type=int,
        nargs="?",
        default=1800,
        help="solver timeout in seconds (default: 1800)",
    )
    parser.add_argument(
        "threads",
        nargs="?",
        default=str(os.cpu_count() or 4),
        help="CryptoMiniSat thread count",
    )
    args = parser.parse_args()

    fixed = get_fixed_differences(args.dc_out)
    body, _ = build_guided_cvc(args.rounds, fixed)
    work = os.path.join(HERE, "results_dc", "_work")
    os.makedirs(work, exist_ok=True)
    cvc = os.path.join(work, "guided_R%d.cvc" % args.rounds)
    with open(cvc, "w") as output:
        output.write(body + "\nQUERY FALSE;\nCOUNTEREXAMPLE;")
    log(
        "exact signed-DC model built for R=%d; "
        "solving (timeout %ds, %s threads)..."
        % (
            args.rounds,
            args.timeout,
            args.threads,
        )
    )

    started = time.time()
    try:
        out = subprocess.check_output(
            ["stp", cvc, "--cryptominisat", "--threads", args.threads],
            stderr=subprocess.STDOUT,
            timeout=args.timeout,
        ).decode()
    except subprocess.TimeoutExpired:
        log("guided solve TIMEOUT after %.0fs" % (time.time() - started))
        return 2
    elapsed = time.time() - started

    if out.strip() == "Valid.":
        log("guided solve UNSAT for the exact signed DC after %.0fs" % elapsed)
        return 3

    assignments = load_words(out)
    cv_names = ["cv_%s" % register for register in "abcdefgh"]
    message_names_m = ["wM_%d" % step for step in range(16)]
    message_names_p = ["wP_%d" % step for step in range(16)]
    required_names = cv_names + message_names_m + message_names_p
    missing_names = [
        name for name in required_names if name not in assignments
    ]
    if missing_names:
        log(
            "STP output omitted required assignments: %s"
            % ", ".join(missing_names)
        )
        return 5

    cv = [assignments[name] for name in cv_names]
    wM = [assignments[name] for name in message_names_m]
    wP = [assignments[name] for name in message_names_p]

    sM, schedule_m, state_a_m, state_e_m = compression_trace(
        cv, wM, args.rounds
    )
    sP, schedule_p, state_a_p, state_e_p = compression_trace(
        cv, wP, args.rounds
    )
    collides = sM == sP
    trace_errors = validate_signed_trace(
        fixed,
        schedule_m,
        schedule_p,
        {"A": state_a_m, "E": state_e_m},
        {"A": state_a_p, "E": state_e_p},
    )
    conforms = not trace_errors
    verified = collides and conforms
    log(
        "SAT after %.0fs; independently verified collision=%s, signed DC=%s"
        % (elapsed, collides, conforms)
    )
    rec = {
        "R": args.rounds,
        "status": "found" if verified else "found_unverified",
        "verified": verified,
        "collision_verified": collides,
        "signed_dc_verified": conforms,
        "signed_dc_errors": trace_errors,
        "guidance": "exact_signed_dc",
        "cv_in_hex": ["%08x" % x for x in cv],
        "W_M_hex": ["%08x" % x for x in wM],
        "W_Mprime_hex": ["%08x" % x for x in wP],
        "final_state_M": ["%08x" % x for x in sM],
        "final_state_Mprime": ["%08x" % x for x in sP],
        "message_diff_input_words": [
            j for j in range(16) if wM[j] != wP[j]
        ],
    }
    result_file = os.path.join(
        HERE,
        "results_dc",
        "collision_R%d_oneLC.json" % args.rounds,
    )
    with open(result_file, "w") as output:
        json.dump(rec, output, indent=2)
    if verified:
        log("*** VERIFIED SFS COLLIDING PAIR FOR THE SIGNED DC ***")
        log("CV_in = " + " ".join(rec["cv_in_hex"]))
        log("W_M   = " + " ".join(rec["W_M_hex"]))
        log("W_Mp  = " + " ".join(rec["W_Mprime_hex"]))
        log("diff input words: %s" % rec["message_diff_input_words"])
    log("GUIDED DONE status=%s verified=%s" % (rec["status"], verified))
    return 0 if verified else 4


if __name__ == "__main__":
    sys.exit(main())
