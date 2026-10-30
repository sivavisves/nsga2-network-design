"""The extensive-form two-stage stochastic MILP, independent of the UI."""
import pyomo.environ as pyo
from .data import validate

KEYS = ("cost", "expected_unmet_demand")


def build_model(d):
    validate(d)
    m = pyo.ConcreteModel()
    nodes = {n["id"]:n for n in d["nodes"]}
    arcs = {a["id"]:a for a in d["arcs"]}
    scenarios = {s["id"]:s for s in d["scenarios"]}
    m.P = pyo.Set(initialize=[i for i,n in nodes.items() if n["kind"]=="plant"])
    m.W = pyo.Set(initialize=[i for i,n in nodes.items() if n["kind"]=="warehouse"])
    m.C = pyo.Set(initialize=[i for i,n in nodes.items() if n["kind"]=="customer"])
    m.A = pyo.Set(initialize=list(arcs))
    m.S = pyo.Set(initialize=list(scenarios))
    incoming = {i:[a for a,v in arcs.items() if v["target"]==i] for i in nodes}
    outgoing = {i:[a for a,v in arcs.items() if v["source"]==i] for i in nodes}
    m.y = pyo.Var(m.W, domain=pyo.Binary)
    m.z = pyo.Var(m.A, domain=pyo.Binary)
    m.x = pyo.Var(m.A,m.S, domain=pyo.NonNegativeReals)
    m.u = pyo.Var(m.C,m.S, domain=pyo.NonNegativeReals)
    m.supply = pyo.Constraint(m.P,m.S, rule=lambda m,p,s: sum(m.x[a,s] for a in outgoing[p]) <= nodes[p]["supply"]*scenarios[s].get("plant_fraction",{}).get(p,1))
    m.balance = pyo.Constraint(m.W,m.S, rule=lambda m,w,s: sum(m.x[a,s] for a in incoming[w]) == sum(m.x[a,s] for a in outgoing[w]))
    m.throughput = pyo.Constraint(m.W,m.S, rule=lambda m,w,s: sum(m.x[a,s] for a in outgoing[w]) <= nodes[w]["capacity"]*scenarios[s].get("warehouse_availability",{}).get(w,1)*m.y[w])
    m.transport = pyo.Constraint(m.A,m.S, rule=lambda m,a,s: m.x[a,s] <= arcs[a]["capacity"]*scenarios[s].get("arc_fraction",{}).get(a,1)*m.z[a])
    m.demand = pyo.Constraint(m.C,m.S, rule=lambda m,c,s: sum(m.x[a,s] for a in incoming[c])+m.u[c,s] == nodes[c]["demand"])
    for c in m.C:
        m.u[c,"normal"].fix(0)
    m.activation = pyo.Constraint(m.A, rule=lambda m,a: m.z[a] <= m.y[arcs[a]["target"] if arcs[a]["target"] in m.W else arcs[a]["source"]])
    m.cost = pyo.Expression(expr=sum(nodes[w]["fixed_cost"]*m.y[w] for w in m.W)+sum(arcs[a]["fixed_cost"]*m.z[a] for a in m.A)+sum(scenarios[s]["probability"]*arcs[a]["cost"]*m.x[a,s] for a in m.A for s in m.S))
    m.expected_unmet_demand = pyo.Expression(expr=sum(scenarios[s]["probability"]*m.u[c,s] for c in m.C for s in m.S if s!="normal"))
    return m
