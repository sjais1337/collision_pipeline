#!/usr/bin/env python3
"""Launch the R=32 campaign: LC search, then 3 parallel DC+pair jobs."""

import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAMPAIGN_DIR = os.path.join(HERE, "campaigns", "R32")
R = 32
NUM_JOBS = 3
THREADS_PER_JOB = 2
PER_CALL_TIMEOUT = 7200
GUIDED_TIMEOUT = 14400


def log(message):
    print(
        "[%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), message),
        flush=True,
    )


def write_campaign_status(**fields):
    path = os.path.join(CAMPAIGN_DIR, "status.json")
    payload = {}
    if os.path.exists(path):
        try:
            with open(path) as handle:
                payload = json.load(handle)
        except (IOError, ValueError):
            payload = {}
    payload.update(fields)
    payload["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    os.makedirs(CAMPAIGN_DIR, exist_ok=True)
    temp_path = path + ".tmp"
    with open(temp_path, "w") as handle:
        json.dump(payload, handle, indent=2)
    os.replace(temp_path, path)


def run_lc_search():
    lc_json = os.path.join(HERE, "results_lc", "lc_%d.json" % R)
    if os.path.exists(lc_json):
        log("reusing existing %s" % lc_json)
        return lc_json

    write_campaign_status(phase="lc_search", R=R)
    log("starting lc_search.py %d" % R)
    log_path = os.path.join(CAMPAIGN_DIR, "lc_search.log")
    os.makedirs(CAMPAIGN_DIR, exist_ok=True)

    with open(log_path, "w") as handle:
        proc = subprocess.run(
            [sys.executable, "-u", os.path.join(HERE, "lc_search.py"), str(R)],
            cwd=HERE,
            env=dict(os.environ, SHA2_THREADS=str(THREADS_PER_JOB)),
            stdout=handle,
            stderr=subprocess.STDOUT,
        )

    if proc.returncode != 0 or not os.path.exists(lc_json):
        write_campaign_status(
            phase="failed",
            lc_search_status="failed",
            lc_search_exit=proc.returncode,
        )
        raise SystemExit("lc_search failed")

    write_campaign_status(phase="lc_search_done", lc_search_status="ok")
    return lc_json


def top_specs(lc_json, count):
    data = json.load(open(lc_json))
    specs = [dict(data["best"], source="lc-search-best", rank=0)]
    for index, candidate in enumerate(data.get("alternates", []), start=1):
        specs.append(dict(candidate, source="lc-search-alt", rank=index))

    unique = []
    seen = set()
    for spec in specs:
        key = (
            spec["start_step"],
            spec["span"],
            tuple(spec["active_words"]),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(spec)
        if len(unique) >= count:
            break
    return unique


def launch_jobs(specs):
    jobs_root = os.path.join(CAMPAIGN_DIR, "jobs")
    os.makedirs(jobs_root, exist_ok=True)
    processes = []

    for index, spec in enumerate(specs):
        job_id = "lc%d" % index
        job_dir = os.path.join(jobs_root, job_id)
        os.makedirs(job_dir, exist_ok=True)

        job_spec = dict(spec)
        job_spec["R"] = R
        job_spec["job_id"] = job_id
        job_spec["tag"] = "R32_%s" % job_id
        spec_path = os.path.join(job_dir, "spec.json")
        with open(spec_path, "w") as handle:
            json.dump(job_spec, handle, indent=2)

        env = os.environ.copy()
        env["SHA2_THREADS"] = str(THREADS_PER_JOB)
        log_path = os.path.join(job_dir, "job.log")
        log(
            "launching %s active=%s threads=%d"
            % (job_id, spec["active_words"], THREADS_PER_JOB)
        )

        handle = open(log_path, "a")
        proc = subprocess.Popen(
            [
                sys.executable,
                "-u",
                os.path.join(HERE, "scripts", "run_lc_job.py"),
                job_dir,
                spec_path,
                str(PER_CALL_TIMEOUT),
                str(GUIDED_TIMEOUT),
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
        phase="running",
        jobs_started=len(processes),
        job_ids=[item[0] for item in processes],
        started_at=time.strftime("%Y-%m-%d %H:%M:%S"),
    )
    return processes


def monitor(processes):
    monitor_script = os.path.join(HERE, "scripts", "monitor_campaign.py")
    while True:
        subprocess.call([sys.executable, monitor_script, CAMPAIGN_DIR])
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
            phase="running",
            jobs_running=len(processes),
            running_jobs=[item[0] for item in processes],
        )
        time.sleep(300)


def main():
    os.makedirs(CAMPAIGN_DIR, exist_ok=True)
    write_campaign_status(
        phase="starting",
        R=R,
        threads_per_job=THREADS_PER_JOB,
        num_jobs=NUM_JOBS,
        per_call_timeout=PER_CALL_TIMEOUT,
        guided_timeout=GUIDED_TIMEOUT,
        started_at=time.strftime("%Y-%m-%d %H:%M:%S"),
    )

    lc_json = run_lc_search()
    specs = top_specs(lc_json, NUM_JOBS)
    if len(specs) < NUM_JOBS:
        write_campaign_status(
            phase="failed",
            reason="not_enough_lcs",
            found=len(specs),
        )
        raise SystemExit("need %d LCs, found %d" % (NUM_JOBS, len(specs)))

    write_campaign_status(
        phase="launching_jobs",
        selected_lcs=[
            {
                "rank": spec.get("rank"),
                "start_step": spec["start_step"],
                "span": spec["span"],
                "active_words": spec["active_words"],
            }
            for spec in specs
        ],
    )

    for index, spec in enumerate(specs):
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

    processes = launch_jobs(specs)
    monitor(processes)
    write_campaign_status(
        phase="finished",
        finished_at=time.strftime("%Y-%m-%d %H:%M:%S"),
    )
    subprocess.call(
        [sys.executable, os.path.join(HERE, "scripts", "monitor_campaign.py"), CAMPAIGN_DIR]
    )


if __name__ == "__main__":
    main()
