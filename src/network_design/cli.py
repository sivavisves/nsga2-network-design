"""Batch entry point: generate, solve, export and animate the default instance."""
import argparse
from pathlib import Path
from .data import generate, load, save
from .solve import solve
from .multiobjective import frontier, usable
from .reporting import persist
from .visualization import animate


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--instance", default="data/example_instance.json")
    p.add_argument("--output", default="results/network_design")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--plants", type=int, default=3)
    p.add_argument("--warehouses", type=int, default=12)
    p.add_argument("--customers", type=int, default=30)
    p.add_argument("--scenarios", type=int, default=10)
    p.add_argument("--generate", action="store_true", help="Regenerate the instance at --instance")
    p.add_argument("--population-size", type=int, default=48)
    p.add_argument("--generations", type=int, default=40)
    p.add_argument("--mutation-rate", type=float, default=None)
    p.add_argument("--crossover-rate", type=float, default=0.9)
    p.add_argument("--time-limit", type=float, default=15)
    p.add_argument("--mip-gap", type=float, default=0.01)
    p.add_argument("--no-gif", action="store_true")
    args = p.parse_args()
    if args.generate or not Path(args.instance).exists():
        save(generate(args.seed,args.plants,args.warehouses,args.customers,args.scenarios),args.instance)
    d = load(args.instance)
    # Preliminary feasibility check uses the exact normal-demand constraints.
    check = solve(d,time_limit=args.time_limit,mip_gap=args.mip_gap)
    if not usable(check):
        raise SystemExit(f"Preliminary normal-operation feasibility check failed: {check['solver']}")
    print("Normal operation feasibility verified; zero unmet demand.",flush=True)
    def progress(i,n,r):
        print(f'{i}/{n} {r["method"]}: {r["solver"]["termination_condition"]}; gap={r["solver"]["gap"]}; {r["objectives"]}',flush=True)
    results = frontier(d,population_size=args.population_size,generations=args.generations,seed=args.seed,mutation_rate=args.mutation_rate,crossover_rate=args.crossover_rate,time_limit=args.time_limit,mip_gap=args.mip_gap,progress=progress)
    persist(d,results,args.output)
    # Bundle the exact input with every output archive.
    save(d,Path(args.output)/"instance.json")
    if not args.no_gif:
        animate(d,results,Path(args.output)/"network_tradeoffs.gif")
    print(f'{len(results["front"])} nondominated designs saved to {args.output}',flush=True)


if __name__ == "__main__":
    main()
