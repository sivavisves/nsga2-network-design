"""Independent arithmetic and constraint audit of extracted decisions."""
import csv
import json
from pathlib import Path


def audit(d, r, tolerance=1e-4):
    nodes = {n["id"]: n for n in d["nodes"]}
    arcs = {a["id"]: a for a in d["arcs"]}
    opened, active = set(r["opened_warehouses"]), set(r["activated_arcs"])
    cost = sum(nodes[w]["fixed_cost"] for w in opened)+sum(arcs[a]["fixed_cost"] for a in active)
    loss = 0.0
    violations, stats = [], []
    def check(condition, message):
        if not condition:
            violations.append(message)
    for a in active:
        v = arcs[a]
        w = v["source"] if nodes[v["source"]]["kind"]=="warehouse" else v["target"]
        check(w in opened, f"Activated arc {a} at closed warehouse")
    total = sum(n["demand"] for n in nodes.values() if n["kind"]=="customer")
    for s in d["scenarios"]:
        sid = s["id"]
        flow = r["shipments"][sid]
        unmet = r["unmet_demand"][sid]
        inc, out = {i:0.0 for i in nodes}, {i:0.0 for i in nodes}
        shipping_cost = 0.0
        for a,v in arcs.items():
            x = flow.get(a,0.0)
            check(x >= -tolerance, f"Negative flow {a}/{sid}")
            check(x <= v["capacity"]*s.get("arc_fraction",{}).get(a,1)*(a in active)+tolerance, f"Arc capacity {a}/{sid}")
            out[v["source"]] += x
            inc[v["target"]] += x
            shipping_cost += v["cost"]*x
        for i,n in nodes.items():
            if n["kind"] == "plant":
                check(out[i] <= n["supply"]*s.get("plant_fraction",{}).get(i,1)+tolerance, f"Plant supply {i}/{sid}")
            elif n["kind"] == "warehouse":
                check(abs(inc[i]-out[i]) <= tolerance, f"Warehouse balance {i}/{sid}")
                check(out[i] <= n["capacity"]*s.get("warehouse_availability",{}).get(i,1)*(i in opened)+tolerance, f"Warehouse capacity {i}/{sid}")
            else:
                u = unmet[i]
                check(u >= -tolerance and abs(inc[i]+u-n["demand"]) <= tolerance, f"Customer demand {i}/{sid}")
                if sid == "normal":
                    check(abs(u) <= tolerance, f"Normal unmet demand {i}")
        shortfall = sum(unmet.values())
        cost += s["probability"]*shipping_cost
        if sid != "normal":
            loss += s["probability"]*shortfall
        stats.append(dict(scenario=sid, name=s["name"], probability=s["probability"], fulfilled_demand=total-shortfall, unmet_demand=shortfall, shipping_cost=shipping_cost, aggregate_arc_flow=sum(flow.values())))
    metrics = dict(cost=cost, expected_unmet_demand=loss)
    if r.get("objectives"):
        for k,v in metrics.items():
            check(abs(v-r["objectives"][k]) <= tolerance*max(1,abs(v)), f"Objective mismatch: {k}")
    pd = sum(s["probability"] for s in d["scenarios"] if s["id"]!="normal")
    conditional = loss/pd if pd else None
    return dict(feasible=not violations, violations=violations, recomputed_objectives=metrics, scenarios=stats, conditional_unmet_demand=conditional, conditional_unmet_percent=100*conditional/total if pd else None)


def csv_text(rows):
    import io
    buffer = io.StringIO()
    if rows:
        writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return buffer.getvalue()


def tables(d, r):
    return {
        "metrics": [dict(design_id=r["design_id"], method=r["method"], **r["objectives"], conditional_unmet_demand=r["diagnostics"]["conditional_unmet_demand"], conditional_unmet_percent=r["diagnostics"]["conditional_unmet_percent"], **r["solver"])],
        "facilities": [dict(**n, opened=n["id"] in r["opened_warehouses"]) for n in d["nodes"] if n["kind"]=="warehouse"],
        "links": [dict(**a, activated=a["id"] in r["activated_arcs"]) for a in d["arcs"]],
        "flows": [dict(scenario=s, arc=a, flow=x) for s,flows in r["shipments"].items() for a,x in flows.items()],
        "unmet": [dict(scenario=s, customer=c, unmet_demand=u) for s,us in r["unmet_demand"].items() for c,u in us.items()],
        "scenarios": r["diagnostics"]["scenarios"],
    }


def persist(d, results, path):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    (path/"results.json").write_text(json.dumps(results, indent=2, allow_nan=False)+"\n")
    for r in results["front"]:
        target = path/r["design_id"]
        target.mkdir(exist_ok=True)
        for name,rows in tables(d,r).items():
            (target/f"{name}.csv").write_text(csv_text(rows))
    (path/"pareto_front.csv").write_text(csv_text([tables(d,r)["metrics"][0] for r in results["front"]]))
