import pytest
from network_design.data import tiny_instance
from network_design.nsga2 import evolve, rank_and_crowding
from network_design.multiobjective import nondominated
from network_design.reporting import audit, persist


def point(cost, loss):
    return dict(objectives=dict(cost=cost,expected_unmet_demand=loss), diagnostics=dict(feasible=True))


def test_ranking_crowding_and_feasibility():
    records = [point(1,4),point(2,3),point(4,1),point(5,5),
               dict(objectives=None,diagnostics=dict(feasible=False))]
    fronts, ranks, distances = rank_and_crowding(records)
    assert set(fronts[0]) == {0,1,2}
    assert ranks[3] == 1 and ranks[4] == 2
    assert distances[0] == distances[2] == float('inf')
    assert distances[1] == 2


def test_evolution_reproducible_audited_and_exportable(tmp_path):
    d = tiny_instance()
    config = dict(population_size=8,generations=3,seed=7,time_limit=5,mip_gap=0)
    a, b = evolve(d,**config), evolve(d,**config)
    assert a['algorithm'] == 'nsga2'
    assert len(a['attempts']) == 32
    assert len(a['history']) == 3
    assert len(a['front']) >= 2
    assert [r['objectives'] for r in a['front']] == [r['objectives'] for r in b['front']]
    assert len(nondominated(a['front'])) == len(a['front'])
    for r in a['front']:
        assert r['method'] == 'nsga2'
        assert audit(d,r)['feasible']
        assert 'fixed_design' in r['settings']
        assert all(any(flows[a] > 1e-8 for flows in r['shipments'].values())
                   for a in r['activated_arcs'])
    assert len({r['settings']['shortfall_penalty'] for r in a['attempts'][:8]}) >= 6
    persist(d,a,tmp_path)
    assert (tmp_path/'pareto_front.csv').exists()


@pytest.mark.parametrize('config',[dict(population_size=3),dict(generations=0),dict(mutation_rate=2),dict(crossover_rate=-1)])
def test_invalid_configuration(config):
    with pytest.raises(ValueError):
        evolve(tiny_instance(),**config)
