import pytest
from network_design import generate, tiny_instance, solve
from network_design.multiobjective import anchors, weighted
from network_design.model import KEYS


def test_default_normal_feasibility():
    r=solve(generate(),time_limit=10,mip_gap=0.02)
    assert r['solver']['has_incumbent']
    assert r['diagnostics']['feasible']
    assert sum(r['unmet_demand']['normal'].values())==pytest.approx(0)
    assert r['dimensions']['binary_variables']==408
    assert r['dimensions']['continuous_variables']==4260


def test_individual_optima_and_normalized_solution():
    d=tiny_instance()
    norm=anchors(d,time_limit=5,mip_gap=0)
    extra=weighted(d,(0.5,0.5),norm,time_limit=5,mip_gap=0)
    assert extra['diagnostics']['feasible']
    for i,k in enumerate(KEYS):
        for r in norm['records']+[extra]:
            assert norm['records'][i]['objectives'][k] <= r['objectives'][k]+1e-6
    for r in norm['records']+[extra]:
        assert r['solver']['termination_condition']=='optimal'
        assert r['solver']['gap']==pytest.approx(0)
        assert r['solver']['runtime']>=0


def test_infeasible_bounds_have_no_objectives():
    r=solve(tiny_instance(),bounds={'expected_unmet_demand':-1},time_limit=5)
    assert r['objectives'] is None
    assert r['solver']['termination_condition']=='infeasible'
    assert not r['solver']['has_incumbent']
    assert r['diagnostics']['violations']


@pytest.mark.parametrize('weights',[(-1,2),(0,0),(1,1),(1,float('nan')),(1/3,1/3,1/3)])
def test_bad_weights(weights):
    with pytest.raises(ValueError):
        solve(tiny_instance(),weights=weights,ideal=dict.fromkeys(KEYS,0),ranges=dict.fromkeys(KEYS,1))


def test_removed_objective_is_rejected():
    assert KEYS == ("cost", "expected_unmet_demand")
    with pytest.raises(ValueError, match="Unknown objective"):
        solve(tiny_instance(), objective="co2")
    with pytest.raises(ValueError, match="Invalid objective bounds"):
        solve(tiny_instance(), bounds={"co2": 10})
