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


def _call_timeout(timeout, budget, stage_started):
    if budget is None:
        return timeout
    remaining = max(1, int(budget - (time.time() - stage_started)))
    return min(timeout, remaining)


def _budget_hit(budget, stage_started):
    return budget is not None and (time.time() - stage_started) >= budget


def _retain_sat(retained, keep_last, achieved, out_file, cvc_snap, name):
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


def _solve_bound(
    name,
    terms,
    variable,
    base_constr,
    carried,
    tag,
    objective,
    cvc,
    bound,
    width,
    call_timeout,
    keep_last,
    retained,
    iterations,
):
    """One STP query with BVLE(obj, bound). Returns (kind, achieved, out_file)."""
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
        dc_search.QUERY,
    )
    dc_search.log(
        "stage=%s bound=%d keep=%d timeout=%ds"
        % (name, bound, keep_last, call_timeout)
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
        return result, None, None

    if output.strip() == "Valid.":
        iterations.append({
            "stage": name,
            "bound": bound,
            "dt": round(elapsed, 2),
            "result": "UNSAT",
        })
        dc_search.log(
            "stage=%s bound=%d result=UNSAT dt=%.1fs" % (name, bound, elapsed)
        )
        return "unsat", None, None

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
    _retain_sat(retained, keep_last, achieved, out_file, cvc_snap, name)
    return "sat", achieved, out_file


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
    strategy="linear",
    start_bound=None,
):
    """Minimize one objective; keep at most ``keep_last`` SAT witnesses.

    strategy:
      linear — classic descent from max bound (or start_bound if set)
      binary — binary search; first probe at start_bound (default 150 for O3)
    """
    os.makedirs(dc_search.work_dir(), exist_ok=True)

    iterations = []
    objective = dc_search._obj_def(name, terms, width)
    cvc = os.path.join(dc_search.work_dir(), "dc_%s_%s.cvc" % (tag, name))

    if objective is None:
        dc_search._write_cvc(cvc, variable, base_constr, carried, dc_search.QUERY)
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

    max_possible = min((1 << width) - 1, len(terms))
    best_value = None
    best_out = None
    retained = []
    status = "ok"
    stage_started = time.time()

    if strategy == "binary":
        return _descend_binary(
            name=name,
            terms=terms,
            variable=variable,
            base_constr=base_constr,
            carried=carried,
            tag=tag,
            timeout=timeout,
            budget=budget,
            keep_last=keep_last,
            width=width,
            start_bound=150 if start_bound is None else start_bound,
            max_possible=max_possible,
            objective=objective,
            cvc=cvc,
            stage_started=stage_started,
            iterations=iterations,
            retained=retained,
        )

    # ---- linear descent (O1/O2 default) ----
    if start_bound is not None:
        bound = min(start_bound, max_possible)
    else:
        bound = max_possible

    while True:
        if _budget_hit(budget, stage_started):
            iterations.append({
                "stage": name,
                "result": "BUDGET",
                "elapsed": round(time.time() - stage_started, 2),
            })
            dc_search.log(
                "stage=%s budget reached best=%s" % (name, best_value)
            )
            break

        call_timeout = _call_timeout(timeout, budget, stage_started)
        dc_search._update_status(
            phase=name,
            current_stage=name,
            current_bound=bound,
            best_value=best_value,
            retained=len(retained),
            strategy="linear",
            tag=tag,
        )

        kind, achieved, out_file = _solve_bound(
            name, terms, variable, base_constr, carried, tag, objective, cvc,
            bound, width, call_timeout, keep_last, retained, iterations,
        )

        if kind not in ("sat", "unsat"):
            status = "ok" if best_out is not None else kind
            break

        if kind == "unsat":
            status = "ok" if best_out is not None else "infeasible"
            break

        best_value = achieved
        best_out = out_file
        dc_search._update_status(
            phase=name,
            current_stage=name,
            current_bound=bound,
            best_value=best_value,
            best_out=best_out,
            retained_values=[item["value"] for item in retained],
            strategy="linear",
            tag=tag,
        )
        if achieved == 0:
            break
        bound = achieved - 1

    obj_name = objective.split(":", 1)[0].strip()
    carry = ""
    if best_value is not None:
        carry = objective + "ASSERT %s = 0bin%s;\n" % (
            obj_name,
            bin(best_value)[2:].zfill(width),
        )
    return best_value, best_out, [x["out_file"] for x in retained], carry, iterations, status


def _descend_binary(
    name,
    terms,
    variable,
    base_constr,
    carried,
    tag,
    timeout,
    budget,
    keep_last,
    width,
    start_bound,
    max_possible,
    objective,
    cvc,
    stage_started,
    iterations,
    retained,
):
    """Binary-search minimize: probe start_bound, then bisect; raise if needed."""
    best_value = None
    best_out = None
    status = "ok"
    probe = min(max(0, int(start_bound)), max_possible)

    dc_search.log(
        "stage=%s binary search start_bound=%d max=%d"
        % (name, probe, max_possible)
    )

    # Phase 1: find any feasible upper bound, starting at probe.
    hi = None
    search = probe
    while hi is None:
        if _budget_hit(budget, stage_started):
            iterations.append({"stage": name, "result": "BUDGET", "phase": "find_hi"})
            status = "ok" if best_out is not None else "timeout"
            break

        call_timeout = _call_timeout(timeout, budget, stage_started)
        dc_search._update_status(
            phase=name,
            current_stage=name,
            current_bound=search,
            best_value=best_value,
            strategy="binary",
            binary_phase="find_hi",
            tag=tag,
        )
        kind, achieved, out_file = _solve_bound(
            name, terms, variable, base_constr, carried, tag, objective, cvc,
            search, width, call_timeout, keep_last, retained, iterations,
        )
        if kind == "sat":
            hi = achieved
            best_value = achieved
            best_out = out_file
            break
        if kind == "unsat":
            if search >= max_possible:
                status = "infeasible"
                break
            # Raise the probe (double, capped).
            nxt = min(max_possible, max(search + 1, search * 2 if search else 1))
            if nxt == search:
                status = "infeasible"
                break
            dc_search.log(
                "stage=%s binary raise probe %d -> %d" % (name, search, nxt)
            )
            search = nxt
            continue
        # timeout / error
        status = "ok" if best_out is not None else kind
        break

    if hi is None:
        obj_name = objective.split(":", 1)[0].strip()
        carry = ""
        return best_value, best_out, [x["out_file"] for x in retained], carry, iterations, status

    if hi == 0:
        obj_name = objective.split(":", 1)[0].strip()
        carry = objective + "ASSERT %s = 0bin%s;\n" % (
            obj_name,
            bin(0)[2:].zfill(width),
        )
        return 0, best_out, [x["out_file"] for x in retained], carry, iterations, "ok"

    # Phase 2: binary search minimum in [0, hi].
    lo = 0
    while lo < hi:
        if _budget_hit(budget, stage_started):
            iterations.append({
                "stage": name,
                "result": "BUDGET",
                "phase": "bisect",
                "lo": lo,
                "hi": hi,
            })
            dc_search.log(
                "stage=%s binary budget stop lo=%d hi=%d best=%s"
                % (name, lo, hi, best_value)
            )
            break

        mid = (lo + hi) // 2
        call_timeout = _call_timeout(timeout, budget, stage_started)
        dc_search._update_status(
            phase=name,
            current_stage=name,
            current_bound=mid,
            best_value=best_value,
            strategy="binary",
            binary_phase="bisect",
            binary_lo=lo,
            binary_hi=hi,
            tag=tag,
        )
        kind, achieved, out_file = _solve_bound(
            name, terms, variable, base_constr, carried, tag, objective, cvc,
            mid, width, call_timeout, keep_last, retained, iterations,
        )
        if kind == "sat":
            hi = achieved
            best_value = achieved
            best_out = out_file
            if achieved == 0:
                break
            continue
        if kind == "unsat":
            lo = mid + 1
            continue
        status = "ok" if best_out is not None else kind
        break

    obj_name = objective.split(":", 1)[0].strip()
    carry = ""
    if best_value is not None:
        carry = objective + "ASSERT %s = 0bin%s;\n" % (
            obj_name,
            bin(best_value)[2:].zfill(width),
        )
    return best_value, best_out, [x["out_file"] for x in retained], carry, iterations, status
