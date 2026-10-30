import copy
from pathlib import Path
import pytest
from network_design.data import generate, tiny_instance, validate, save, load


def test_default_reproducible_and_units(tmp_path):
    d = generate()
    assert d == generate(42)
    assert d != generate(43)
    assert [sum(n['kind']==k for n in d['nodes']) for k in ['plant','warehouse','customer']] == [3,12,30]
    assert len(d['arcs']) == 396
    assert len(d['scenarios']) == 10
    assert sum(s['probability'] for s in d['scenarios']) == pytest.approx(1)
    assert d['scenarios'][0]['probability'] == 0.7
    save(d,tmp_path/'instance.json')
    assert load(tmp_path/'instance.json')==d
    assert load(Path(__file__).resolve().parents[1]/'data/example_instance.json')==d


def test_invalid_data():
    for mutation in [lambda d:d['scenarios'][0].update(probability=-1),lambda d:d['scenarios'][0].update(warehouse_availability={'W1':0}),lambda d:d['arcs'][0].update(target='C1'),lambda d:d['nodes'][0].update(supply=-1)]:
        d = copy.deepcopy(tiny_instance())
        mutation(d)
        with pytest.raises(ValueError):
            validate(d)


@pytest.mark.parametrize('sizes',[(1,1,1,2),(2,3,5,5),(3,12,30,10)])
def test_configurable_sizes(sizes):
    validate(generate(42,*sizes))
