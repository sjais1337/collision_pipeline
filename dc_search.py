"""Search differential characteristics for local collisions found by lc_search.

config_gen builds the per-round flags, src/unit_function_256.py emits the STP
model, and parse_dc reads the resulting characteristics. Optional validation is
delegated to find_collision.py.
"""

import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "src"))

from config_gen import gen_config, with_value_transitions  # noqa: E402
from unit_function_256 import (  # noqa: E402
    message_expand,
    message_expand_value,
    read_differential_characteristic,
    sha_a,
    sha_e,
    sha2_value,
)

RESULTS_DC = os.path.join(HERE, "results_dc")
WORK = os.path.join(RESULTS_DC, "_work")

BLOCK = 32
THREADS = os.environ.get("SHA2_THREADS", str(os.cpu_count() or 4))
QUERY = "\nQUERY FALSE;\nCOUNTEREXAMPLE;"


class DCModel:
    """Build the STP model and its O1-O5 objective terms."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.start = cfg["start_step"]
        self.end = cfg["end_step"]
        self.mb = cfg["message_bound"]
        self.msgdiff = cfg["message_differential"]
        self.op = [cfg["op%d" % i] for i in range(10)]

        self.declare = []
        self.constraints = []

    def check_assign(self, declaration):
        if declaration not in self.declare:
            self.declare.append(declaration)

    def _add_model(self, variables, constraints):
        self.constraints.append("".join(constraints))
        for variable in variables:
            self.check_assign(variable)

    def main(self):
        for step in range(self.start, self.end):
            variables, constraints = sha_e(
                BLOCK,
                self.op[0][step],
                self.op[1][step],
                self.op[2][step],
                step,
            )
            self._add_model(variables, constraints)

            variables, constraints = sha_a(
                BLOCK,
                self.op[3][step],
                self.op[4][step],
                self.op[5][step],
                step,
            )
            self._add_model(variables, constraints)

            # config_gen enables op9 only for the value-transition model.
            if self.op[9][step]:
                variables, constraints = sha2_value(BLOCK, "IF", "MAJ", step)
                self._add_model(variables, constraints)

                if step > 15:
                    variables, constraints = message_expand_value(BLOCK, step)
                    self._add_model(variables, constraints)

        for step in range(16, self.mb):
            variables, constraints = message_expand(
                BLOCK,
                self.op[6][step],
                self.op[7][step],
                self.op[8][step],
                step,
            )
            self._add_model(variables, constraints)

    def build(self):
        self.declare = []
        self.constraints = []
        self.main()
        self.assign_value()
        return "".join(self.declare), "".join(self.constraints)

    def declared_set(self):
        return {line.split(":")[0].strip() for line in self.declare}

    def _declared_message_words(self):
        words = set()
        for declaration in self.declare:
            if declaration.startswith("wv_"):
                words.add(int(declaration.split("_")[1]))
        return words

    def assign_value(self):
        declared_words = self._declared_message_words()

        # lc_search supplies the only message words allowed to differ.
        for step in range(self.mb):
            if step not in declared_words or step in self.msgdiff:
                continue
            for bit in range(BLOCK):
                self.constraints.append(
                    "ASSERT wv_%d_%d = 0bin0;\n"
                    "ASSERT wd_%d_%d = 0bin0;\n"
                    % (step, bit, step, bit)
                )

        active_terms = []
        for step in self.msgdiff:
            for bit in range(BLOCK):
                active_terms.append("0bin000000000@wd_%d_%d" % (step, bit))
        self.constraints.append(
            "ASSERT BVGE(BVPLUS(10,%s), 0bin0000000001);\n"
            % ",".join(active_terms)
        )

        # State differences are zero before and after the collision window.
        for step in range(self.start - 4, self.start):
            for bit in range(BLOCK):
                self.constraints.append(
                    "ASSERT xv_%d_%d = 0bin0;\n"
                    "ASSERT xd_%d_%d = 0bin0;\n"
                    "ASSERT yv_%d_%d = 0bin0;\n"
                    "ASSERT yd_%d_%d = 0bin0;\n"
                    % (step, bit, step, bit, step, bit, step, bit)
                )

        for step in range(self.end - 8, self.end):
            for bit in range(BLOCK):
                self.constraints.append(
                    "ASSERT xv_%d_%d = 0bin0;\n"
                    "ASSERT xd_%d_%d = 0bin0;\n"
                    % (step, bit, step, bit)
                )

        for step in range(self.end - 4, self.end):
            for bit in range(BLOCK):
                self.constraints.append(
                    "ASSERT yv_%d_%d = 0bin0;\n"
                    "ASSERT yd_%d_%d = 0bin0;\n"
                    % (step, bit, step, bit)
                )

    def _O1_terms(self, declared):
        """Weight of the final one or two active message words."""
        active_words = sorted(self.msgdiff)
        final_words = active_words[-2:] if len(active_words) >= 2 else active_words
        return [term for step in final_words for term in self._wd(step, declared)]

    def _O2_terms(self, declared):
        """Total active message-word weight."""
        return [
            term
            for step in sorted(self.msgdiff)
            for term in self._wd(step, declared)
        ]

    def _O3_terms(self, declared):
        """Uncontrolled Sigma1, IF, and E conditions."""
        terms = []

        for step in range(17, self.end):
            if self.op[0][step] == 1:
                terms += self._named("ned_xor", step, declared)

            if self.op[1][step] in (1, 4):
                terms += self._named("nev_if", step, declared)
                terms += self._named("ned_if", step, declared)
            elif self.op[1][step] in (2, 3, 5):
                terms += self._named("ned_if", step, declared)

        for step in range(16, self.end - 4):
            terms += self._yd(step, declared)

        return terms

    def _O4_terms(self, declared):
        """Total A-register difference weight."""
        return [
            term
            for step in range(self.mb)
            for term in self._xd(step, declared)
        ]

    def _O5_terms(self, declared):
        """Total E-register difference weight."""
        return [
            term
            for step in range(self.mb)
            for term in self._yd(step, declared)
        ]

    @staticmethod
    def _term(variable):
        return "0bin000000000@%s" % variable

    def _bits(self, prefix, step, declared):
        terms = []
        for bit in range(BLOCK):
            variable = "%s_%d_%d" % (prefix, step, bit)
            if variable in declared:
                terms.append(self._term(variable))
        return terms

    def _wd(self, step, declared):
        return self._bits("wd", step, declared)

    def _yd(self, step, declared):
        return self._bits("yd", step, declared)

    def _xd(self, step, declared):
        return self._bits("xd", step, declared)

    def _named(self, prefix, step, declared):
        return self._bits(prefix, step, declared)


def count_hamming(out_file, message_bound):
    """Return the E, W, and A activity counts from an STP assignment."""
    del message_bound  # Kept for compatibility with existing callers.

    values = {"x": {}, "y": {}, "w": {}}
    differences = {"x": {}, "y": {}, "w": {}}

    with open(out_file) as result:
        lines = result.read().split("\n")

    for line in lines:
        if " = " not in line:
            continue

        name, raw_value = line.replace("ASSERT( ", "").split(" = ", 1)
        name = name.strip()
        bit = 1 if "1" in raw_value else 0

        for prefix in ("xv", "xd", "yv", "yd", "wv", "wd"):
            if not name.startswith(prefix + "_"):
                continue

            register = prefix[0]
            index = name[len(prefix) + 1:]
            target = values if prefix[1] == "v" else differences
            target[register][index] = bit
            break

    counts = {}
    for register in ("x", "y", "w"):
        indices = set(values[register]) | set(differences[register])
        counts[register] = sum(
            1
            for index in indices
            if values[register].get(index, 0)
            or differences[register].get(index, 0)
        )

    return counts["y"], counts["w"], counts["x"]


def build_specs(R, lc_json=None):
    """Load and rank the candidates produced by lc_search.py."""
    if lc_json is None:
        lc_json = os.path.join(HERE, "results_lc", "lc_%d.json" % R)

    if not os.path.exists(lc_json):
        raise FileNotFoundError(
            "No local collision for R=%d at %s. Run lc_search.py %d first "
            "(the LC search is the sole, preset-free source of local collisions)."
            % (R, lc_json, R)
        )

    with open(lc_json) as source:
        data = json.load(source)

    specs = [dict(data["best"], source="lc-search-best")]
    specs += [
        dict(candidate, source="lc-search-alt")
        for candidate in data.get("alternates", [])
    ]

    unique_specs = []
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
        unique_specs.append(spec)

    # The state tail needs about nine steps to host a collision.
    min_feasible_span = 9
    unique_specs.sort(
        key=lambda spec: (
            0 if spec["span"] >= min_feasible_span else 1,
            spec.get("num_active", len(spec["active_words"])),
            spec.get("cond_total", 0),
            spec["span"],
        )
    )
    return unique_specs


def _parse_obj(solver_output, name):
    for line in solver_output.split("\n"):
        if name not in line or " = " not in line:
            continue

        raw = line.split(" = ", 1)[1].replace(" );", "").replace(");", "").strip()
        if raw.startswith("0x"):
            return int(raw[2:], 16)
        if raw.startswith("0b"):
            return int(raw[2:], 2)

        try:
            return int(raw)
        except ValueError:
            return None

    return None


def _obj_def(name, terms, width=10):
    if not terms:
        return None
    return "%s: BITVECTOR(%d);\nASSERT %s = BVPLUS(%d,%s);\n" % (
        name,
        width,
        name,
        width,
        ",".join(terms),
    )


def _run_stp(cvc, timeout):
    command = ["stp", cvc, "--cryptominisat", "--threads", THREADS]
    try:
        output = subprocess.check_output(
            command,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
        return output.decode(), None
    except subprocess.TimeoutExpired:
        return None, "timeout"
    except subprocess.CalledProcessError as error:
        return None, "error:" + error.output.decode()[:150]


def _write_cvc(path, *parts):
    with open(path, "w") as model_file:
        for part in parts:
            model_file.write(part)


def _write_solver_output(path, output):
    with open(path, "w") as result_file:
        result_file.write(output)


def descend_stage(name, terms, variable, base_constr, carried, tag, timeout,
                  query, width=10, budget=None):
    """Minimize one objective and return its best witness."""
    os.makedirs(WORK, exist_ok=True)

    iterations = []
    objective = _obj_def(name, terms, width)
    cvc = os.path.join(WORK, "dc_%s_%s.cvc" % (tag, name))

    if objective is None:
        _write_cvc(cvc, variable, base_constr, carried, query)

        started = time.time()
        output, error = _run_stp(cvc, timeout)
        elapsed = time.time() - started

        if error:
            status = error.split(":")[0]
            event = {
                "stage": name,
                "dt": round(elapsed, 2),
                "result": status.upper(),
            }
            return None, None, "", [event], status

        if output.strip() == "Valid.":
            event = {
                "stage": name,
                "dt": round(elapsed, 2),
                "result": "UNSAT",
            }
            return None, None, "", [event], "infeasible"

        out_file = os.path.join(WORK, "dc_%s_%s.out" % (tag, name))
        _write_solver_output(out_file, output)
        event = {
            "stage": name,
            "achieved": 0,
            "dt": round(elapsed, 2),
            "result": "SAT",
        }
        return 0, out_file, "", [event], "ok"

    bound = min((1 << width) - 1, len(terms))
    best_value = None
    best_out = None
    status = "ok"
    stage_started = time.time()

    while True:
        if budget is not None and best_out is not None:
            if time.time() - stage_started > budget:
                iterations.append({"stage": name, "result": "BUDGET"})
                break

        bound_constraint = "ASSERT BVLE(%s, 0bin%s);\n" % (
            name,
            bin(bound)[2:].zfill(width),
        )
        _write_cvc(
            cvc,
            variable,
            base_constr,
            carried,
            objective,
            bound_constraint,
            query,
        )

        started = time.time()
        output, error = _run_stp(cvc, timeout)
        elapsed = time.time() - started

        if error:
            result = error.split(":")[0]
            iterations.append({
                "stage": name,
                "bound": bound,
                "dt": round(elapsed, 2),
                "result": result.upper(),
            })
            status = "ok" if best_out is not None else result
            break

        if output.strip() == "Valid.":
            iterations.append({
                "stage": name,
                "bound": bound,
                "dt": round(elapsed, 2),
                "result": "UNSAT",
            })
            status = "ok" if best_out is not None else "infeasible"
            break

        out_file = os.path.join(
            WORK,
            "dc_%s_%s_%d.out" % (tag, name, bound),
        )
        _write_solver_output(out_file, output)

        achieved = _parse_obj(output, name)
        if achieved is None:
            achieved = bound

        iterations.append({
            "stage": name,
            "bound": bound,
            "achieved": achieved,
            "dt": round(elapsed, 2),
            "result": "SAT",
        })
        best_value = achieved
        best_out = out_file

        if achieved == 0:
            break
        bound = achieved - 1

    carry = ""
    if best_value is not None:
        carry = objective + "ASSERT %s = 0bin%s;\n" % (
            name,
            bin(best_value)[2:].zfill(width),
        )

    return best_value, best_out, carry, iterations, status


def _cascade_result(status, final_out, optima, iterations, message_bound):
    result = {
        "status": status,
        "found": final_out is not None,
        "min_conditions": optima.get("o3"),
        "stage_optima": optima,
        "iters": iterations,
        "total_time": round(sum(item.get("dt", 0) for item in iterations), 2),
        "out_file": final_out,
        "sat_outs": [final_out] if final_out else [],
    }

    if final_out is not None:
        he, hw, ha = count_hamming(final_out, message_bound)
        result.update({"HE": he, "HW": hw, "HA": ha})

    return result


def solve_cascade(cfg, tag, timeout=600, o5_value=True, budget=None,
                  stop_after="o5"):
    """Run the O1-O5 lexicographic minimization cascade."""
    diff_model = DCModel(cfg)
    diff_variables, diff_constraints = diff_model.build()
    diff_declared = diff_model.declared_set()

    stages = [
        ("o1", diff_model._O1_terms(diff_declared)),
        ("o2", diff_model._O2_terms(diff_declared)),
        ("o3", diff_model._O3_terms(diff_declared)),
        ("o4", diff_model._O4_terms(diff_declared)),
    ]

    carried = ""
    optima = {}
    all_iterations = []
    final_out = None
    status = "ok"

    for name, terms in stages:
        value, out_file, carry, iterations, stage_status = descend_stage(
            name,
            terms,
            diff_variables,
            diff_constraints,
            carried,
            tag,
            timeout,
            QUERY,
            budget=budget,
        )
        all_iterations += iterations
        optima[name] = value

        if out_file is not None:
            final_out = out_file

        if stage_status != "ok":
            status = stage_status
            if out_file is None:
                return _cascade_result(
                    status,
                    final_out,
                    optima,
                    all_iterations,
                    cfg["message_bound"],
                )

        carried += carry

        if name == stop_after:
            return _cascade_result(
                status if final_out else "no_solution",
                final_out,
                optima,
                all_iterations,
                cfg["message_bound"],
            )

    if o5_value:
        value_model = DCModel(with_value_transitions(cfg))
        o5_variables, o5_constraints = value_model.build()
        o5_terms = value_model._O5_terms(value_model.declared_set())
    else:
        o5_variables = diff_variables
        o5_constraints = diff_constraints
        o5_terms = diff_model._O5_terms(diff_declared)

    value, out_file, _, iterations, stage_status = descend_stage(
        "o5",
        o5_terms,
        o5_variables,
        o5_constraints,
        carried,
        tag,
        timeout,
        QUERY,
        budget=budget,
    )
    all_iterations += iterations

    if out_file is not None:
        optima["o5"] = value
        final_out = out_file
    elif o5_value:
        status = "o5_value_" + stage_status
        value, out_file, _, iterations, _ = descend_stage(
            "o5",
            diff_model._O5_terms(diff_declared),
            diff_variables,
            diff_constraints,
            carried,
            tag + "_diffO5",
            timeout,
            QUERY,
            budget=budget,
        )
        all_iterations += iterations

        if out_file is not None:
            optima["o5"] = value
            final_out = out_file

    if stage_status != "ok" and status == "ok":
        status = "o5_" + stage_status
    if final_out is not None and status == "ok":
        status = "minimized"

    return _cascade_result(
        status if final_out else "no_solution",
        final_out,
        optima,
        all_iterations,
        cfg["message_bound"],
    )


def _sat_out_files(result, tag):
    """Return the final witnesses available for validation."""
    del tag  # Kept for compatibility with existing callers.
    return [
        path
        for path in result.get("sat_outs", [])
        if path and os.path.exists(path)
    ]


def _print_attempt(R, index, candidate):
    print("  [R=%d] try %d (%s): start=%d span=%d active=%s" % (
        R,
        index,
        candidate.get("source", "?"),
        candidate["start_step"],
        candidate["span"],
        candidate["active_words"],
    ))


def _print_result(result):
    optima = result.get("stage_optima", {})
    values = [optima.get(name) for name in ("o1", "o2", "o3", "o4", "o5")]
    print("    -> status=%s found=%s O1..O5=%s O3(cond)=%s total=%.1fs" % (
        result["status"],
        result["found"],
        values,
        result["min_conditions"],
        result["total_time"],
    ))


def _write_summary(R, summary):
    os.makedirs(RESULTS_DC, exist_ok=True)
    path = os.path.join(RESULTS_DC, "dc_R%d.json" % R)
    with open(path, "w") as result_file:
        json.dump(summary, result_file, indent=2, default=str)


def _write_characteristic(R, out_file):
    characteristic = read_differential_characteristic(BLOCK, out_file, R)
    path = os.path.join(RESULTS_DC, "dc_R%d.txt" % R)

    with open(path, "w") as result_file:
        for row in characteristic:
            if isinstance(row, list):
                for line in row:
                    result_file.write(str(line) + "\n")
            else:
                result_file.write(str(row) + "\n")


def run_specs(R, specs, timeout=300, max_attempts=8, init_pro=97,
              validate=True, oracle_timeout=300, max_validate=1,
              solve_budget=None, o5_value=True):
    """Try local collisions in order and retain the first validated DC."""
    del init_pro  # Preserved in the public signature for existing callers.

    attempts = []
    chosen = None
    chosen_out = None
    chosen_collision = None
    best_effort = None

    if validate:
        import find_collision

    for index, candidate in enumerate(specs[:max_attempts]):
        config = gen_config(
            R,
            candidate["start_step"],
            candidate["start_step"] + candidate["span"],
            candidate["active_words"],
        )
        tag = "R%d_c%d" % (R, index)
        _print_attempt(R, index, candidate)

        result = solve_cascade(
            config,
            tag,
            timeout=timeout,
            o5_value=o5_value,
            budget=solve_budget,
        )
        result["candidate"] = candidate
        attempts.append(result)
        _print_result(result)

        if not result["found"]:
            continue

        if not validate:
            chosen = result
            chosen_out = result["out_file"]
            break

        verified = None
        last_collision = None
        for dc_out in _sat_out_files(result, tag)[:max_validate]:
            collision = find_collision.solve_dc(
                R,
                dc_out,
                timeout=oracle_timeout,
            )
            last_collision = collision
            print("       validate %s -> %s" % (
                os.path.basename(dc_out),
                collision.get("status"),
            ))

            if collision.get("verified"):
                verified = (dc_out, collision)
                break
            if collision.get("status") in ("timeout", "error"):
                break

        if best_effort is None and result["out_file"]:
            best_effort = (result, result["out_file"], last_collision)

        if verified:
            chosen_out, chosen_collision = verified
            chosen = result
            print("    => DC validated: verified SFS colliding pair found")
            break

        if last_collision and last_collision.get("status") == "invalid_dc":
            print("    => DC has no conforming pair (invalid_dc); trying next candidate")
        else:
            print("    => pair search did not complete in budget; trying next candidate")

    if chosen is None and best_effort is not None:
        chosen, chosen_out, chosen_collision = best_effort

    if chosen and chosen_out:
        chosen["out_file"] = chosen_out

    summary = {
        "R": R,
        "chosen": chosen,
        "chosen_out": chosen_out,
        "collision": chosen_collision,
        "attempts": attempts,
    }
    _write_summary(R, summary)

    if chosen and chosen_out:
        _write_characteristic(R, chosen_out)

    if validate and chosen and chosen_collision:
        find_collision._save(R, chosen["candidate"], chosen_collision)

    return summary


def run_round(R, lc_json=None, timeout=300, max_attempts=8, init_pro=97,
              validate=True, oracle_timeout=300, max_validate=1,
              solve_budget=None, o5_value=True):
    specs = build_specs(R, lc_json)
    return run_specs(
        R,
        specs,
        timeout=timeout,
        max_attempts=max_attempts,
        init_pro=init_pro,
        validate=validate,
        oracle_timeout=oracle_timeout,
        max_validate=max_validate,
        solve_budget=solve_budget,
        o5_value=o5_value,
    )


def main():
    R = int(sys.argv[1])
    timeout = int(sys.argv[2]) if len(sys.argv) > 2 else 300
    max_attempts = int(sys.argv[3]) if len(sys.argv) > 3 else 8
    o5_value = bool(int(sys.argv[4])) if len(sys.argv) > 4 else True

    run_round(
        R,
        timeout=timeout,
        max_attempts=max_attempts,
        o5_value=o5_value,
    )


if __name__ == "__main__":
    main()
