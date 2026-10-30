import pyomo.environ as pyo
import pytest
from network_design.data import tiny_instance
from network_design.model import build_model
from network_design.solve import solve
from network_design.reporting import audit


def test_hand_calculated_design():
    d = tiny_instance()
    m = build_model(d)
    for w in m.W:
        m.y[w].fix(1)
    for a in m.A:
        m.z[a].fix(1)
    for s in m.S:
        warehouse = 'W1' if s=='normal' else 'W2'
        for a in m.A:
            value = {'P1>'+warehouse:10,warehouse+'>C1':4,warehouse+'>C2':6}.get(a,0)
            m.x[a,s].fix(value)
        for c in m.C:
            m.u[c,s].fix(0)
    m.obj=pyo.Objective(expr=m.cost)
    solver = pyo.SolverFactory('appsi_highs')
    solver.options['threads'] = 1
    result = solver.solve(m)
    assert str(result.solver.termination_condition)=='optimal'
    assert pyo.value(m.cost)==pytest.approx(56)
    assert not hasattr(m,"co2")
    assert pyo.value(m.expected_unmet_demand)==0
    assert m.y.index_set() is m.W
    assert m.z.index_set() is m.A
    assert len(m.x)==len(m.A)*len(m.S)


def test_outage_and_all_constraints():
    d = tiny_instance()
    r = solve(d,mip_gap=0)
    # Cost contains no hidden shortfall penalty: W1 costs 10 + 3 links + 0.7*20.
    assert r['objectives']==pytest.approx(dict(cost=27,expected_unmet_demand=3))
    assert r['diagnostics']['conditional_unmet_percent']==pytest.approx(100)
    assert r['diagnostics']['feasible']
    assert sum(r['unmet_demand']['normal'].values())==0
    assert all(x==0 for a,x in r['shipments']['outage'].items() if 'W1' in a)
    assert audit(d,r)['recomputed_objectives']==pytest.approx(r['objectives'])
    # The independent audit detects a flow violating balance and activation/capacity.
    r['shipments']['outage']['W2>C1']=100
    diagnostics = audit(d,r)
    assert not diagnostics['feasible']
    assert any('Arc capacity' in v for v in diagnostics['violations'])
    assert any('Warehouse balance' in v for v in diagnostics['violations'])
    assert any('Warehouse capacity' in v for v in diagnostics['violations'])
