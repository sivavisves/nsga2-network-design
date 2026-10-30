# Synthetic network-design inputs

The two-objective model uses expected annual cost and expected disruption unmet demand. Both shipped inputs use **schema version 2** and require no external dataset:

| File | Plants | Warehouses | Customers | Arcs | Scenarios |
| --- | ---: | ---: | ---: | ---: | ---: |
| [example_instance.json](example_instance.json) | 3 | 12 | 30 | 396 | 10 |
| [tiny_instance.json](tiny_instance.json) | 1 | 2 | 2 | 6 | 2 |

The stored JSON is the source of truth for a demonstrated run. `example_instance.json` is generated with NumPy `default_rng(42)`; its annual customer demand totals 3,414 units. The tiny instance is explicitly specified for hand calculations.

## Schema and units

Top-level fields are `schema_version`, `seed`, `nodes`, `arcs` and `scenarios`; generated default inputs also include a `units` description. Node and arc IDs are unique. Each scenario describes an alternative condition for the same annual operating period.

| Record | Fields | Meaning and units |
| --- | --- | --- |
| Every node | `id`, `kind`, `x`, `y` | Kind is `plant`, `warehouse` or `customer`; coordinates are km |
| Plant | `supply` | Base annual supply, units/year |
| Warehouse | `capacity`, `fixed_cost` | Base throughput, units/year; annualized opening cost, USD/year |
| Customer | `demand` | Annual demand, units/year, identical across scenarios |
| Arc | `id`, `source`, `target`, `distance` | Directed eligible link; distance in km |
| Arc | `capacity`, `cost`, `fixed_cost` | Base capacity, units/year; variable cost, USD/unit; annualized activation cost, USD/year |
| Scenario | `id`, `name`, `probability` | Condition identifier, display name and probability |
| Scenario | `warehouse_availability`, `plant_fraction`, `arc_fraction` | Optional asset-ID-to-capacity-fraction maps |

An arc ID uses `source>target`. Only plant-to-warehouse and warehouse-to-customer arcs are allowed. All normal customer demand must be met; dropping normal demand is not a feasibility fallback.

For each scenario, multiply warehouse capacity by `warehouse_availability`, plant supply by `plant_fraction`, and link capacity by `arc_fraction`. Missing map entries mean full capacity (`1`). Fractions lie in `[0,1]`; zero represents a complete failure. The first scenario must have ID `normal`, positive probability and full asset availability. Fixed opening and activation costs are charged once per selected asset, regardless of the number of scenarios.

## Default generation and disruptions

All nodes lie in a synthetic 100-by-100 km region. Transportation cost follows Euclidean distance with seeded variation; fixed costs and capacities are heterogeneous. Total plant supply is 1.35 times demand. Normal arc capacities are at least total demand, aggregate warehouse throughput exceeds demand, and both eligible arc layers are complete. Opening all facilities and links therefore provides a feasible normal network for generated inputs. The CLI verifies feasibility before sampling.

Normal probability is 0.7. Nine disruptions share probability 0.3: four individual warehouse outages, one plant supply reduction, one transport-arc outage and three multi-asset disruptions. Scenario effects are applied through the fraction maps rather than by changing design decisions.

The validator checks schema version, IDs, allowed echelons, finite parameter values, positive node capacities/demands/costs, nonnegative arc capacities/costs, scenario probabilities and capacity fractions, and aggregate normal capacity. Aggregate capacity alone does not establish feasibility for a custom sparse network; a solve is still needed to verify connectivity and usable capacities.

To regenerate the default input and solve it, run from the repository root:

```sh
network-design --generate --instance data/example_instance.json --seed 42 \
  --plants 3 --warehouses 12 --customers 30 --scenarios 10 \
  --output results/regenerated --time-limit 8 --grid 21
```

The command regenerates the input file and performs the full frontier run. For data generation alone, use the Python API:

```python
from network_design import generate, save

save(generate(seed=42), "results/example_instance.json")
```

Schema version 2 removes the previous emissions fields. Existing locations, costs, capacities, demands and scenarios were preserved. The generator reserves the former random draws to reproduce those values. Schema-v1 inputs are rejected by the loader; update their schema and remove obsolete emission fields before reuse.

## Hand-checkable design

The tiny case has one plant with supply 10, two warehouses each with capacity 10, and demand `C1=4`, `C2=6`. Normal probability is 0.7; W1 fails in the disruption with probability 0.3. Every link has capacity 10, variable cost 1 and fixed activation cost 1. W1 opening costs 10 and W2 opening costs 20.

Open both warehouses and activate all six links. Send 10 from P1 through W1 in normal operations, delivering 4 to C1 and 6 to C2. During the W1 outage, use W2 for the same shipments. Warehouse opening costs are 30, link costs are 6, and expected shipment cost is `0.7 × 20 + 0.3 × 20 = 20`. The design has **cost 56** and **expected unmet demand 0**. This is a specified feasible design, not a simultaneous minimum of both objectives.

Cost alone instead opens only W1 and its three links. Fixed cost is `10 + 3`, normal shipping contributes `0.7 × 20`, and no shipments occur in the outage. Its **cost is 27** and **expected disruption unmet demand is 3** (`0.3 × 10`). Conditional unmet demand is 10 units/year, or 100% of total demand. These arithmetic checks are covered by the tests.

For the full formulation, see [the problem specification](../docs/sample_problem.md); for solved designs and exports, see [the saved demonstration](../examples/network_design/README.md).
