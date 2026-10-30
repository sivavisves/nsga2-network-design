> Architecture update: the default frontier search now uses NSGA-II to evolve facility/link decisions and dispatch preferences. The mathematical constraints below also define the fixed-network dispatch LP used to evaluate each chromosome. MILP scalarization methods remain available as benchmarks. See the root README for genetic operators and configuration.

# Two-objective facility location and transportation-network design

Build a reproducible Python application that chooses warehouses and shipping links, then adapts shipments to disruptions. Minimize **expected annual cost** and **expected disruption unmet demand**. The implementation uses Pyomo + open-source HiGHS, seeded synthetic data, Plotly + Streamlit, and pytest. No external dataset or paid solver is required. See [the main README](../README.md) for installation, [the input guide](../data/README.md) for the JSON schema, and [the saved demonstration](../examples/network_design/README.md) for results and exports.

## Scenario and dimensions

A retailer ships a single product through three directed echelons:

`Manufacturing plants -> Candidate warehouses -> Customer zones`

The default instance has 3 plants, 12 candidate warehouses, 30 customer zones, all 36 plant-to-warehouse arcs, all 360 warehouse-to-customer arcs, and 10 scenarios (1 normal and 9 disruptions). No direct plant-to-customer shipping is allowed.

Every scenario represents the same annual operating period under an alternative condition. Warehouse-opening and link-activation decisions are shared by all scenarios. Shipments and unmet demand adapt by scenario. Fixed costs are charged once, not multiplied by the number of scenarios.

## Sets and parameters

- `P`, `W`, `C`: plants, candidate warehouses and customer zones.
- `A_PW`, `A_WC`: eligible directed shipping arcs; `A` is their union.
- `Omega`: scenarios; scenario `0` denotes normal operations.
- `Omega_D = Omega \ {0}`: disruptions. In JSON and Python, normal scenario `0` is represented by the string ID `normal`; other scenarios have unique string IDs.
- `F[w]`: annualized warehouse opening cost [USD/year].
- `K[i,j]`: annualized link activation cost [USD/year].
- `U[w]`: warehouse throughput capacity [units/year].
- `S[p,s]`: plant supply in a scenario [units/year].
- `D[c]`: customer demand, constant across scenarios [units/year].
- `L[i,j,s]`: available arc transport capacity in a scenario [units/year].
- `avail[w,s]`: available warehouse capacity fraction in `[0,1]`.
- `t[i,j]`: transportation cost [USD per shipped unit].
- `pi[s]`: nonnegative scenario probability, summing to 1.

All capacities, supplies and demands are annualized. Coordinates and Euclidean distances are measured in km. There are no emissions parameters or objective in this version.

## Decisions

First-stage network design:

- `y[w] in {0,1}`: warehouse opened.
- `z[i,j] in {0,1}`: eligible link activated.

Second-stage scenario recourse:

- `x[i,j,s] >= 0`: shipment [units/year].
- `u[c,s] >= 0`: unmet customer demand [units/year].

Only eligible arcs receive design and flow variables. The same `y` and `z` apply across all scenarios.

## Two objectives, both minimized

Expected annual cost:

\[
C=\sum_{w\in W}F_wy_w+\sum_{(i,j)\in A}K_{ij}z_{ij}
 +\sum_{s\in\Omega}\pi_s\sum_{(i,j)\in A}t_{ij}x_{ijs}.
\]

Expected disruption unmet demand:

\[
R=\sum_{s\in\Omega_D}\pi_s\sum_{c\in C}u_{cs}.
\]

`R` is an **unconditional probability-weighted** shortfall [units/year]. For interpretation, also report conditional disruption shortfall `R / sum(pi[s] for disruption s)` and its percentage of total customer demand, when disruption probability is positive. Optimize `R`, not the derived percentage. The resilience measure describes expected service loss, not worst-case reliability.

Do not add an unmet-demand penalty to cost. Consequently, a cost-only design may intentionally serve no disruption demand to avoid transportation costs. The second objective or a resilience bound controls service during disruptions.

## Constraints

Plant supply, for every plant and scenario:

\[
\sum_{w:(p,w)\in A_{PW}}x_{pws}\le S_{ps}.
\]

Warehouse flow conservation, for every warehouse and scenario:

\[
\sum_{p:(p,w)\in A_{PW}}x_{pws}
=\sum_{c:(w,c)\in A_{WC}}x_{wcs}.
\]

Warehouse throughput and disruption availability:

\[
\sum_{c:(w,c)\in A_{WC}}x_{wcs}\le U_w\,avail_{ws}\,y_w.
\]

Normal availability is 1; a complete warehouse failure has availability 0. Warehouses have no inventory.

Arc activation and scenario capacity:

\[
0\le x_{ijs}\le L_{ijs}z_{ij}.
\]

Set available transport capacity to zero for a failed arc.

Customer demand balance in every scenario:

\[
\sum_{w:(w,c)\in A_{WC}}x_{wcs}+u_{cs}=D_c.
\]

All normal demand must be served:

\[
u_{c0}=0\quad\forall c\in C.
\]

Links can only be activated at opened warehouses:

\[
z_{pw}\le y_w,\qquad z_{wc}\le y_w.
\]

## Multiobjective solution methods

First solve the cost and resilience objectives separately under the same constraints. Evaluate both objectives at both solutions to form a 2-by-2 payoff table. For each objective use the minimum observed value as the ideal value and the maximum minus minimum as its normalization range. If an anchor has a nonzero solver gap or is time-limited, label ideal values and ranges as incumbent estimates. An effectively zero observed range is reported as non-varying and contributes zero to the normalized score.

### Normalized weighted sums

For nonnegative weights `(lambda_C, lambda_R)` summing to 1, solve:

\[
\min\ \lambda_C\frac{C-C^*}{\max(range_C,10^{-9})}
 +\lambda_R\frac{R-R^*}{\max(range_R,10^{-9})}.
\]

Include cheapest `(1,0)`, most resilient `(0,1)`, balanced `(0.5,0.5)`, and custom preferences. The default weight grid uses increments of 0.25: `(0,1)`, `(0.25,0.75)`, `(0.5,0.5)`, `(0.75,0.25)` and `(1,0)`. Weights follow the order `(cost, expected_unmet_demand)`. Custom dashboard weights are normalized to sum to one.

### Epsilon constraints

Minimize cost subject to a disruption-loss limit:

\[
\min C\qquad\text{subject to }R\le\epsilon_R
\quad\text{and all network constraints.}
\]

Use a configurable one-dimensional grid of 21 resilience thresholds by default, spanning the resilience values in the two-anchor payoff table. A complete default sample therefore contains 2 individual solves, 5 weighted solves and 21 epsilon solves: 28 frontier attempts. The CLI additionally runs a preliminary feasibility solve, outside the frontier attempt count. `--grid` controls the number of resilience thresholds, not a two-dimensional grid.

Record infeasible thresholds and time limits explicitly. Do not extract objectives from missing solutions. Filter the union of feasible samples to keep unique, nondominated two-objective vectors within numerical tolerances. Design `a` dominates `b` if it is no worse in cost and shortfall and strictly better in at least one. The current implementation does not apply a lexicographic tie-break. A pure resilience optimum may therefore include unused facilities, excess links or arbitrary recourse with the same optimal shortfall; cost-aware sampling can find cheaper designs with that shortfall.

Call the result an **approximate sampled Pareto frontier**. Weighted sums can miss unsupported MILP solutions, finite epsilon sampling can miss other efficient decisions, and time-limited incumbents do not certify global Pareto optimality. Preserve solver status, termination condition, scalar objective bounds/gap, runtime and independent feasibility diagnostics for every attempt.

## Synthetic data and reproducibility

Use seed 42 and configurable positive counts of plants, warehouses, customers and scenarios. Generate 2D positions in a 100-by-100 km region, positive customer demands and warehouse capacities, heterogeneous fixed costs, and transportation costs proportional to distance with seeded variation. Provide enough normal supply, throughput and transport capacity for a known feasible normal network; verify it with a preliminary solve.

Default normal probability is 0.7; disruptions sum to 0.3. Include individual warehouse outages, a plant supply reduction, an arc outage and multi-asset disruptions. Modify warehouse availability, plant supply and arc capacity through scenario fractions. Do not force particular Pareto outcomes.

Ship `data/example_instance.json` and a hand-checkable `data/tiny_instance.json`, with schema version 2 and documented units. Schema-v1 inputs must be updated before loading. Preserve the existing non-emission inputs when migrating from the previous formulation. Store the exact input with each batch result. Solver time limits can affect reproducibility across machines; saved decisions are the demonstrated results.

## Interface and outputs

The Streamlit dashboard must provide:

- Network maps showing plants, opened/closed warehouses, customers and activated links, with hover information and scenario flow widths.
- A normal/disruption selector and fulfilled-demand, unmet-demand and aggregate-arc-flow metrics.
- Two objective KPIs and a selectable **2D cost-versus-expected-unmet-demand** scatter plot linked to the inspected network.
- Two weighted-sum controls and one resilience epsilon bound with clear units.
- Per-scenario analysis, opened-facility/link tables, and comparison of at least two designs.
- Solver diagnostics, warnings and formulation dimensions.
- CSV exports for metrics, facility/link decisions, scenario flows, shortfalls and scenario statistics; JSON/ZIP result exports.

The default CLI/dashboard configuration is a 15-second time limit per solve and 1% relative MIP gap; the shipped demonstration uses 8 seconds. Both values are configurable.

Use explicit Solve selected design and Generate Pareto frontier buttons. Cache completed solves by input and configuration; do not solve on every widget change. Load the shipped results immediately without solving.

The GIF must show the cost/resilience frontier on the left and each selected network allocation on the right. Highlight the matching point and tour designs under normal operations and their worst sampled disruptions. Distinguish sampling progress from the final tour. Include physical cost and shortfall values and label the frontier as sampled.

Keep input generation, modeling, solving, multiobjective methods, independent reporting, visualization and the interface in separate modules. Each returned design includes its ID, method/settings, two unscaled objective values, solver metadata, opened warehouses, activated arcs, scenario shipments/shortfalls and validation diagnostics.

## Tests and acceptance

From the repository root in an activated virtual environment, run `pip install -e '.[test]'`, `pytest -q`, and `streamlit run app.py`. Batch generation is available through `network-design`.

Tests must verify probabilities and seeded inputs, full normal demand, warehouse conservation, all capacities, link/facility activation, shared first-stage decisions, zero throughput at failed warehouses, independently recomputed cost and shortfall, two-dimensional dominance and duplicate filtering, individual objective optima on a tiny exact case, valid two-weight scalarizations, resilience-only epsilon constraints, clean infeasibility handling, result exports, and loading the saved dashboard. Reject attempts to optimize or bound the removed objective.

The tiny feasible design opens both warehouses and all six arcs, sends normal shipments through W1, and switches all flow to W2 during its W1 outage. Its cost is 56 and expected unmet demand is 0. The cost-only optimum instead opens W1, costs 27 and has expected disruption unmet demand 3.

Deliver the working solver, schema-v2 sample inputs, interactive dashboard, newly sampled two-objective frontier, GIF, tests and clear local run instructions. Scope remains one product, no inventory, no direct plant-customer links, no capacity expansion and no warehouse construction lead times.

## Python API and result contract

A small exact cost-only solve:

```python
from network_design import solve, tiny_instance

result = solve(tiny_instance(), objective="cost", time_limit=5, mip_gap=0)
assert result["diagnostics"]["feasible"]
print(result["objectives"])  # cost=27, expected_unmet_demand=3
```

To solve a balanced normalized preference, first establish the payoff table:

```python
from network_design import anchors, tiny_instance, weighted

data = tiny_instance()
normalization = anchors(data, time_limit=5, mip_gap=0)
result = weighted(data, (0.5, 0.5), normalization, time_limit=5, mip_gap=0)
```

The objective names, in order, are `cost` and `expected_unmet_demand`. The removed emissions objective and bounds are rejected; weights must contain exactly two nonnegative finite entries summing to one. `frontier(data, grid=21, time_limit=15, mip_gap=0.01)` samples both methods and returns schema version 2 with `objective_keys`, `normalization`, `config`, `attempts` and `front`.

Each feasible solve record contains the method/settings, physical `objectives`, solver metadata, model dimensions, opened warehouses, activated arcs, scenario shipments/shortfalls and independent `diagnostics`. No-incumbent outcomes have `objectives=None` and an explicit reason. Only audited feasible records participate in nondominance filtering. Solver bounds/gaps for weighted sums refer to the normalized scalar objective, rather than cost in USD.

The dashboard ZIP includes the instance, results and exported design tables. Batch outputs contain JSON plus one metrics/facilities/links/flows/unmet/scenarios CSV set for each filtered design; see [the artifact guide](../examples/network_design/README.md). Local test and full-run evidence are recorded in [VALIDATION.md](../VALIDATION.md).
