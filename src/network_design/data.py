"""JSON schema v2. All quantities use a single annual operating period."""
import json
from pathlib import Path
import numpy as np


def validate(d):
    if d.get("schema_version") != 2:
        raise ValueError("Expected instance schema_version=2")
    nodes = d["nodes"]
    groups = {k: [n for n in nodes if n["kind"] == k] for k in ("plant", "warehouse", "customer")}
    ids = [n["id"] for n in nodes]
    if len(set(ids)) != len(ids) or any(not g for g in groups.values()):
        raise ValueError("Unique node IDs and all three echelons are required")
    if any(n["kind"] not in groups or not all(np.isfinite(n[k]) for k in ("x", "y")) for n in nodes):
        raise ValueError("Invalid node type or coordinates")
    for n in nodes:
        keys = {"plant": ["supply"], "warehouse": ["capacity", "fixed_cost"], "customer": ["demand"]}[n["kind"]]
        if any(not np.isfinite(n[k]) or n[k] <= 0 for k in keys):
            raise ValueError("Node capacities, demand, and costs must be positive")
    lookup = {n["id"]: n for n in nodes}
    arcs = d["arcs"]
    arc_ids = {a["id"] for a in arcs}
    pairs = [(a["source"], a["target"]) for a in arcs]
    if len(arc_ids) != len(arcs) or len(set(pairs)) != len(arcs):
        raise ValueError("Duplicate arcs")
    for a in arcs:
        if a["source"] not in lookup or a["target"] not in lookup:
            raise ValueError("Unknown arc endpoint")
        if (lookup[a["source"]]["kind"], lookup[a["target"]]["kind"]) not in [("plant", "warehouse"), ("warehouse", "customer")]:
            raise ValueError("Only plant-to-warehouse and warehouse-to-customer arcs are allowed")
        if any(not np.isfinite(a[k]) or a[k] < 0 for k in ("capacity", "cost", "fixed_cost")):
            raise ValueError("Invalid arc parameter")
    scenarios = d["scenarios"]
    probs = [s["probability"] for s in scenarios]
    if not scenarios or scenarios[0]["id"] != "normal" or len({s["id"] for s in scenarios}) != len(scenarios):
        raise ValueError("Unique scenarios starting with normal are required")
    if not all(np.isfinite(p) and p >= 0 for p in probs) or not np.isclose(sum(probs), 1) or probs[0] <= 0:
        raise ValueError("Scenario probabilities must sum to one and normal probability must be positive")
    for s in scenarios:
        for field, kind in [("warehouse_availability", "warehouse"), ("plant_fraction", "plant"), ("arc_fraction", None)]:
            values = s.get(field, {})
            eligible = arc_ids if kind is None else {n["id"] for n in groups[kind]}
            if any(k not in eligible or not np.isfinite(v) or not 0 <= v <= 1 for k, v in values.items()):
                raise ValueError("Invalid scenario capacity fraction")
            if s["id"] == "normal" and any(v != 1 for v in values.values()):
                raise ValueError("Normal operations must have full asset availability")
    demand = sum(n["demand"] for n in groups["customer"])
    if min(sum(n[k] for n in groups[g]) for g, k in [("plant", "supply"), ("warehouse", "capacity")]) < demand:
        raise ValueError("Insufficient aggregate normal capacity")
    return d


def generate(seed=42, plants=3, warehouses=12, customers=30, scenarios=10):
    if min(plants, warehouses, customers) < 1 or scenarios < 2:
        raise ValueError("Positive sizes and at least two scenarios are required")
    rng = np.random.default_rng(seed)
    nodes = []
    demand = rng.integers(70, 151, customers)
    total = float(sum(demand))
    for kind, count, prefix in [("plant", plants, "P"), ("warehouse", warehouses, "W"), ("customer", customers, "C")]:
        for i in range(count):
            n = dict(id=f"{prefix}{i+1:02d}", kind=kind, x=float(rng.uniform(0, 100)), y=float(rng.uniform(0, 100)))
            if kind == "plant":
                n["supply"] = total * 1.35 / plants
            elif kind == "warehouse":
                n.update(capacity=total * max(0.24, 1.35 / warehouses) * float(rng.uniform(0.9, 1.1)), fixed_cost=float(rng.uniform(18000, 65000)))
                rng.random()  # Reserve the former emissions draw to preserve existing inputs.
            else:
                n["demand"] = int(demand[i])
            nodes.append(n)
    arcs = []
    for source in nodes:
        for target in nodes:
            if (source["kind"], target["kind"]) not in [("plant", "warehouse"), ("warehouse", "customer")]:
                continue
            distance = float(np.hypot(source["x"]-target["x"], source["y"]-target["y"]))
            capacity = total*float(rng.uniform(1, 1.4))
            cost = distance*float(rng.uniform(0.7, 1.15))
            rng.random()  # Preserve the seeded cost/capacity sequence after dropping emissions.
            arcs.append(dict(id=f'{source["id"]}>{target["id"]}', source=source["id"], target=target["id"], distance=distance,
                             capacity=capacity, cost=cost, fixed_cost=float(rng.uniform(150, 1500))))
    ws = [n["id"] for n in nodes if n["kind"] == "warehouse"]
    ps = [n["id"] for n in nodes if n["kind"] == "plant"]
    shuffled = list(rng.permutation(ws))
    ss = [dict(id="normal", name="Normal operations", probability=0.7)]
    for i in range(scenarios-1):
        s = dict(id=f"disruption_{i+1}", probability=0.3/(scenarios-1))
        w = str(shuffled[i % len(ws)])
        if i < 4:
            s.update(name=f"Warehouse {w} outage", warehouse_availability={w: 0.0})
        elif i == 4:
            s.update(name=f"Plant {ps[0]} supply reduced 75%", plant_fraction={ps[0]: 0.25})
        elif i == 5:
            a = arcs[int(rng.integers(len(arcs)))]["id"]
            s.update(name=f"Transport {a} outage", arc_fraction={a: 0.0})
        else:
            w2 = str(shuffled[(i+1) % len(ws)])
            a = arcs[int(rng.integers(len(arcs)))]["id"]
            s.update(name=f"Multi-asset disruption {i-5}", warehouse_availability={w: 0.0, w2: 0.35}, plant_fraction={ps[i % len(ps)]: 0.5}, arc_fraction={a: 0.0})
        ss.append(s)
    return validate(dict(schema_version=2, seed=seed, units="annual; currency USD; coordinates km", nodes=nodes, arcs=arcs, scenarios=ss))


def save(d, path):
    validate(d)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(d, indent=2)+"\n")


def load(path):
    return validate(json.loads(Path(path).read_text()))


def tiny_instance():
    """Known feasible design: open both W1/W2, activate all links.

    Normal: P1 -> W1:10 -> (C1:4,C2:6). Outage: same via W2.
    Fixed cost=30+6=36; shipping=20 in both scenarios; total cost=56,
    disruption loss=0.
    """
    nodes = [dict(id="P1", kind="plant", x=0, y=5, supply=10),
             dict(id="W1", kind="warehouse", x=4, y=2, capacity=10, fixed_cost=10),
             dict(id="W2", kind="warehouse", x=4, y=8, capacity=10, fixed_cost=20),
             dict(id="C1", kind="customer", x=10, y=2, demand=4),
             dict(id="C2", kind="customer", x=10, y=8, demand=6)]
    arcs = [dict(id=f"{a}>{b}", source=a, target=b, distance=1, capacity=10, cost=1, fixed_cost=1)
            for a,b in [("P1","W1"),("P1","W2"),("W1","C1"),("W1","C2"),("W2","C1"),("W2","C2")]]
    return validate(dict(schema_version=2, seed=None, nodes=nodes, arcs=arcs,
                         scenarios=[dict(id="normal", name="Normal operations", probability=0.7),
                                    dict(id="outage", name="W1 outage", probability=0.3, warehouse_availability={"W1":0})]))
