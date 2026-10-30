"""Seeded NSGA-II over binary network decisions and a dispatch-preference gene.

Feasible candidates dominate infeasible ones. Dispatch is evaluated by a fixed-
network LP, not by a MILP search for facilities. No global optimality is claimed.
"""
import copy
import hashlib
import json
import numpy as np
from .model import KEYS
from .data import validate
from .solve import solve
from .reporting import audit
from .multiobjective import usable, nondominated


def rank_and_crowding(records):
    """Fast nondominated sorting and objective-wise crowding distances."""
    n = len(records)
    values = [tuple(r['objectives'][k] for k in KEYS) if usable(r)
              else (float('inf'), float('inf')) for r in records]
    dominates = [[] for _ in records]
    counts = [0]*n
    for i in range(n):
        for j in range(i+1, n):
            a, b = values[i], values[j]
            if all(x <= y for x,y in zip(a,b)) and any(x < y for x,y in zip(a,b)):
                dominates[i].append(j); counts[j] += 1
            elif all(y <= x for x,y in zip(a,b)) and any(y < x for x,y in zip(a,b)):
                dominates[j].append(i); counts[i] += 1
    fronts, ranks, distances = [], [0]*n, [0.0]*n
    current = [i for i in range(n) if counts[i] == 0]
    while current:
        fronts.append(current)
        following = []
        for i in current:
            ranks[i] = len(fronts)-1
            for j in dominates[i]:
                counts[j] -= 1
                if counts[j] == 0:
                    following.append(j)
        for k in range(len(KEYS)):
            order = sorted(current, key=lambda i: values[i][k])
            low, high = values[order[0]][k], values[order[-1]][k]
            if not np.isfinite(high) or high == low:
                continue
            distances[order[0]] = distances[order[-1]] = float('inf')
            for pos in range(1, len(order)-1):
                distances[order[pos]] += (values[order[pos+1]][k]-values[order[pos-1]][k])/(high-low)
        current = following
    return fronts, ranks, distances


def evolve(d, population_size=48, generations=40, seed=42, crossover_rate=0.9,
           mutation_rate=None, time_limit=15, mip_gap=0.01, progress=None):
    validate(d)
    if population_size < 4 or generations < 1:
        raise ValueError('Population must be at least 4 and generations at least 1')
    warehouses = [n['id'] for n in d['nodes'] if n['kind'] == 'warehouse']
    arcs = d['arcs']
    width = len(warehouses)+len(arcs)
    mutation_rate = 1/width if mutation_rate is None else mutation_rate
    if not 0 <= crossover_rate <= 1 or not 0 <= mutation_rate <= 1:
        raise ValueError('Genetic operator probabilities must lie in [0, 1]')
    rng = np.random.default_rng(seed)
    # Preference spans dispatch penalties logarithmically, including cost-only.
    # Linear [0,1] weights previously crowded nearly every candidate at zero loss.
    max_penalty = max(1, 2*max(a['cost'] for a in arcs))*100
    cache, attempts, history = {}, [], []
    total = population_size*(generations+1)

    def repair(bits):
        bits = bits.copy()
        opened = set(w for w,b in zip(warehouses,bits) if b)
        for i,a in enumerate(arcs):
            if (a['source'] in warehouses and a['source'] not in opened) or (a['target'] in warehouses and a['target'] not in opened):
                bits[len(warehouses)+i] = False
        return bits

    def evaluate(individual, generation):
        bits, preference = individual
        key = (tuple(bool(x) for x in bits), preference)
        if key not in cache:
            fixed = dict(opened_warehouses=[w for w,b in zip(warehouses,bits) if b],
                         activated_arcs=[a['id'] for a,b in zip(arcs,bits[len(warehouses):]) if b])
            penalty = 0 if preference == 0 else np.expm1(preference/1000*np.log1p(max_penalty))
            weight = float(penalty/(1+penalty))
            record = solve(d, weights=(1-weight,weight), ideal=dict.fromkeys(KEYS,0),
                           ranges=dict.fromkeys(KEYS,1), fixed_design=fixed, time_limit=time_limit, mip_gap=mip_gap)
            if usable(record):
                # Decode to the network actually needed by all scenario flows.
                # Removing unused infrastructure preserves every dispatch constraint.
                active = [a['id'] for a in arcs if any(
                    flows[a['id']] > 1e-8 for flows in record['shipments'].values())]
                touched = {endpoint for a in arcs if a['id'] in active
                           for endpoint in (a['source'],a['target'])}
                opened = [w for w in warehouses if w in touched]
                record['activated_arcs'] = active
                record['opened_warehouses'] = opened
                checked = audit(d,dict(record,objectives=None))
                old_cost = record['objectives']['cost']
                record['objectives'] = checked['recomputed_objectives']
                # Fixed-cost reduction shifts both scalar LP bounds equally.
                shift = (1-weight)*(old_cost-record['objectives']['cost'])
                for bound in ('lower_bound','upper_bound'):
                    if record['solver'][bound] is not None:
                        record['solver'][bound] -= shift
                record['diagnostics'] = audit(d,record)
                record['settings']['fixed_design'] = dict(opened_warehouses=opened,activated_arcs=active)
                record['design_id'] = hashlib.sha256(json.dumps(dict(
                    network=record['settings']['fixed_design'],objectives=record['objectives']),
                    sort_keys=True).encode()).hexdigest()[:12]
            record['method'] = 'nsga2' 
            record['settings'].update(generation=generation, dispatch_preference=preference/1000, shortfall_penalty=float(penalty))
            cache[key] = record
        record = copy.deepcopy(cache[key])
        record["settings"]["generation"] = generation
        attempts.append(record)
        if progress:
            progress(len(attempts),total,record)
        if usable(record):
            # Inherit the decoded infrastructure instead of carrying unused links.
            bits[:] = [w in record['opened_warehouses'] for w in warehouses]+[
                a['id'] in record['activated_arcs'] for a in arcs]
        return record

    # Dense seeds provide full-capacity candidates, subject to LP termination/audit.
    population = [(np.ones(width,dtype=bool),p) for p in (0,1000)]
    while len(population) < population_size:
        density = rng.uniform(0.35,1)
        population.append((repair(rng.random(width)<density),int(round(1000*(len(population)-2)/max(1,population_size-3)))))
    records = [evaluate(x,0) for x in population]
    if not any(usable(r) for r in records):
        raise RuntimeError('No feasible initial network; check full-network capacity or increase evaluation time limit')
    for generation in range(1,generations+1):
        _, ranks, distances = rank_and_crowding(records)
        def tournament():
            a,b = rng.integers(len(population),size=2)
            return population[min((a,b),key=lambda i:(ranks[i],-distances[i]))]
        children = []
        while len(children) < population_size:
            a,b = tournament(),tournament()
            bits = a[0].copy()
            preference = a[1]
            if rng.random() < crossover_rate:
                mask = rng.random(width)<0.5
                bits[mask] = b[0][mask]
                alpha = rng.uniform()
                preference = int(round(alpha*a[1]+(1-alpha)*b[1]))
                preference = min(1000,max(0,preference))
            previous = bits.copy()
            bits ^= rng.random(width)<mutation_rate
            # Newly opened warehouses need incident links to become useful.
            newly_opened = {w for i,w in enumerate(warehouses) if bits[i] and not previous[i]}
            for i,arc in enumerate(arcs):
                if arc['source'] in newly_opened or arc['target'] in newly_opened:
                    bits[len(warehouses)+i] = True
            if rng.random() < max(mutation_rate,0.2):
                preference = int(rng.integers(1001))
            children.append((repair(bits),preference))
        combined = population+children
        combined_records = records+[evaluate(x,generation) for x in children]
        unique, duplicates, seen = [], [], set()
        for i,r in enumerate(combined_records):
            key = tuple(round(r['objectives'][k],6) for k in KEYS) if usable(r) else ('infeasible',i)
            if key in seen:
                duplicates.append(i)
            else:
                seen.add(key); unique.append(i)
        # Keep duplicate fitness vectors only when needed to fill the population.
        indices = unique+duplicates[:max(0,population_size-len(unique))]
        combined = [combined[i] for i in indices]
        combined_records = [combined_records[i] for i in indices]
        fronts, _, distances = rank_and_crowding(combined_records)
        survivors = []
        for front in fronts:
            survivors.extend(sorted(front,key=lambda i:-distances[i])[:population_size-len(survivors)])
            if len(survivors) == population_size:
                break
        population = [combined[i] for i in survivors]
        records = [combined_records[i] for i in survivors]
        history.append(dict(generation=generation, feasible=sum(usable(r) for r in records),
                            nondominated=len(nondominated(records)), unique_evaluations=len(cache)))
    return dict(schema_version=2, objective_keys=list(KEYS), algorithm='nsga2',
                label='Approximate NSGA-II Pareto frontier; global optimality is not certified',
                config=dict(population_size=population_size,generations=generations,seed=seed,
                            crossover_rate=crossover_rate,mutation_rate=mutation_rate,time_limit=time_limit,mip_gap=mip_gap),
                normalization=dict(records=[],ideal=dict.fromkeys(KEYS,0),ranges=dict.fromkeys(KEYS,1),nonvarying=[],warnings=[]),
                history=history, attempts=attempts, front=nondominated(attempts))
