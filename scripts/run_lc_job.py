#!/usr/bin/env python3
"""Run the full LC pipeline for one candidate: DC cascade then guided pair."""

import json
import os
import subprocess
import sys
import time

# Set job-specific paths before importing dc_search (WORK is resolved lazily).
if len(sys.argv) >= 3:
    _job_dir = sys.argv[1]
    os.environ.setdefault(
        "SHA2_WORK_DIR",
        os.path.join(_job_dir, "work"),
    )
    os.environ.setdefault(
        "SHA2_STATUS_FILE",
        os.path.join(_job_dir, "status.json"),
    )

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import dc_search  # noqa: E402
import parse_dc  # noqa: E402


def log(message):
    print(
        "[%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), message),
        flush=True,
    )


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
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp_path = path + ".tmp"
    with open(temp_path, "w") as handle:
        json.dump(payload, handle, indent=2)
    os.replace(temp_path, path)


def main():
    if len(sys.argv) < 3:
        print(
            "usage: run_lc_job.py <job_dir> <spec_json> "
            "[per_call_timeout_s] [guided_timeout_s] [o5_value 0|1]",
            file=sys.stderr,
        )
        return 2

    job_dir = sys.argv[1]
    spec = json.load(open(sys.argv[2]))
    per_call_timeout = int(sys.argv[3]) if len(sys.argv) > 3 else 3600
    guided_timeout = int(sys.argv[4]) if len(sys.argv) > 4 else 7200
    o5_value = bool(int(sys.argv[5])) if len(sys.argv) > 5 else False

    R = spec["R"]
    start = spec["start_step"]
    span = spec["span"]
    active = spec["active_words"]
    job_id = spec.get("job_id", os.path.basename(job_dir))
    tag = spec.get("tag", job_id)

    status_file = os.path.join(job_dir, "status.json")
    work_dir = os.path.join(job_dir, "work")
    os.makedirs(work_dir, exist_ok=True)

    os.environ["SHA2_WORK_DIR"] = work_dir
    os.environ["SHA2_STATUS_FILE"] = status_file
    os.environ["SHA2_JOB_TAG"] = tag

    write_status(
        status_file,
        phase="starting",
        job_id=job_id,
        tag=tag,
        R=R,
        local_collision=active,
        start_step=start,
        span=span,
        threads=os.environ.get("SHA2_THREADS"),
        started_at=time.strftime("%Y-%m-%d %H:%M:%S"),
    )

    log(
        "job=%s R=%d start=%d span=%d active=%s threads=%s"
        % (job_id, R, start, span, active, os.environ.get("SHA2_THREADS"))
    )

    cfg = dc_search.gen_config(R, start, start + span, active)
    write_status(status_file, phase="dc_search", tag=tag)

    cascade = dc_search.solve_cascade(
        cfg,
        tag,
        timeout=per_call_timeout,
        o5_value=o5_value,
        budget=None,
    )
    cascade_path = os.path.join(job_dir, "cascade.json")
    with open(cascade_path, "w") as handle:
        json.dump(cascade, handle, indent=2, default=str)

    out_file = cascade.get("out_file")
    optima = cascade.get("stage_optima", {})
    write_status(
        status_file,
        phase="dc_search_done",
        cascade_status=cascade.get("status"),
        found=cascade.get("found"),
        stage_optima=optima,
        out_file=out_file,
        cascade_file=cascade_path,
    )

    if not out_file:
        write_status(status_file, phase="failed", reason="no_dc")
        log("job=%s failed: no DC produced" % job_id)
        return 1

    parsed = parse_dc.parse(
        out_file,
        R,
        start=start,
        end=start + span,
        stored_o3=optima.get("o3"),
    )
    report_path = os.path.join(job_dir, "dc_report.txt")
    with open(report_path, "w") as handle:
        handle.write(parse_dc.pretty(parsed))

    result_file = os.path.join(job_dir, "collision.json")
    os.environ["SHA2_RESULT_FILE"] = result_file
    write_status(status_file, phase="guided_pair", dc_out=out_file)

    guided_cmd = [
        sys.executable,
        "-u",
        os.path.join(HERE, "guided_pair.py"),
        out_file,
        str(R),
        str(guided_timeout),
        os.environ.get("SHA2_THREADS", "2"),
    ]
    log("job=%s launching guided_pair: %s" % (job_id, " ".join(guided_cmd[-4:])))
    guided_log = open(os.path.join(job_dir, "guided_pair.log"), "w")
    proc = subprocess.run(
        guided_cmd,
        cwd=HERE,
        env=os.environ.copy(),
        stdout=guided_log,
        stderr=subprocess.STDOUT,
    )
    guided_log.close()

    collision = {}
    if os.path.exists(result_file):
        collision = json.load(open(result_file))

    final_phase = "done" if proc.returncode == 0 else "done_unverified"
    if proc.returncode == 3:
        final_phase = "failed"
        reason = "guided_unsat"
    elif proc.returncode == 2:
        final_phase = "failed"
        reason = "guided_timeout"
    else:
        reason = None

    write_status(
        status_file,
        phase=final_phase,
        guided_exit_code=proc.returncode,
        verified=collision.get("verified"),
        collision_verified=collision.get("collision_verified"),
        signed_dc_verified=collision.get("signed_dc_verified"),
        result_file=result_file,
        reason=reason,
        finished_at=time.strftime("%Y-%m-%d %H:%M:%S"),
    )
    log(
        "job=%s finished phase=%s exit=%d verified=%s"
        % (
            job_id,
            final_phase,
            proc.returncode,
            collision.get("verified"),
        )
    )
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
