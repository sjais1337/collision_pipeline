#!/usr/bin/env python3
"""Run one staged minimization phase (o1 / o2 / o3) for a single local collision."""

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def log(message):
    print(
        "[%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), message),
        flush=True,
    )


def write_json(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp = path + ".tmp"
    with open(temp, "w") as handle:
        json.dump(payload, handle, indent=2, default=str)
    os.replace(temp, path)


def write_status(path, **fields):
    payload = {}
    if os.path.exists(path):
        try:
            with open(path) as handle:
                payload = json.load(handle)
        except (IOError, ValueError):
            payload = {}
    payload.update(fields)
    payload["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    payload["pid"] = os.getpid()
    write_json(path, payload)


def wait_min_elapsed(started, min_wait_s):
    remaining = min_wait_s - (time.time() - started)
    if remaining > 0:
        log("early finish; waiting %.0fs to reach min-wait %ds" % (
            remaining,
            min_wait_s,
        ))
        time.sleep(remaining)


def load_prior_carries(job_dir, stage):
    """Rebuild carried O1(/O2) asserts from prior stage result files."""
    carried = ""
    needed = []
    if stage == "o2":
        needed = ["o1"]
    elif stage == "o3":
        needed = ["o1", "o2"]

    for prior in needed:
        path = os.path.join(job_dir, "%s_result.json" % prior)
        if not os.path.exists(path):
            raise SystemExit("missing prior result %s for stage %s" % (path, stage))
        data = json.load(open(path))
        carry = data.get("carry")
        if not carry:
            raise SystemExit(
                "prior stage %s has no carry (no witness); cannot run %s"
                % (prior, stage)
            )
        carried += carry
    return carried


def main():
    parser = argparse.ArgumentParser(
        description="One LC, one staged objective (o1/o2/o3).",
    )
    parser.add_argument("--job-dir", required=True)
    parser.add_argument("--spec", required=True, help="path to LC spec.json")
    parser.add_argument("--stage", required=True, choices=("o1", "o2", "o3"))
    parser.add_argument("--budget", type=int, required=True, help="stage wall budget (s)")
    parser.add_argument(
        "--min-wait",
        type=int,
        default=0,
        help="wait at least this many seconds before exiting (even if early)",
    )
    parser.add_argument(
        "--keep-last",
        type=int,
        default=3,
        help="retained SAT witnesses (O3 should use 1)",
    )
    parser.add_argument("--threads", type=int, required=True)
    parser.add_argument(
        "--per-call-timeout",
        type=int,
        default=0,
        help="max STP call timeout; 0 means use remaining budget",
    )
    parser.add_argument(
        "--bound-strategy",
        choices=("linear", "binary"),
        default="linear",
        help="linear descent or binary search on the objective bound",
    )
    parser.add_argument(
        "--start-bound",
        type=int,
        default=-1,
        help="initial bound probe (-1 = strategy default; binary O3 uses 150)",
    )
    args = parser.parse_args()

    job_dir = os.path.abspath(args.job_dir)
    work_dir = os.path.join(job_dir, "work")
    status_file = os.path.join(job_dir, "status.json")
    os.makedirs(work_dir, exist_ok=True)

    os.environ["SHA2_WORK_DIR"] = work_dir
    os.environ["SHA2_STATUS_FILE"] = status_file
    os.environ["SHA2_THREADS"] = str(args.threads)

    sys.path.insert(0, HERE)
    sys.path.insert(0, os.path.join(HERE, "scripts"))

    import dc_search  # noqa: E402
    from staged_descent import descend_retained, set_threads  # noqa: E402

    set_threads(args.threads)

    spec = json.load(open(args.spec))
    R = int(spec["R"])
    start = int(spec["start_step"])
    span = int(spec["span"])
    active = list(spec["active_words"])
    job_id = spec.get("job_id", os.path.basename(job_dir))
    tag = "%s_%s" % (spec.get("tag", job_id), args.stage)

    write_status(
        status_file,
        phase=args.stage,
        job_id=job_id,
        stage=args.stage,
        threads=args.threads,
        budget=args.budget,
        keep_last=args.keep_last,
        bound_strategy=args.bound_strategy,
        start_bound=args.start_bound if args.start_bound >= 0 else None,
        active_words=active,
        optimum=None,
        best_value=None,
        current_bound=None,
        started_at=time.strftime("%Y-%m-%d %H:%M:%S"),
    )

    log(
        "job=%s stage=%s threads=%d budget=%ds keep_last=%d "
        "strategy=%s start_bound=%s active=%s"
        % (
            job_id,
            args.stage,
            args.threads,
            args.budget,
            args.keep_last,
            args.bound_strategy,
            args.start_bound if args.start_bound >= 0 else "default",
            active,
        )
    )

    cfg = dc_search.gen_config(R, start, start + span, active)
    model = dc_search.DCModel(cfg)
    variables, constraints = model.build()
    declared = model.declared_set()

    term_builders = {
        "o1": model._O1_terms,
        "o2": model._O2_terms,
        "o3": model._O3_terms,
    }
    terms = term_builders[args.stage](declared)
    carried = load_prior_carries(job_dir, args.stage)

    per_call = args.per_call_timeout if args.per_call_timeout > 0 else args.budget
    phase_started = time.time()

    start_bound = None if args.start_bound < 0 else args.start_bound
    value, best_out, retained_outs, carry, iterations, status = descend_retained(
        args.stage,
        terms,
        variables,
        constraints,
        carried,
        tag,
        timeout=per_call,
        budget=args.budget,
        keep_last=args.keep_last,
        strategy=args.bound_strategy,
        start_bound=start_bound,
    )

    if args.min_wait > 0:
        wait_min_elapsed(phase_started, args.min_wait)

    result = {
        "job_id": job_id,
        "stage": args.stage,
        "status": status,
        "found": best_out is not None,
        "optimum": value,
        "best_out": best_out,
        "retained_outs": retained_outs,
        "carry": carry,
        "iterations": iterations,
        "threads": args.threads,
        "budget": args.budget,
        "min_wait": args.min_wait,
        "elapsed": round(time.time() - phase_started, 2),
        "local_collision": {
            "start_step": start,
            "span": span,
            "active_words": active,
        },
        "finished_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    result_path = os.path.join(job_dir, "%s_result.json" % args.stage)
    write_json(result_path, result)

    write_status(
        status_file,
        phase="%s_done" % args.stage,
        stage=args.stage,
        stage_status=status,
        optimum=value,
        found=result["found"],
        best_out=best_out,
        retained_outs=retained_outs,
        result_file=result_path,
        finished_at=result["finished_at"],
    )

    log(
        "job=%s stage=%s done status=%s optimum=%s retained=%d elapsed=%.1fs"
        % (
            job_id,
            args.stage,
            status,
            value,
            len(retained_outs),
            result["elapsed"],
        )
    )
    return 0 if result["found"] else 1


if __name__ == "__main__":
    sys.exit(main())
