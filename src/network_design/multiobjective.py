"""Payoff-table normalization and two sampled frontier methods."""
import numpy as np
from .model import KEYS
from .solve import solve


def usable(r):
    return r.get("objectives") is not None and r["diagnostics"]["feasible"]


def nondominated(records, rtol=1e-7, atol=1e-5):
    candidates = [r for r in records if usable(r)]
    if not candidates:
        return []
    values = np.array([[r["objectives"][k] for k in KEYS] for r in candidates])
    keep = []
    for i,v in enumerate(values):
        if not keep or not np.any(np.all(np.abs(values[keep]-v) <= atol+rtol*np.maximum(1,np.abs(v)),axis=1)):
            keep.append(i)
    unique_values = values[keep]
    front = []
    for pos,i in enumerate(keep):
        v = values[i]
        tol = atol+rtol*np.maximum(1,np.maximum(np.abs(unique_values),np.abs(v)))
        dominated = np.any(np.all(unique_values <= v+tol,axis=1) & np.any(unique_values < v-tol,axis=1))
        if not dominated:
            front.append(candidates[i])
    return sorted(front,key=lambda r:r["objectives"]["cost"])


def anchors(d, **kwargs):
    records = [solve(d, objective=k, **kwargs) for k in KEYS]
    if not all(usable(r) for r in records):
        raise RuntimeError("An individual objective returned no feasible incumbent; increase the time limit or check normal-operation feasibility.")
    payoff = np.array([[r["objectives"][k] for k in KEYS] for r in records])
    ideal = dict(zip(KEYS, map(float,payoff.min(axis=0))))
    ranges = dict(zip(KEYS, map(float,np.ptp(payoff,axis=0))))
    warnings = []
    for r in records:
        if r["solver"]["termination_condition"] != "optimal" or (r["solver"]["gap"] or 0)>1e-6:
            warnings.append(f'{r["settings"]["objective"]} anchor has termination {r["solver"]["termination_condition"]}, gap {r["solver"]["gap"]}; ideal and scales are incumbent estimates.')
    nonvarying = [k for k in KEYS if ranges[k] <= 1e-9*max(1,abs(ideal[k]))]
    return dict(records=records, ideal=ideal, ranges=ranges, nonvarying=nonvarying, warnings=warnings)


def weighted(d, weights, normalization, **kwargs):
    return solve(d, weights=weights, ideal=normalization["ideal"], ranges=normalization["ranges"], **kwargs)


def weight_grid(step=0.25):
    count = round(1/step)
    if count < 1 or not np.isclose(count*step,1):
        raise ValueError("Weight step must divide 1")
    return [(i/count, (count-i)/count) for i in range(count+1)]


def sampled_frontier(d, grid=21, time_limit=15, mip_gap=0.01, progress=None, normalization=None):
    if grid < 2:
        raise ValueError("Epsilon grid must contain at least two resilience thresholds")
    config = dict(time_limit=time_limit, mip_gap=mip_gap)
    norm = normalization or anchors(d, **config)
    records = list(norm["records"])
    def add(r):
        records.append(r)
        if progress:
            progress(len(records), len(KEYS)+len(weight_grid())+grid, r)
    for weights in weight_grid():
        add(weighted(d,weights,norm,**config))
    upper = {k:max(r["objectives"][k] for r in norm["records"]) for k in KEYS}
    for r in np.linspace(norm["ideal"]["expected_unmet_demand"],upper["expected_unmet_demand"],grid):
        add(solve(d,bounds=dict(expected_unmet_demand=float(r)),**config))
    return dict(schema_version=2, objective_keys=list(KEYS), label="Approximate sampled Pareto frontier; completeness is not certified", normalization=norm, config=dict(epsilon_grid=grid, **config), attempts=records, front=nondominated(records))


def frontier(d, **kwargs):
    """Run the default NSGA-II genetic search; MILP sampling is a benchmark."""
    from .nsga2 import evolve
    return evolve(d, **kwargs)
