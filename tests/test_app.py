from pathlib import Path
import json
from streamlit.testing.v1 import AppTest
from network_design.data import load
from network_design.visualization import network_map, tradeoff_plot

ROOT=Path(__file__).resolve().parents[1]


def test_shipped_results_load_and_plot():
    d=load(ROOT/'data/example_instance.json')
    result=json.loads((ROOT/'examples/network_design/results.json').read_text())
    r=result['front'][0]
    assert network_map(d,r).data
    chart = tradeoff_plot(result['front'],r)
    assert chart.data
    assert all(trace.type == 'scatter' for trace in chart.data)
    assert chart.layout.yaxis.title.text == 'Expected disruption unmet demand (units/year)'
    assert all(set(design['objectives']) == {'cost','expected_unmet_demand'} for design in result['front'])
    assert len(r['opened_warehouses'])>0


def test_dashboard_displays_saved_network_without_solving():
    app=AppTest.from_file(str(ROOT/'app.py')).run(timeout=30)
    assert not app.exception
    assert len(app.metric)>=5
    assert any(x.label=='Design to inspect' for x in app.selectbox)
    assert any(x.label=='Operating scenario' for x in app.selectbox)


def test_custom_preferences_have_two_weights():
    app=AppTest.from_file(str(ROOT/'app.py')).run(timeout=30)
    preference=next(x for x in app.selectbox if x.label=='Preference')
    assert 'Greenest network' not in preference.options
    preference.select('Custom').run()
    assert not app.exception
    assert {s.label for s in app.slider if 'weight' in s.label} == {'Cost weight','Resilience weight'}


def test_dashboard_runs_nsga2():
    app=AppTest.from_file(str(ROOT/'app.py')).run(timeout=30)
    next(x for x in app.number_input if x.label=='GA population size').set_value(4)
    next(x for x in app.number_input if x.label=='GA generations').set_value(1)
    next(x for x in app.button if x.label=='Generate Pareto frontier').click().run(timeout=60)
    assert not app.exception
    assert app.session_state['results']['algorithm'] == 'nsga2'
    assert len(app.session_state['results']['history']) == 1
    assert len(app.metric) >= 5
