#!/usr/bin/env python3
"""Print a live summary for an R32 (or generic) campaign directory."""

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


def job_line(job_dir):
    status_path = os.path.join(job_dir, "status.json")
    status = load_json(status_path)
    if not status:
        return "  %s: (no status yet)" % os.path.basename(job_dir)

    parts = [
        os.path.basename(job_dir),
        "phase=%s" % status.get("phase", "?"),
    ]
    if status.get("current_stage"):
        parts.append("stage=%s" % status["current_stage"])
    if status.get("current_bound") is not None:
        parts.append("bound=%s" % status["current_bound"])
    if status.get("stage_optima"):
        parts.append("O3=%s" % status["stage_optima"].get("o3"))
    if status.get("verified") is not None:
        parts.append("verified=%s" % status["verified"])
    parts.append("updated=%s" % status.get("updated_at", "?"))
    return "  " + " | ".join(parts)


def main():
    campaign_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "campaigns",
        "R32",
    )

    campaign_status = load_json(os.path.join(campaign_dir, "status.json"))
    print("=== campaign %s ===" % campaign_dir)
    print("updated: %s" % time.strftime("%Y-%m-%d %H:%M:%S"))
    if campaign_status:
        for key in (
            "phase",
            "R",
            "lc_search_status",
            "jobs_started",
            "started_at",
        ):
            if key in campaign_status:
                print("%s: %s" % (key, campaign_status[key]))

    jobs_root = os.path.join(campaign_dir, "jobs")
    if os.path.isdir(jobs_root):
        for name in sorted(os.listdir(jobs_root)):
            job_dir = os.path.join(jobs_root, name)
            if os.path.isdir(job_dir):
                print(job_line(job_dir))
    else:
        print("  (no jobs directory yet)")

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
