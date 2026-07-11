#!/usr/bin/env python3
"""Stage descent with witness retention (new script; does not modify dc_search).

Status field meanings (written into SHA2_STATUS_FILE):
  trying_bound  — BVLE ceiling of the STP call currently running / last started
  best_found    — lowest SAT objective value found in THIS stage so far
  optimum       — only set when the stage finishes (final answer); absent while running
  binary_lo/hi  — proven floor / best feasible during binary search
"""

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


def _publish(**fields):
    """Heartbeat with explicit search vocabulary; never leaves a stale optimum."""
    payload = dict(fields)
    # While searching, optimum must not linger from a prior stage.
    if "optimum" not in payload:
        payload["optimum"] = None
    dc_search._update_status(**payload)


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
    del terms  # terms only size the objective; already baked into `objective`.
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
        "stage=%s trying_bound=%d timeout=%ds"
        % (name, bound, call_timeout)
    )

    started = time.time()
    output, error = dc_search._run_stp(cvc, call_timeout)
    elapsed = time.time() - started

    if error:
        result = error.split(":")[0]
        iterations.append({
            "stage": name,
            "trying_bound": bound,
            "dt": round(elapsed, 2),
            "result": result.upper(),
        })
        dc_search.log(
            "stage=%s trying_bound=%d result=%s dt=%.1fs"
            % (name, bound, result.upper(), elapsed)
        )
        return result, None, None

    if output.strip() == "Valid.":
        iterations.append({
            "stage": name,
            "trying_bound": bound,
            "dt": round(elapsed, 2),
            "result": "UNSAT",
        })
        dc_search.log(
            "stage=%s trying_bound=%d result=UNSAT dt=%.1fs"
            % (name, bound, elapsed)
        )
        return "unsat", None, None

    out_file = os.path.join(
        dc_search.work_dir(),
        "dc_%s_%s_b%d.out" % (tag, name, bound),
    )
    # Avoid clobbering when the same bound is retried: uniquify if needed.
    if os.path.exists(out_file):
        out_file = os.path.join(
            dc_search.work_dir(),
            "dc_%s_%s_b%d_%d.out" % (tag, name, bound, int(time.time())),
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
    if achieved > bound:
        dc_search.log(
            "stage=%s WARNING achieved=%d > trying_bound=%d; clamping"
            % (name, achieved, bound)
        )
        achieved = bound

    iterations.append({
        "stage": name,
        "trying_bound": bound,
        "achieved": achieved,
        "dt": round(elapsed, 2),
        "result": "SAT",
        "out_file": out_file,
    })
    dc_search.log(
        "stage=%s trying_bound=%d best_found=%s (this call) result=SAT dt=%.1fs"
        % (name, bound, achieved, elapsed)
    )
    _retain_sat(retained, keep_last, achieved, out_file, cvc_snap, name)
    return "sat", achieved, out_file


def _make_carry(objective, best_value, width):
    if best_value is None:
        return ""
    obj_name = objective.split(":", 1)[0].strip()
    return objective + "ASSERT %s = 0bin%s;\n" % (
        obj_name,
        bin(best_value)[2:].zfill(width),
    )


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
      binary — binary search; first probe at start_bound (default 150)
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
    stage_started = time.time()

    if strategy == "binary":
        return _descend_binary(
            name=name,
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
            retained=[],
            terms=terms,
        )

    return _descend_linear(
        name=name,
        variable=variable,
        base_constr=base_constr,
        carried=carried,
        tag=tag,
        timeout=timeout,
        budget=budget,
        keep_last=keep_last,
        width=width,
        start_bound=start_bound,
        max_possible=max_possible,
        objective=objective,
        cvc=cvc,
        stage_started=stage_started,
        iterations=iterations,
        retained=[],
        terms=terms,
    )


def _descend_linear(
    name,
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
    terms,
):
    best_found = None
    best_out = None
    status = "ok"
    if start_bound is not None:
        trying = min(start_bound, max_possible)
    else:
        trying = max_possible

    dc_search.log(
        "stage=%s linear descent initial_trying_bound=%d max=%d"
        % (name, trying, max_possible)
    )

    while True:
        if _budget_hit(budget, stage_started):
            iterations.append({
                "stage": name,
                "result": "BUDGET",
                "elapsed": round(time.time() - stage_started, 2),
            })
            dc_search.log(
                "stage=%s budget reached best_found=%s" % (name, best_found)
            )
            break

        call_timeout = _call_timeout(timeout, budget, stage_started)
        _publish(
            phase=name,
            current_stage=name,
            trying_bound=trying,
            best_found=best_found,
            current_bound=trying,  # alias for older monitors
            best_value=best_found,
            strategy="linear",
            tag=tag,
        )

        kind, achieved, out_file = _solve_bound(
            name, terms, variable, base_constr, carried, tag, objective, cvc,
            trying, width, call_timeout, keep_last, retained, iterations,
        )

        if kind not in ("sat", "unsat"):
            status = "ok" if best_out is not None else kind
            break

        if kind == "unsat":
            # With linear descent, UNSAT at trying means optimum is best_found
            # (if any) and trying was one below the previous SAT.
            status = "ok" if best_out is not None else "infeasible"
            dc_search.log(
                "stage=%s linear stop UNSAT at trying_bound=%d best_found=%s"
                % (name, trying, best_found)
            )
            break

        best_found = achieved
        best_out = out_file
        if achieved == 0:
            _publish(
                phase=name,
                current_stage=name,
                trying_bound=trying,
                best_found=best_found,
                current_bound=trying,
                best_value=best_found,
                strategy="linear",
                tag=tag,
            )
            break
        trying = achieved - 1
        _publish(
            phase=name,
            current_stage=name,
            trying_bound=trying,
            best_found=best_found,
            current_bound=trying,
            best_value=best_found,
            retained_values=[item["value"] for item in retained],
            strategy="linear",
            tag=tag,
        )

    return (
        best_found,
        best_out,
        [x["out_file"] for x in retained],
        _make_carry(objective, best_found, width),
        iterations,
        status,
    )


def _descend_binary(
    name,
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
    terms,
):
    """Binary-search minimize: probe start_bound, raise if UNSAT, then bisect.

    Invariants:
      lo = lowest value not yet proven UNSAT-below (all k < lo are impossible
           once lo advances from UNSAT answers)
      hi = best SAT value found (feasible); None until first SAT
      best_found == hi after each SAT
    """
    best_found = None
    best_out = None
    status = "ok"
    probe = min(max(0, int(start_bound)), max_possible)
    lo = 0  # values < lo are known impossible only after UNSAT raises

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
        _publish(
            phase=name,
            current_stage=name,
            trying_bound=search,
            best_found=best_found,
            current_bound=search,
            best_value=best_found,
            strategy="binary",
            binary_phase="find_hi",
            binary_lo=lo,
            binary_hi=hi,
            tag=tag,
        )
        kind, achieved, out_file = _solve_bound(
            name, terms, variable, base_constr, carried, tag, objective, cvc,
            search, width, call_timeout, keep_last, retained, iterations,
        )
        if kind == "sat":
            hi = achieved
            best_found = achieved
            best_out = out_file
            dc_search.log(
                "stage=%s binary found feasible best_found=%d (tried %d)"
                % (name, best_found, search)
            )
            break
        if kind == "unsat":
            # Everything <= search is impossible.
            lo = search + 1
            if search >= max_possible or lo > max_possible:
                status = "infeasible"
                break
            nxt = min(max_possible, max(lo, search * 2 if search else 1))
            if nxt < lo:
                nxt = lo
            if nxt == search:
                status = "infeasible"
                break
            dc_search.log(
                "stage=%s binary UNSAT <= %d; raise trying_bound %d -> %d (lo=%d)"
                % (name, search, search, nxt, lo)
            )
            search = nxt
            continue
        status = "ok" if best_out is not None else kind
        break

    if hi is None:
        return (
            best_found,
            best_out,
            [x["out_file"] for x in retained],
            _make_carry(objective, best_found, width),
            iterations,
            status,
        )

    if hi == 0 or lo >= hi:
        # Already optimal (0) or lo pushed up to hi during find_hi (shouldn't).
        return (
            best_found,
            best_out,
            [x["out_file"] for x in retained],
            _make_carry(objective, best_found, width),
            iterations,
            "ok",
        )

    # Phase 2: binary search minimum in [lo, hi].
    while lo < hi:
        if _budget_hit(budget, stage_started):
            iterations.append({
                "stage": name,
                "result": "BUDGET",
                "phase": "bisect",
                "lo": lo,
                "hi": hi,
                "best_found": best_found,
            })
            dc_search.log(
                "stage=%s binary budget stop lo=%d hi=%d best_found=%s"
                % (name, lo, hi, best_found)
            )
            break

        mid = (lo + hi) // 2
        call_timeout = _call_timeout(timeout, budget, stage_started)
        _publish(
            phase=name,
            current_stage=name,
            trying_bound=mid,
            best_found=best_found,
            current_bound=mid,
            best_value=best_found,
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
            # Feasible at achieved (<= mid). Shrink search to [lo, achieved].
            hi = achieved
            best_found = achieved
            best_out = out_file
            dc_search.log(
                "stage=%s binary SAT -> best_found=%d; search [%d, %d]"
                % (name, best_found, lo, hi)
            )
            if achieved == 0:
                break
            continue
        if kind == "unsat":
            # No solution with obj <= mid; minimum is at least mid+1.
            lo = mid + 1
            dc_search.log(
                "stage=%s binary UNSAT -> search [%d, %d] best_found=%s"
                % (name, lo, hi, best_found)
            )
            continue
        status = "ok" if best_out is not None else kind
        break

    # When the loop exits with lo == hi, optimum is proven == hi == best_found.
    if lo == hi and best_found is not None and best_found != lo:
        # UNSAT raised lo up to the known feasible hi.
        if lo == hi:
            pass
    if best_found is not None and lo > best_found:
        # Inconsistent; keep best_found as best-known.
        dc_search.log(
            "stage=%s WARNING lo=%d > best_found=%d"
            % (name, lo, best_found)
        )

    dc_search.log(
        "stage=%s binary done best_found=%s proven_range=[%d,%s] status=%s"
        % (name, best_found, lo, hi, status)
    )
    return (
        best_found,
        best_out,
        [x["out_file"] for x in retained],
        _make_carry(objective, best_found, width),
        iterations,
        status,
    )
