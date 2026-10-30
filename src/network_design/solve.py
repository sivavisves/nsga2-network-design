"""HiGHS solve with explicit incumbent checks and complete status reporting."""
import hashlib
import json
import math
import time
import pyomo.environ as pyo
from .model import build_model, KEYS
from .reporting import audit


def solve(d, objective="cost", weights=None, ideal=None, ranges=None, bounds=None, time_limit=15, mip_gap=0.01, fixed_design=None):
    if time_limit <= 0 or not 0 <= mip_gap < 1:
        raise ValueError("Positive time limit and 0 <= mip_gap < 1 required")
    m = build_model(d)
    if fixed_design is not None:
        for w in m.W:
            m.y[w].fix(int(w in fixed_design["opened_warehouses"]))
        for a in m.A:
            m.z[a].fix(int(a in fixed_design["activated_arcs"]))
        pyo.TransformationFactory("core.relax_integer_vars").apply_to(m)
    bounds = bounds or {}
    if any(k not in KEYS or not math.isfinite(v) for k,v in bounds.items()):
        raise ValueError("Invalid objective bounds")
    m.epsilon_bounds = pyo.ConstraintList()
    for k,v in bounds.items():
        m.epsilon_bounds.add(getattr(m,k) <= v)
    method = "epsilon" if bounds else "individual"
    settings = dict(objective=objective, bounds=bounds, time_limit=time_limit, mip_gap=mip_gap)
    if weights is not None:
        if len(weights)!=len(KEYS) or any(not math.isfinite(w) or w < 0 for w in weights) or abs(sum(weights)-1)>1e-8:
            raise ValueError("Two nonnegative weights summing to one are required")
        if ideal is None or ranges is None:
            raise ValueError("Normalization requires individual-optimum ideal and ranges")
        expression = sum(w*(getattr(m,k)-ideal[k])/max(ranges[k],1e-9) for w,k in zip(weights,KEYS) if ranges[k] > 1e-9*max(1,abs(ideal[k])))
        method = "weighted"
        settings.update(weights=list(weights), ideal=ideal, ranges=ranges)
    else:
        if objective not in KEYS:
            raise ValueError(f"Unknown objective {objective}")
        expression = getattr(m,objective)
    m.objective = pyo.Objective(expr=expression)
    solver = pyo.SolverFactory("appsi_highs")
    if not solver.available(exception_flag=False):
        raise RuntimeError("HiGHS is unavailable. Install with: pip install -e '.[test]' (includes highspy).")
    solver.options.update(time_limit=float(time_limit), mip_rel_gap=float(mip_gap), random_seed=42, threads=1)
    started = time.perf_counter()
    result = solver.solve(m, load_solutions=False)
    runtime = time.perf_counter()-started
    termination = str(result.solver.termination_condition)
    has_solution = bool(len(result.solution)) and termination not in ("infeasible", "unbounded", "infeasibleOrUnbounded")
    info = dict(status=str(result.solver.status), termination_condition=termination, runtime=runtime, gap=None, lower_bound=None, upper_bound=None, has_incumbent=has_solution)
    for source,target in [("lower_bound","lower_bound"),("upper_bound","upper_bound")]:
        try:
            value = float(getattr(result.problem,source))
            if math.isfinite(value):
                info[target] = value
        except (ValueError, TypeError, AttributeError):
            pass
    if info["lower_bound"] is not None and info["upper_bound"] is not None:
        difference = abs(info["upper_bound"]-info["lower_bound"])
        info["gap"] = 0.0 if difference <= 1e-9*max(1,abs(info["upper_bound"])) else difference/max(abs(info["upper_bound"]),1e-10)
    if fixed_design is not None:
        settings["fixed_design"] = fixed_design
    rid = hashlib.sha256(json.dumps(dict(instance=d, method=method, settings=settings), sort_keys=True).encode()).hexdigest()[:12]
    record = dict(design_id=rid, method=method, settings=settings, solver=info, objectives=None, dimensions=dict(binary_variables=0 if fixed_design is not None else len(m.W)+len(m.A), continuous_variables=(len(m.A)+len(m.C))*len(m.S), constraints=m.nconstraints()))
    if not has_solution:
        record["diagnostics"] = dict(feasible=False, violations=[f"No incumbent solution: {termination}"])
        return record
    m.solutions.load_from(result)
    record.update(objectives={k:float(pyo.value(getattr(m,k))) for k in KEYS},
                  opened_warehouses=[w for w in m.W if pyo.value(m.y[w])>0.5], activated_arcs=[a for a in m.A if pyo.value(m.z[a])>0.5],
                  shipments={s:{a:max(0.0,float(pyo.value(m.x[a,s]))) for a in m.A} for s in m.S},
                  unmet_demand={s:{c:max(0.0,float(pyo.value(m.u[c,s]))) for c in m.C} for s in m.S})
    record["diagnostics"] = audit(d,record)
    if not record["diagnostics"]["feasible"]:
        record["solver"]["status"] = "validation_failed"
    return record
