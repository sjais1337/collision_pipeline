#!/usr/bin/env python3
"""Print a live summary for a staged / R32 campaign directory.

Per-job fields:
  trying=N   — BVLE ceiling of the active / last-started STP call
  best=N     — lowest SAT objective found in the CURRENT stage so far
  optimum=N  — final answer (only when phase ends with *_done)
"""

import json
import os
import sys
import time


def load_json(path):
    try:
        with open(path) as handle:
            return json.load(handle)
    except (IOError, ValueError):
        return {}


def job_line(job_dir, marker=""):
    status_path = os.path.join(job_dir, "status.json")
    status = load_json(status_path)
    name = os.path.basename(job_dir)
    if not status:
        return "  %s%s: (no status yet)" % (marker, name)

    phase = status.get("phase", "?")
    parts = ["%s%s" % (marker, name), "phase=%s" % phase]

    strategy = status.get("strategy") or status.get("bound_strategy")
    if strategy:
        parts.append("strategy=%s" % strategy)
    if status.get("binary_phase"):
        parts.append("bin=%s" % status["binary_phase"])
        if status.get("binary_lo") is not None and status.get("binary_hi") is not None:
            parts.append("range=[%s,%s]" % (status["binary_lo"], status["binary_hi"]))

    # Prefer explicit vocabulary; fall back to legacy keys.
    trying = status.get("trying_bound")
    if trying is None:
        trying = status.get("current_bound")
    best = status.get("best_found")
    if best is None:
        best = status.get("best_value")

    done = phase.endswith("_done")
    if done:
        opt = status.get("optimum")
        if opt is None:
            opt = best
        if opt is not None:
            parts.append("optimum=%s" % opt)
    else:
        # While running: never show a stale prior-stage "optimum".
        if trying is not None:
            parts.append("trying=%s" % trying)
        if best is not None:
            parts.append("best=%s" % best)

    if status.get("threads") is not None:
        parts.append("threads=%s" % status["threads"])
    parts.append("updated=%s" % status.get("updated_at", "?"))
    return "  " + " | ".join(parts)


def main():
    campaign_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "campaigns",
        "R32",
    )
    show_all = "--all" in sys.argv[2:]

    campaign_status = load_json(os.path.join(campaign_dir, "status.json"))
    print("=== campaign %s ===" % campaign_dir)
    print("updated: %s" % time.strftime("%Y-%m-%d %H:%M:%S"))
    if campaign_status:
        for key in (
            "phase",
            "R",
            "start_from",
            "o1_advanced_count",
            "o2_advanced_count",
            "n_jobs",
            "o3_bound_strategy",
            "o3_start_bound",
            "started_at",
        ):
            if key in campaign_status:
                print("%s: %s" % (key, campaign_status[key]))
        if campaign_status.get("o1_advanced"):
            print("o1_advanced: %s" % ", ".join(campaign_status["o1_advanced"]))
        if campaign_status.get("o2_advanced"):
            print("o2_advanced: %s" % ", ".join(campaign_status["o2_advanced"]))
        if campaign_status.get("jobs_running"):
            print("jobs_running: %s" % ", ".join(campaign_status["jobs_running"]))
        if campaign_status.get("o2_threads"):
            print("o2_threads: %s" % campaign_status["o2_threads"])
        if campaign_status.get("o3_threads"):
            print("o3_threads: %s" % campaign_status["o3_threads"])

    active = set()
    for key in ("jobs_running", "o1_advanced", "o2_advanced"):
        for job_id in campaign_status.get(key) or []:
            active.add(job_id)

    now = time.time()
    jobs_root = os.path.join(campaign_dir, "jobs")
    if not os.path.isdir(jobs_root):
        print("  (no jobs directory yet)")
        return

    names = sorted(
        name for name in os.listdir(jobs_root)
        if os.path.isdir(os.path.join(jobs_root, name))
    )

    if not active:
        for name in names:
            status = load_json(os.path.join(jobs_root, name, "status.json"))
            updated = status.get("updated_at")
            if not updated:
                continue
            try:
                stamp = time.mktime(time.strptime(updated, "%Y-%m-%d %H:%M:%S"))
            except ValueError:
                continue
            if now - stamp < 600:
                active.add(name)

    print("--- active / selected (%d) ---" % len(active))
    print("  (trying=BVLE ceiling, best=lowest SAT this stage, optimum=final only)")
    for name in names:
        if name in active:
            print(job_line(os.path.join(jobs_root, name)))

    idle = [name for name in names if name not in active]
    if idle:
        print("--- idle / not in current stage (%d) ---" % len(idle))
        if show_all:
            for name in idle:
                print(job_line(os.path.join(jobs_root, name), marker="(idle) "))
        else:
            print("  %s" % ", ".join(idle))
            print("  (pass --all to show their last status; often stale)")

    lc_json = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "results_lc",
        "lc_%s.json" % campaign_status.get("R", 32),
    )
    if os.path.exists(lc_json):
        data = load_json(lc_json)
        best = data.get("best", {})
        print("LC best: start=%s span=%s active=%s" % (
            best.get("start_step"),
            best.get("span"),
            best.get("active_words"),
        ))


if __name__ == "__main__":
    main()
