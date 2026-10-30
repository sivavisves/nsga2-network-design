from network_design.data import tiny_instance
from network_design.multiobjective import nondominated, weight_grid, sampled_frontier
from network_design.model import KEYS
from network_design.reporting import persist


def point(v):
    return dict(objectives=dict(zip(KEYS,v)),diagnostics=dict(feasible=True))


def test_nondominance_and_duplicates():
    a,b,c,d=point((1,4)),point((4,1)),point((5,5)),point((1,4))
    assert nondominated([a,b,c,d])==[a,b]
    assert nondominated([point((1,1)),point((1+1e-9,1))])==[point((1,1))]
    assert len(weight_grid())==5
    assert all(abs(sum(w)-1)<1e-9 for w in weight_grid())


def test_both_frontier_methods_and_exports(tmp_path):
    d=tiny_instance()
    results=sampled_frontier(d,grid=5,time_limit=5,mip_gap=0)
    assert len(results['attempts'])==12
    assert len(results['front'])>=2
    assert results['objective_keys'] == list(KEYS)
    assert len(results['normalization']['records']) == 2
    for r in results['attempts']:
        if r['objectives'] is not None:
            assert set(r['objectives']) == set(KEYS)
        if r['method'] == 'weighted':
            assert len(r['settings']['weights']) == 2
        if r['method'] == 'epsilon':
            assert set(r['settings']['bounds']) == {'expected_unmet_demand'}
    assert {r['method'] for r in results['attempts']}=={'individual','weighted','epsilon'}
    assert len(nondominated(results['front']))==len(results['front'])
    for r in results['front']:
        assert r['diagnostics']['feasible']
    persist(d,results,tmp_path)
    assert (tmp_path/'results.json').exists()
    assert (tmp_path/'pareto_front.csv').exists()
    for r in results['front']:
        for name in ['metrics','facilities','links','flows','unmet','scenarios']:
            assert (tmp_path/r['design_id']/f'{name}.csv').exists()
