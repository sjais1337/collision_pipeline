#!/usr/bin/env python3
"""Run an LC search + parallel DC/guided-pair campaign for one round count."""

import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def log(message):
    print(
        "[%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), message),
        flush=True,
    )


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
    os.makedirs(campaign_dir, exist_ok=True)
    temp_path = path + ".tmp"
    with open(temp_path, "w") as handle:
        json.dump(payload, handle, indent=2)
    os.replace(temp_path, path)


def run_lc_search(R, campaign_dir, threads):
    lc_json = os.path.join(HERE, "results_lc", "lc_%d.json" % R)
    if os.path.exists(lc_json):
        log("reusing existing %s" % lc_json)
        return lc_json

    write_campaign_status(campaign_dir, phase="lc_search", R=R)
    log("starting lc_search.py %d" % R)
    log_path = os.path.join(campaign_dir, "lc_search.log")
    os.makedirs(campaign_dir, exist_ok=True)

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
            lc_search_status="failed",
            lc_search_exit=proc.returncode,
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
        key = (
            spec["start_step"],
            spec["span"],
            tuple(spec["active_words"]),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(spec)
    return unique


def resolve_job_count(specs, jobs_arg, reserve_vcpus, threads_per_job):
    cpus = os.cpu_count() or 4
    auto_jobs = max(1, (cpus - reserve_vcpus) // threads_per_job)
    if jobs_arg == "auto":
        return min(len(specs), auto_jobs)
    return min(len(specs), int(jobs_arg))


def launch_jobs(R, campaign_dir, specs, threads_per_job, per_call_timeout, guided_timeout):
    jobs_root = os.path.join(campaign_dir, "jobs")
    os.makedirs(jobs_root, exist_ok=True)
    processes = []

    for index, spec in enumerate(specs):
        job_id = "lc%d" % index
        job_dir = os.path.join(jobs_root, job_id)
        os.makedirs(job_dir, exist_ok=True)

        job_spec = dict(spec)
        job_spec["R"] = R
        job_spec["job_id"] = job_id
        job_spec["tag"] = "R%d_%s" % (R, job_id)
        spec_path = os.path.join(job_dir, "spec.json")
        with open(spec_path, "w") as handle:
            json.dump(job_spec, handle, indent=2)

        env = os.environ.copy()
        env["SHA2_THREADS"] = str(threads_per_job)
        log_path = os.path.join(job_dir, "job.log")
        log(
            "launching %s active=%s threads=%d"
            % (job_id, spec["active_words"], threads_per_job)
        )

        handle = open(log_path, "a")
        proc = subprocess.Popen(
            [
                sys.executable,
                "-u",
                os.path.join(HERE, "scripts", "run_lc_job.py"),
                job_dir,
                spec_path,
                str(per_call_timeout),
                str(guided_timeout),
                "0",
            ],
            cwd=HERE,
            env=env,
            stdout=handle,
            stderr=subprocess.STDOUT,
        )
        handle.close()
        processes.append((job_id, proc, job_dir))

    write_campaign_status(
        campaign_dir,
        phase="running",
        jobs_started=len(processes),
        job_ids=[item[0] for item in processes],
        started_at=time.strftime("%Y-%m-%d %H:%M:%S"),
    )
    return processes


def monitor(campaign_dir, processes, poll_seconds):
    monitor_script = os.path.join(HERE, "scripts", "monitor_campaign.py")
    while True:
        subprocess.call([sys.executable, monitor_script, campaign_dir])
        alive = []
        for job_id, proc, job_dir in processes:
            if proc.poll() is None:
                alive.append((job_id, proc, job_dir))
            else:
                log("job %s exited with code %d" % (job_id, proc.returncode))
        processes = alive
        if not processes:
            break
        write_campaign_status(
            campaign_dir,
            phase="running",
            jobs_running=len(processes),
            running_jobs=[item[0] for item in processes],
        )
        time.sleep(poll_seconds)


def main():
    parser = argparse.ArgumentParser(description="Run a parallel SHA-256 DC campaign.")
    parser.add_argument("--R", type=int, default=32, help="target round count")
    parser.add_argument(
        "--jobs",
        default="auto",
        help="number of parallel LC jobs, or 'auto' (default)",
    )
    parser.add_argument(
        "--threads-per-job",
        type=int,
        default=int(os.environ.get("SHA2_THREADS", "2")),
        help="CryptoMiniSat threads per job (default: 2)",
    )
    parser.add_argument(
        "--reserve-vcpus",
        type=int,
        default=4,
        help="vCPUs reserved for OS/controller when --jobs auto",
    )
    parser.add_argument(
        "--min-span",
        type=int,
        default=9,
        help="minimum LC span for DC feasibility",
    )
    parser.add_argument(
        "--per-call-timeout",
        type=int,
        default=7200,
        help="STP timeout per cascade call (seconds)",
    )
    parser.add_argument(
        "--guided-timeout",
        type=int,
        default=14400,
        help="guided_pair solver timeout (seconds)",
    )
    parser.add_argument(
        "--poll-seconds",
        type=int,
        default=300,
        help="monitor poll interval",
    )
    parser.add_argument(
        "--campaign-dir",
        default="",
        help="campaign output directory (default: campaigns/R<R>)",
    )
    args = parser.parse_args()

    campaign_dir = args.campaign_dir or os.path.join(
        HERE,
        "campaigns",
        "R%d" % args.R,
    )
    os.makedirs(campaign_dir, exist_ok=True)

    write_campaign_status(
        campaign_dir,
        phase="starting",
        R=args.R,
        threads_per_job=args.threads_per_job,
        reserve_vcpus=args.reserve_vcpus,
        per_call_timeout=args.per_call_timeout,
        guided_timeout=args.guided_timeout,
        started_at=time.strftime("%Y-%m-%d %H:%M:%S"),
    )

    lc_json = run_lc_search(args.R, campaign_dir, args.threads_per_job)
    specs = ranked_specs(lc_json, min_span=args.min_span)
    num_jobs = resolve_job_count(
        specs,
        args.jobs,
        args.reserve_vcpus,
        args.threads_per_job,
    )
    selected = specs[:num_jobs]

    if not selected:
        write_campaign_status(
            campaign_dir,
            phase="failed",
            reason="no_feasible_lcs",
        )
        raise SystemExit("no feasible LCs with span >= %d" % args.min_span)

    write_campaign_status(
        campaign_dir,
        phase="launching_jobs",
        num_jobs=num_jobs,
        cpus=os.cpu_count(),
        selected_lcs=[
            {
                "rank": spec.get("rank"),
                "start_step": spec["start_step"],
                "span": spec["span"],
                "active_words": spec["active_words"],
            }
            for spec in selected
        ],
    )

    log(
        "cpus=%s jobs=%d threads/job=%d selected=%d feasible=%d"
        % (
            os.cpu_count(),
            num_jobs,
            args.threads_per_job,
            len(selected),
            len(specs),
        )
    )
    for index, spec in enumerate(selected):
        log(
            "selected lc%d rank=%s start=%d span=%d active=%s"
            % (
                index,
                spec.get("rank"),
                spec["start_step"],
                spec["span"],
                spec["active_words"],
            )
        )

    processes = launch_jobs(
        args.R,
        campaign_dir,
        selected,
        args.threads_per_job,
        args.per_call_timeout,
        args.guided_timeout,
    )
    monitor(campaign_dir, processes, args.poll_seconds)
    write_campaign_status(
        campaign_dir,
        phase="finished",
        finished_at=time.strftime("%Y-%m-%d %H:%M:%S"),
    )
    subprocess.call(
        [sys.executable, os.path.join(HERE, "scripts", "monitor_campaign.py"), campaign_dir]
    )


if __name__ == "__main__":
    main()
