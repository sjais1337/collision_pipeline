#!/usr/bin/env python3
"""Stage descent with witness retention (new script; does not modify dc_search)."""

import os
import time

import dc_search


def _delete_quiet(path):
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass


def set_threads(n):
    """Retarget CryptoMiniSat threads for this process without editing dc_search."""
    value = str(int(n))
    os.environ["SHA2_THREADS"] = value
    dc_search.THREADS = value


def descend_retained(
    name,
    terms,
    variable,
    base_constr,
    carried,
    tag,
    timeout,
    budget,
    keep_last=3,
    width=10,
):
    """Minimize one objective; keep at most ``keep_last`` SAT witnesses.

    When a better SAT arrives and the retention window is full, the oldest
    retained .out (and its .cvc snapshot) are deleted. The newest retained
    witness is always the best value so far.
    """
    os.makedirs(dc_search.work_dir(), exist_ok=True)

    iterations = []
    objective = dc_search._obj_def(name, terms, width)
    cvc = os.path.join(dc_search.work_dir(), "dc_%s_%s.cvc" % (tag, name))
    query = dc_search.QUERY

    if objective is None:
        dc_search._write_cvc(cvc, variable, base_constr, carried, query)
        started = time.time()
        output, error = dc_search._run_stp(cvc, timeout)
        elapsed = time.time() - started
        if error:
            status = error.split(":")[0]
            return None, None, [], "", [{
                "stage": name,
                "dt": round(elapsed, 2),
                "result": status.upper(),
            }], status
        if output.strip() == "Valid.":
            return None, None, [], "", [{
                "stage": name,
                "dt": round(elapsed, 2),
                "result": "UNSAT",
            }], "infeasible"
        out_file = os.path.join(
            dc_search.work_dir(),
            "dc_%s_%s.out" % (tag, name),
        )
        dc_search._write_solver_output(out_file, output)
        return 0, out_file, [out_file], "", [{
            "stage": name,
            "achieved": 0,
            "dt": round(elapsed, 2),
            "result": "SAT",
        }], "ok"

    bound = min((1 << width) - 1, len(terms))
    best_value = None
    best_out = None
    retained = []
    status = "ok"
    stage_started = time.time()

    while True:
        elapsed_stage = time.time() - stage_started
        if budget is not None and elapsed_stage >= budget:
            iterations.append({
                "stage": name,
                "result": "BUDGET",
                "elapsed": round(elapsed_stage, 2),
            })
            dc_search.log(
                "stage=%s budget reached (%.1fs >= %ds) best=%s"
                % (name, elapsed_stage, budget, best_value)
            )
            break

        remaining = None
        if budget is not None:
            remaining = max(1, int(budget - elapsed_stage))
        call_timeout = timeout if remaining is None else min(timeout, remaining)

        bound_constraint = "ASSERT BVLE(%s, 0bin%s);\n" % (
            name,
            bin(bound)[2:].zfill(width),
        )
        dc_search._write_cvc(
            cvc,
            variable,
            base_constr,
            carried,
            objective,
            bound_constraint,
            query,
        )

        dc_search._update_status(
            phase="dc_search",
            current_stage=name,
            current_bound=bound,
            best_value=best_value,
            retained=len(retained),
            tag=tag,
        )
        dc_search.log(
            "stage=%s bound=%d tag=%s keep=%d timeout=%ds"
            % (name, bound, tag, keep_last, call_timeout)
        )

        started = time.time()
        output, error = dc_search._run_stp(cvc, call_timeout)
        elapsed = time.time() - started

        if error:
            result = error.split(":")[0]
            iterations.append({
                "stage": name,
                "bound": bound,
                "dt": round(elapsed, 2),
                "result": result.upper(),
            })
            dc_search.log(
                "stage=%s bound=%d result=%s dt=%.1fs"
                % (name, bound, result.upper(), elapsed)
            )
            status = "ok" if best_out is not None else result
            break

        if output.strip() == "Valid.":
            iterations.append({
                "stage": name,
                "bound": bound,
                "dt": round(elapsed, 2),
                "result": "UNSAT",
            })
            dc_search.log(
                "stage=%s bound=%d result=UNSAT dt=%.1fs"
                % (name, bound, elapsed)
            )
            status = "ok" if best_out is not None else "infeasible"
            break

        out_file = os.path.join(
            dc_search.work_dir(),
            "dc_%s_%s_%d.out" % (tag, name, bound),
        )
        dc_search._write_solver_output(out_file, output)

        cvc_snap = out_file.replace(".out", ".cvc")
        try:
            with open(cvc, "rb") as src, open(cvc_snap, "wb") as dst:
                dst.write(src.read())
        except OSError:
            cvc_snap = None

        achieved = dc_search._parse_obj(output, name)
        if achieved is None:
            achieved = bound

        iterations.append({
            "stage": name,
            "bound": bound,
            "achieved": achieved,
            "dt": round(elapsed, 2),
            "result": "SAT",
            "out_file": out_file,
        })
        dc_search.log(
            "stage=%s bound=%d achieved=%s result=SAT dt=%.1fs"
            % (name, bound, achieved, elapsed)
        )

        retained.append({
            "value": achieved,
            "out_file": out_file,
            "cvc_file": cvc_snap,
        })
        while len(retained) > keep_last:
            old = retained.pop(0)
            _delete_quiet(old.get("out_file"))
            _delete_quiet(old.get("cvc_file"))
            dc_search.log(
                "stage=%s pruned older witness value=%s"
                % (name, old.get("value"))
            )

        best_value = achieved
        best_out = out_file
        dc_search._update_status(
            phase="dc_search",
            current_stage=name,
            current_bound=bound,
            best_value=best_value,
            best_out=best_out,
            retained_values=[item["value"] for item in retained],
            tag=tag,
        )

        if achieved == 0:
            break
        bound = achieved - 1

    carry = ""
    if best_value is not None:
        carry = objective + "ASSERT %s = 0bin%s;\n" % (
            name,
            bin(best_value)[2:].zfill(width),
        )

    retained_outs = [item["out_file"] for item in retained]
    return best_value, best_out, retained_outs, carry, iterations, status
