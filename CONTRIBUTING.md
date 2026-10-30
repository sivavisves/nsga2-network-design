# Contributing to the network-design application

The application implements the [two-objective specification](docs/sample_problem.md): minimize expected annual cost and expected disruption unmet demand. Modeling, data and interface changes should preserve the same annual planning horizon, shared network decisions and full normal-demand fulfillment.

## Development commands

From the repository root, activate a virtual environment and install the project:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e '.[test]'
pytest -q
streamlit run app.py
```

For an end-to-end solver/export/animation check on the tiny instance:

```sh
network-design --instance data/tiny_instance.json \
  --output results/tiny --time-limit 5 --mip-gap 0 --grid 5
```

Use a fresh output directory when changing inputs or solver settings. The default full instance uses 28 frontier attempts plus a preliminary feasibility check; use the tiny case for routine development rather than repeatedly regenerating the full demonstration.

## Module responsibilities

| File | Responsibility |
| --- | --- |
| `src/network_design/data.py` | Schema-v2 validation, seeded generation and JSON serialization |
| `src/network_design/model.py` | Shared facility/link decisions and scenario flow recourse; objective order is `cost`, `expected_unmet_demand` |
| `src/network_design/solve.py` | HiGHS configuration, incumbent extraction and solver metadata |
| `src/network_design/multiobjective.py` | Two anchors, two-weight scalarization, resilience-only epsilon grid and 2D nondominance |
| `src/network_design/reporting.py` | Independent flow/objective audit and JSON/CSV exports |
| `src/network_design/visualization.py` | Plotly network/frontier views and Matplotlib GIF/static preview |
| `src/network_design/cli.py` | Input generation, preliminary feasibility check and batch outputs |
| `app.py` | Streamlit interaction, result caching, comparisons and downloads |
| `tests/` | Data, arithmetic, solver, Pareto, persistence and dashboard checks |

Keep modeling logic outside the interface. The dashboard loads shipped results and must not solve on initial load or on every widget change. Cache keys and saved-result compatibility checks must identify the input and current objective configuration.

## Model and result conventions

Opening and link-activation decisions are shared across scenarios; shipments and unmet demand vary by scenario. Fixed costs are counted once. There is no shortfall penalty in cost, and normal unmet demand is fixed to zero. Resilience is unconditional probability-weighted disruption shortfall; conditional reporting metrics must not replace it in the optimized objective.

Weights follow the order `(cost, expected_unmet_demand)`, are nonnegative and sum to one. Default sampling uses five weight pairs and one grid of 21 shortfall bounds. Keep physical objective values separate from scalarized scores. Preserve solver termination, time, bounds and gap, including time limits and infeasible attempts; missing objectives must remain `None`, not zero. Do not label an incumbent or sampled frontier as a certified global solution.

Update the independent arithmetic and constraint checks when changing the model. The tiny hand-checkable design has cost 56 and loss 0; its cost-only optimum has cost 27 and loss 3. A model change must keep these expectations valid or explicitly revise the input and documented calculations.

## Inputs, generated artifacts and documentation

Inputs and result archives use schema version 2. The input guide is [data/README.md](data/README.md). The generator preserves existing cost/capacity/location/disruption values by reserving the former random draws; avoid changing this sequence accidentally. Update the schema and compatibility behavior deliberately when making incompatible changes.

`examples/network_design/` holds the audited demonstration; `results/` is for local output. Regenerate examples only when model, inputs or visualization changes require it, and inspect GIF frames after rendering. Replace obsolete design folders when publishing a replacement sample. Keep its [artifact guide](examples/network_design/README.md), the [README](README.md), [specification](docs/sample_problem.md) and [validation record](VALIDATION.md) consistent with the actual saved files. Numerical changes and visual-only changes should be documented according to what they affect.

The [Python CI workflow](.github/workflows/python.yml) installs on Python 3.11, runs pytest, and generates a tiny-instance frontier and GIF with a five-point resilience grid. Local checks do not establish that a remote CI run has passed.
