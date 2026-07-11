#!/usr/bin/env python3
"""Staged O1 -> O2 -> O3 campaign (stops after O3).

Phase plan (defaults target a 48-vCPU EC2 host):
  O1: up to 22 LCs x 2 threads, 2.5h budget, 2h min-wait, keep last 3.
      O1 is Hamming weight of the highest-index active message words.
      Advance if O1 optimum < 30, then keep the best 8 (lowest O1) for O2.
  O2: those 8 get equal max thread split (~4 on a 48-vCPU host), 2.5h / 2h-wait.
      O2 is total message-difference Hamming weight H(dW). Advance if O2 < 15.
  O3: survivors get equal max thread split, 24h budget, keep best only.

Resume with --start-from o2|o3 when prior stage result JSONs exist.
Does not modify dc_search.py / guided_pair.py.
"""

import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

O12_BUDGET_S = 9000
O12_MIN_WAIT_S = 7200
O1_ADVANCE_LT = 30
O2_ADVANCE_LT = 15
O2_MAX_JOBS = 8          # among O1 survivors, keep the best K (lowest O1)
O3_BUDGET_S = 86400
O12_THREADS = 2
DEFAULT_JOBS = 22
RESERVE_VCPUS = 4
STAGE_ORDER = ("o1", "o2", "o3")


def log(message):
    print(
        "[%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), message),
        flush=True,
    )


def write_json(path, payload):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    temp = path + ".tmp"
    with open(temp, "w") as handle:
        json.dump(payload, handle, indent=2, default=str)
    os.replace(temp, path)


def write_campaign_status(campaign_dir, **fields):
    path = os.path.join(campaign_dir, "status.json")
    payload = {}
    if os.path.exists(path):
        try:
            with open(path) as handle:
                payload = json.load(handle)
        except (IOError, ValueError):
            payload = {}
    payload.update(fields)
    payload["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    write_json(path, payload)


def run_lc_search(R, campaign_dir, threads):
    lc_json = os.path.join(HERE, "results_lc", "lc_%d.json" % R)
    if os.path.exists(lc_json):
        log("reusing existing %s" % lc_json)
        return lc_json

    write_campaign_status(campaign_dir, phase="lc_search", R=R)
    log_path = os.path.join(campaign_dir, "lc_search.log")
    os.makedirs(campaign_dir, exist_ok=True)
    log("starting lc_search.py %d" % R)
    with open(log_path, "w") as handle:
        proc = subprocess.run(
            [sys.executable, "-u", os.path.join(HERE, "lc_search.py"), str(R)],
            cwd=HERE,
            env=dict(os.environ, SHA2_THREADS=str(threads)),
            stdout=handle,
            stderr=subprocess.STDOUT,
        )
    if proc.returncode != 0 or not os.path.exists(lc_json):
        write_campaign_status(
            campaign_dir,
            phase="failed",
            reason="lc_search_failed",
            exit_code=proc.returncode,
        )
        raise SystemExit("lc_search failed")
    write_campaign_status(campaign_dir, phase="lc_search_done", lc_search_status="ok")
    return lc_json


def ranked_specs(lc_json, min_span=9):
    data = json.load(open(lc_json))
    specs = [dict(data["best"], source="lc-search-best", rank=0)]
    for index, candidate in enumerate(data.get("alternates", []), start=1):
        specs.append(dict(candidate, source="lc-search-alt", rank=index))

    unique = []
    seen = set()
    for spec in specs:
        if spec["span"] < min_span:
            continue
        key = (spec["start_step"], spec["span"], tuple(spec["active_words"]))
        if key in seen:
            continue
        seen.add(key)
        unique.append(spec)
    return unique


def prepare_jobs(campaign_dir, R, specs):
    jobs_root = os.path.join(campaign_dir, "jobs")
    os.makedirs(jobs_root, exist_ok=True)
    jobs = []
    for index, spec in enumerate(specs):
        job_id = "lc%d" % index
        job_dir = os.path.join(jobs_root, job_id)
        os.makedirs(job_dir, exist_ok=True)
        job_spec = dict(spec)
        job_spec["R"] = R
        job_spec["job_id"] = job_id
        job_spec["tag"] = "R%d_%s" % (R, job_id)
        spec_path = os.path.join(job_dir, "spec.json")
        write_json(spec_path, job_spec)
        jobs.append({
            "job_id": job_id,
            "job_dir": job_dir,
            "spec_path": spec_path,
            "spec": job_spec,
        })
    return jobs


def load_jobs_from_campaign(campaign_dir):
    """Rebuild job list from a previous run's selected_lcs.json / job dirs."""
    selected_path = os.path.join(campaign_dir, "selected_lcs.json")
    jobs_root = os.path.join(campaign_dir, "jobs")
    if not os.path.exists(selected_path):
        raise SystemExit(
            "cannot resume: missing %s (start a fresh campaign first)"
            % selected_path
        )

    selected = json.load(open(selected_path))
    jobs = []
    for index, spec in enumerate(selected):
        job_id = spec.get("job_id", "lc%d" % index)
        job_dir = os.path.join(jobs_root, job_id)
        spec_path = os.path.join(job_dir, "spec.json")
        if not os.path.exists(spec_path):
            raise SystemExit("cannot resume: missing %s" % spec_path)
        jobs.append({
            "job_id": job_id,
            "job_dir": job_dir,
            "spec_path": spec_path,
            "spec": json.load(open(spec_path)),
        })
    return jobs


def stage_result_path(job, stage):
    return os.path.join(job["job_dir"], "%s_result.json" % stage)


def has_stage_result(job, stage):
    return os.path.exists(stage_result_path(job, stage))


def launch_stage(
    jobs,
    stage,
    budget,
    min_wait,
    keep_last,
    threads_by_job,
    bound_strategy="linear",
    start_bound=None,
):
    processes = []
    worker = os.path.join(HERE, "scripts", "run_staged_job.py")

    for job in jobs:
        job_id = job["job_id"]
        threads = int(threads_by_job[job_id])
        log_path = os.path.join(job["job_dir"], "%s.log" % stage)
        cmd = [
            sys.executable,
            "-u",
            worker,
            "--job-dir", job["job_dir"],
            "--spec", job["spec_path"],
            "--stage", stage,
            "--budget", str(budget),
            "--min-wait", str(min_wait),
            "--keep-last", str(keep_last),
            "--threads", str(threads),
            "--bound-strategy", bound_strategy,
        ]
        if start_bound is not None:
            cmd += ["--start-bound", str(start_bound)]
        log(
            "launch %s stage=%s threads=%d budget=%ds keep=%d strategy=%s start_bound=%s"
            % (
                job_id,
                stage,
                threads,
                budget,
                keep_last,
                bound_strategy,
                start_bound if start_bound is not None else "default",
            )
        )
        handle = open(log_path, "a")
        proc = subprocess.Popen(
            cmd,
            cwd=HERE,
            env=dict(os.environ, SHA2_THREADS=str(threads)),
            stdout=handle,
            stderr=subprocess.STDOUT,
        )
        handle.close()
        processes.append((job, proc, log_path))
    return processes


def wait_processes(processes, campaign_dir, stage, poll_seconds):
    alive = list(processes)
    while alive:
        write_campaign_status(
            campaign_dir,
            phase="stage_%s" % stage,
            jobs_running=[
                job["job_id"] for job, proc, _ in alive if proc.poll() is None
            ],
        )
        still = []
        for job, proc, log_path in alive:
            code = proc.poll()
            if code is None:
                still.append((job, proc, log_path))
            else:
                log(
                    "job %s stage=%s exited code=%d log=%s"
                    % (job["job_id"], stage, code, log_path)
                )
        alive = still
        if alive:
            time.sleep(poll_seconds)


def load_stage_result(job, stage):
    path = stage_result_path(job, stage)
    if not os.path.exists(path):
        return None
    return json.load(open(path))


def summarize_stage(campaign_dir, jobs, stage):
    rows = []
    for job in jobs:
        result = load_stage_result(job, stage) or {
            "job_id": job["job_id"],
            "stage": stage,
            "found": False,
            "optimum": None,
            "status": "missing_result",
        }
        rows.append(result)
    path = os.path.join(campaign_dir, "%s_summary.json" % stage)
    write_json(path, {"stage": stage, "results": rows})
    log("wrote %s (%d jobs)" % (path, len(rows)))
    return rows


def allocate_threads(job_ids, reserve_vcpus, label):
    """Split usable vCPUs evenly so each search gets as many threads as possible."""
    cpus = os.cpu_count() or 4
    usable = max(1, cpus - reserve_vcpus)
    n = max(1, len(job_ids))
    base = max(1, usable // n)
    rem = usable - base * n
    allocation = {}
    for index, job_id in enumerate(job_ids):
        allocation[job_id] = base + (1 if index < rem else 0)
    log(
        "%s thread allocation: cpus=%d reserve=%d usable=%d jobs=%d -> %s"
        % (label, cpus, reserve_vcpus, usable, n, allocation)
    )
    return allocation


def filter_advance(jobs, rows, threshold, stage_label, top_k=None):
    """Keep jobs with optimum < threshold; optionally only the best ``top_k``."""
    eligible = []
    for job, row in zip(jobs, rows):
        optimum = row.get("optimum")
        if row.get("found") and optimum is not None and optimum < threshold:
            eligible.append((optimum, job, row))
            log(
                "%s eligible %s optimum=%s (< %d)"
                % (stage_label, job["job_id"], optimum, threshold)
            )
        else:
            log(
                "%s drop %s found=%s optimum=%s"
                % (stage_label, job["job_id"], row.get("found"), optimum)
            )

    eligible.sort(key=lambda item: (item[0], item[1]["job_id"]))
    if top_k is not None and len(eligible) > top_k:
        log(
            "%s keeping best %d of %d eligible (lowest optima)"
            % (stage_label, top_k, len(eligible))
        )
        for optimum, job, _ in eligible[top_k:]:
            log(
                "%s skip %s optimum=%s (outside top %d)"
                % (stage_label, job["job_id"], optimum, top_k)
            )
        eligible = eligible[:top_k]

    advanced = []
    for optimum, job, _ in eligible:
        advanced.append(job)
        log("%s advance %s optimum=%s" % (stage_label, job["job_id"], optimum))
    return advanced


def main():
    parser = argparse.ArgumentParser(description="Staged O1/O2/O3 DC campaign.")
    parser.add_argument("--R", type=int, default=32)
    parser.add_argument("--jobs", type=int, default=DEFAULT_JOBS)
    parser.add_argument("--o12-threads", type=int, default=O12_THREADS)
    parser.add_argument("--reserve-vcpus", type=int, default=RESERVE_VCPUS)
    parser.add_argument("--o12-budget", type=int, default=O12_BUDGET_S)
    parser.add_argument("--o12-min-wait", type=int, default=O12_MIN_WAIT_S)
    parser.add_argument("--o1-advance-lt", type=int, default=O1_ADVANCE_LT)
    parser.add_argument("--o2-advance-lt", type=int, default=O2_ADVANCE_LT)
    parser.add_argument(
        "--o2-max-jobs",
        type=int,
        default=O2_MAX_JOBS,
        help="among O1 survivors, keep only the best K (lowest O1) for O2",
    )
    parser.add_argument("--o3-budget", type=int, default=O3_BUDGET_S)
    parser.add_argument(
        "--o3-start-bound",
        type=int,
        default=150,
        help="O3 binary-search initial probe (default 150)",
    )
    parser.add_argument("--poll-seconds", type=int, default=300)
    parser.add_argument("--min-span", type=int, default=9)
    parser.add_argument(
        "--start-from",
        choices=STAGE_ORDER,
        default="o1",
        help="skip earlier stages and reuse their on-disk results",
    )
    parser.add_argument(
        "--campaign-dir",
        default="",
        help="default: campaigns/staged_R<R>",
    )
    args = parser.parse_args()

    campaign_dir = args.campaign_dir or os.path.join(
        HERE,
        "campaigns",
        "staged_R%d" % args.R,
    )
    os.makedirs(campaign_dir, exist_ok=True)
    start_from = args.start_from

    write_campaign_status(
        campaign_dir,
        phase="starting",
        R=args.R,
        jobs=args.jobs,
        start_from=start_from,
        o12_threads=args.o12_threads,
        o12_budget=args.o12_budget,
        o12_min_wait=args.o12_min_wait,
        o1_advance_lt=args.o1_advance_lt,
        o2_advance_lt=args.o2_advance_lt,
        o2_max_jobs=args.o2_max_jobs,
        o3_budget=args.o3_budget,
        o3_start_bound=args.o3_start_bound,
        started_at=time.strftime("%Y-%m-%d %H:%M:%S"),
    )

    if start_from == "o1":
        lc_json = run_lc_search(args.R, campaign_dir, args.o12_threads)
        specs = ranked_specs(lc_json, min_span=args.min_span)[: args.jobs]
        if not specs:
            raise SystemExit("no feasible LCs found")
        jobs = prepare_jobs(campaign_dir, args.R, specs)
        write_json(
            os.path.join(campaign_dir, "selected_lcs.json"),
            [job["spec"] for job in jobs],
        )
    else:
        log("resuming from %s using existing campaign artifacts" % start_from)
        jobs = load_jobs_from_campaign(campaign_dir)

    for job in jobs:
        log(
            "selected %s start=%s span=%s active=%s"
            % (
                job["job_id"],
                job["spec"]["start_step"],
                job["spec"]["span"],
                job["spec"]["active_words"],
            )
        )

    # ---- O1 ----
    if start_from == "o1":
        pending = [job for job in jobs if not has_stage_result(job, "o1")]
        done = [job for job in jobs if has_stage_result(job, "o1")]
        if done:
            log("reusing %d existing O1 results; launching %d remaining" % (
                len(done),
                len(pending),
            ))
        if pending:
            write_campaign_status(campaign_dir, phase="o1", n_jobs=len(pending))
            threads = {job["job_id"]: args.o12_threads for job in pending}
            procs = launch_stage(
                pending,
                "o1",
                budget=args.o12_budget,
                min_wait=args.o12_min_wait,
                keep_last=3,
                threads_by_job=threads,
            )
            wait_processes(procs, campaign_dir, "o1", args.poll_seconds)
        o1_rows = summarize_stage(campaign_dir, jobs, "o1")
    else:
        log("skipping O1 launch (--start-from=%s)" % start_from)
        o1_rows = summarize_stage(campaign_dir, jobs, "o1")

    o2_jobs = filter_advance(
        jobs,
        o1_rows,
        args.o1_advance_lt,
        "O1",
        top_k=args.o2_max_jobs,
    )
    write_campaign_status(
        campaign_dir,
        phase="o1_done",
        o1_advanced=[job["job_id"] for job in o2_jobs],
        o1_advanced_count=len(o2_jobs),
    )
    if not o2_jobs:
        write_campaign_status(campaign_dir, phase="finished", reason="no_o1_survivors")
        log("no LCs advanced past O1; done")
        return 0

    # ---- O2 ----
    if start_from in ("o1", "o2"):
        pending = [job for job in o2_jobs if not has_stage_result(job, "o2")]
        done = [job for job in o2_jobs if has_stage_result(job, "o2")]
        if done and start_from == "o2":
            log("reusing %d existing O2 results; launching %d remaining" % (
                len(done),
                len(pending),
            ))
        if pending:
            allocation = allocate_threads(
                [job["job_id"] for job in pending],
                args.reserve_vcpus,
                "O2",
            )
            write_campaign_status(
                campaign_dir,
                phase="o2",
                n_jobs=len(pending),
                o2_threads=allocation,
            )
            procs = launch_stage(
                pending,
                "o2",
                budget=args.o12_budget,
                min_wait=args.o12_min_wait,
                keep_last=3,
                threads_by_job=allocation,
            )
            wait_processes(procs, campaign_dir, "o2", args.poll_seconds)
        o2_rows = summarize_stage(campaign_dir, o2_jobs, "o2")
    else:
        log("skipping O2 launch (--start-from=%s)" % start_from)
        o2_rows = summarize_stage(campaign_dir, o2_jobs, "o2")

    o3_jobs = filter_advance(o2_jobs, o2_rows, args.o2_advance_lt, "O2")
    write_campaign_status(
        campaign_dir,
        phase="o2_done",
        o2_advanced=[job["job_id"] for job in o3_jobs],
        o2_advanced_count=len(o3_jobs),
    )
    if not o3_jobs:
        write_campaign_status(campaign_dir, phase="finished", reason="no_o2_survivors")
        log("no LCs advanced past O2; done")
        return 0

    # ---- O3 ----
    # Clear incomplete O3 results so a restart actually relaunches.
    pending = [job for job in o3_jobs if not has_stage_result(job, "o3")]
    if pending:
        allocation = allocate_threads(
            [job["job_id"] for job in pending],
            args.reserve_vcpus,
            "O3",
        )
        write_campaign_status(
            campaign_dir,
            phase="o3",
            n_jobs=len(pending),
            o3_threads=allocation,
            o3_bound_strategy="binary",
            o3_start_bound=args.o3_start_bound,
        )
        procs = launch_stage(
            pending,
            "o3",
            budget=args.o3_budget,
            min_wait=0,
            keep_last=1,
            threads_by_job=allocation,
            bound_strategy="binary",
            start_bound=args.o3_start_bound,
        )
        wait_processes(procs, campaign_dir, "o3", args.poll_seconds)
    else:
        log("all O3 results already present; nothing to launch")
    summarize_stage(campaign_dir, o3_jobs, "o3")

    write_campaign_status(
        campaign_dir,
        phase="finished",
        finished_at=time.strftime("%Y-%m-%d %H:%M:%S"),
    )
    log("staged campaign finished (O1->O2->O3 only)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
