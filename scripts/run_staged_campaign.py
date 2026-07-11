#!/usr/bin/env python3
"""Staged O1 -> O2 -> O3 campaign (stops after O3).

Phase plan (defaults target a 48-vCPU EC2 host):
  O1: run up to 22 LCs in parallel for 2.5h each; wait at least 2h even if early.
      Keep last 3 SAT witnesses per LC. Advance LCs with O1 optimum < 30.
  O2: same 2.5h / 2h-wait / keep-3 policy on survivors. Advance LCs that found O2.
  O3: redistribute all usable vCPUs across survivors; 24h budget; keep best only.

Does not modify dc_search.py / guided_pair.py. New scripts only.
"""

import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Defaults matching the requested policy.
O12_BUDGET_S = 9000       # 2.5 hours
O12_MIN_WAIT_S = 7200     # 2 hours
O1_ADVANCE_LT = 30
O3_BUDGET_S = 86400       # 24 hours
O12_THREADS = 2
DEFAULT_JOBS = 22
RESERVE_VCPUS = 4


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


def launch_stage(jobs, stage, budget, min_wait, keep_last, threads_by_job):
    """Launch one stage for each job; threads_by_job maps job_id -> thread count."""
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
        ]
        log(
            "launch %s stage=%s threads=%d budget=%ds keep=%d"
            % (job_id, stage, threads, budget, keep_last)
        )
        handle = open(log_path, "a")
        proc = subprocess.Popen(
            cmd,
            cwd=HERE,
            env=dict(os.environ, SHA2_THREADS=str(threads)),
            stdout=handle,
            stderr=subprocess.STDOUT,
        )
        # Parent no longer needs the handle; child keeps the fd.
        handle.close()
        processes.append((job, proc, log_path))
    return processes


def wait_processes(processes, campaign_dir, stage, poll_seconds):
    alive = list(processes)
    while alive:
        write_campaign_status(
            campaign_dir,
            phase="stage_%s" % stage,
            jobs_running=[job["job_id"] for job, proc, _ in alive if proc.poll() is None],
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
    path = os.path.join(job["job_dir"], "%s_result.json" % stage)
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


def o3_thread_allocation(job_ids, reserve_vcpus):
    """Give every surviving O3 search as many threads as possible, equally."""
    cpus = os.cpu_count() or 4
    usable = max(1, cpus - reserve_vcpus)
    n = max(1, len(job_ids))
    base = max(1, usable // n)
    rem = usable - base * n
    allocation = {}
    for index, job_id in enumerate(job_ids):
        # Spread leftover cores one-by-one.
        allocation[job_id] = base + (1 if index < rem else 0)
    log(
        "O3 thread allocation: cpus=%d reserve=%d usable=%d jobs=%d -> %s"
        % (cpus, reserve_vcpus, usable, n, allocation)
    )
    return allocation


def main():
    parser = argparse.ArgumentParser(description="Staged O1/O2/O3 DC campaign.")
    parser.add_argument("--R", type=int, default=32)
    parser.add_argument("--jobs", type=int, default=DEFAULT_JOBS)
    parser.add_argument("--o12-threads", type=int, default=O12_THREADS)
    parser.add_argument("--reserve-vcpus", type=int, default=RESERVE_VCPUS)
    parser.add_argument("--o12-budget", type=int, default=O12_BUDGET_S)
    parser.add_argument("--o12-min-wait", type=int, default=O12_MIN_WAIT_S)
    parser.add_argument("--o1-advance-lt", type=int, default=O1_ADVANCE_LT)
    parser.add_argument("--o3-budget", type=int, default=O3_BUDGET_S)
    parser.add_argument("--poll-seconds", type=int, default=300)
    parser.add_argument("--min-span", type=int, default=9)
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

    write_campaign_status(
        campaign_dir,
        phase="starting",
        R=args.R,
        jobs=args.jobs,
        o12_threads=args.o12_threads,
        o12_budget=args.o12_budget,
        o12_min_wait=args.o12_min_wait,
        o1_advance_lt=args.o1_advance_lt,
        o3_budget=args.o3_budget,
        started_at=time.strftime("%Y-%m-%d %H:%M:%S"),
    )

    lc_json = run_lc_search(args.R, campaign_dir, args.o12_threads)
    specs = ranked_specs(lc_json, min_span=args.min_span)[: args.jobs]
    if not specs:
        raise SystemExit("no feasible LCs found")

    jobs = prepare_jobs(campaign_dir, args.R, specs)
    write_json(
        os.path.join(campaign_dir, "selected_lcs.json"),
        [job["spec"] for job in jobs],
    )
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
    write_campaign_status(campaign_dir, phase="o1", n_jobs=len(jobs))
    threads = {job["job_id"]: args.o12_threads for job in jobs}
    procs = launch_stage(
        jobs,
        "o1",
        budget=args.o12_budget,
        min_wait=args.o12_min_wait,
        keep_last=3,
        threads_by_job=threads,
    )
    wait_processes(procs, campaign_dir, "o1", args.poll_seconds)
    o1_rows = summarize_stage(campaign_dir, jobs, "o1")

    o2_jobs = []
    for job, row in zip(jobs, o1_rows):
        optimum = row.get("optimum")
        if row.get("found") and optimum is not None and optimum < args.o1_advance_lt:
            o2_jobs.append(job)
            log(
                "O1 advance %s optimum=%s (< %d)"
                % (job["job_id"], optimum, args.o1_advance_lt)
            )
        else:
            log(
                "O1 drop %s found=%s optimum=%s"
                % (job["job_id"], row.get("found"), optimum)
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
    write_campaign_status(campaign_dir, phase="o2", n_jobs=len(o2_jobs))
    threads = {job["job_id"]: args.o12_threads for job in o2_jobs}
    procs = launch_stage(
        o2_jobs,
        "o2",
        budget=args.o12_budget,
        min_wait=args.o12_min_wait,
        keep_last=3,
        threads_by_job=threads,
    )
    wait_processes(procs, campaign_dir, "o2", args.poll_seconds)
    o2_rows = summarize_stage(campaign_dir, o2_jobs, "o2")

    o3_jobs = []
    for job, row in zip(o2_jobs, o2_rows):
        if row.get("found") and row.get("optimum") is not None:
            o3_jobs.append(job)
            log("O2 advance %s optimum=%s" % (job["job_id"], row.get("optimum")))
        else:
            log("O2 drop %s found=%s" % (job["job_id"], row.get("found")))

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
    allocation = o3_thread_allocation(
        [job["job_id"] for job in o3_jobs],
        args.reserve_vcpus,
    )
    write_campaign_status(
        campaign_dir,
        phase="o3",
        n_jobs=len(o3_jobs),
        o3_threads=allocation,
    )
    procs = launch_stage(
        o3_jobs,
        "o3",
        budget=args.o3_budget,
        min_wait=0,
        keep_last=1,
        threads_by_job=allocation,
    )
    wait_processes(procs, campaign_dir, "o3", args.poll_seconds)
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
