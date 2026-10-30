"""Launch from the repository root: streamlit run app.py."""
import hashlib
import io
import json
from pathlib import Path
import zipfile
import pandas as pd
import streamlit as st
from network_design.data import generate, load
from network_design.model import KEYS
from network_design.multiobjective import anchors, frontier, weighted, usable
from network_design.solve import solve
from network_design.reporting import csv_text, tables
from network_design.visualization import network_map, tradeoff_plot, LABELS

ROOT = Path(__file__).resolve().parent
st.set_page_config(page_title="Network trade-offs",page_icon="◈",layout="wide")
st.title("Network design: cost & disruption resilience")
st.caption("NSGA-II genetic network search · scenario dispatch LPs · synthetic annual data")

@st.cache_data
def cached_anchors(d,time_limit,gap):
    return anchors(d,time_limit=time_limit,mip_gap=gap)

@st.cache_data
def cached_frontier(d,time_limit,gap,population,generations,search_seed):
    return frontier(d,population_size=population,generations=generations,seed=search_seed,time_limit=time_limit,mip_gap=gap)

@st.cache_data
def cached_selected(d,time_limit,gap,method,weights,bounds):
    if method == "Weighted sum":
        return weighted(d,weights,cached_anchors(d,time_limit,gap),time_limit=time_limit,mip_gap=gap)
    return solve(d,bounds=bounds,time_limit=time_limit,mip_gap=gap)

with st.sidebar:
    st.header("Instance")
    source = st.selectbox("Data",["Shipped example","Generate synthetic"])
    if source == "Shipped example":
        d = load(ROOT/"data/example_instance.json")
    else:
        seed = st.number_input("Seed",0,100000,42)
        plants = st.number_input("Plants",1,10,3)
        warehouses = st.number_input("Warehouses",1,25,12)
        customers = st.number_input("Customers",1,60,30)
        scenarios = st.number_input("Scenarios",2,20,10)
        d = generate(seed,plants,warehouses,customers,scenarios)
    st.header("Solver")
    time_limit = st.number_input("Time limit per MILP (seconds)",1,600,15)
    gap = st.number_input("Relative MIP gap",0.0,0.5,0.01,0.005,format="%.3f")
    population = st.number_input("GA population size",4,200,48)
    generations = st.number_input("GA generations",1,200,40)
    search_seed = st.number_input("GA random seed",0,100000,42)
    st.caption("NSGA-II uses tournament selection, crossover, mutation, and elitist survival. Fixed-network LPs evaluate outage dispatch.")
    st.download_button("Download instance JSON",json.dumps(d,indent=2),"instance.json")

key = hashlib.sha256(json.dumps(dict(instance=d,objectives=KEYS),sort_keys=True).encode()).hexdigest()
if st.session_state.get("instance_key") != key:
    st.session_state.instance_key = key
    st.session_state.results = None
    st.session_state.extra = []
    if source == "Shipped example":
        sample = ROOT/"examples/network_design/results.json"
        sample_instance = ROOT/"examples/network_design/instance.json"
        if sample.exists() and sample_instance.exists() and json.loads(sample_instance.read_text())==d:
            loaded = json.loads(sample.read_text())
            if loaded.get("objective_keys") == list(KEYS):
                st.session_state.results = loaded
                # Historical samples remain viewable and explicitly labeled.

with st.expander("Run NSGA-II or solve a MILP benchmark",expanded=st.session_state.results is None):
    method = st.radio("MILP benchmark scalarization",["Weighted sum","Epsilon constraints"],horizontal=True)
    preset = st.selectbox("Preference",["Balanced network","Cheapest network","Most resilient network","Custom"])
    presets = {"Balanced network":(0.5,0.5),"Cheapest network":(1,0),"Most resilient network":(0,1)}
    if preset == "Custom":
        cols = st.columns(2)
        raw = [cols[i].slider(f"{name} weight",0.0,1.0,0.5,0.01) for i,name in enumerate(["Cost","Resilience"])]
        weights = tuple(v/sum(raw) for v in raw) if sum(raw)>0 else (0.5,0.5)
        st.caption(f"Normalized weights: {weights[0]:.3f}, {weights[1]:.3f}")
    else:
        weights = presets[preset]
    results = st.session_state.results
    norm = results["normalization"] if results and results["normalization"]["records"] else None
    if method == "Epsilon constraints" and norm is None:
        st.info("Generate the frontier first to establish objective-based epsilon bounds.")
    bounds = {}
    if norm:
        upper = {k:max(r["objectives"][k] for r in norm["records"]) for k in KEYS}
        for k in ["expected_unmet_demand"]:
            low,high = float(norm["ideal"][k]),float(upper[k])
            if high-low>1e-8:
                bounds[k] = st.slider(LABELS[k]+" upper bound",low,high,high)
            else:
                bounds[k] = high
                st.caption(f"{LABELS[k]}: non-varying observed anchor range ({high:,.2f})")
    c1,c2 = st.columns(2)
    if c1.button("Solve selected design",disabled=method=="Epsilon constraints" and norm is None):
        try:
            with st.spinner("Solving selected design…"):
                r = cached_selected(d,time_limit,gap,method,weights,bounds)
            st.session_state.extra.append(r)
            if not usable(r):
                st.warning(f'No feasible incumbent: {r["solver"]["termination_condition"]}')
        except (RuntimeError,ValueError) as exc:
            st.error(str(exc))
    if c2.button("Generate Pareto frontier"):
        try:
            with st.spinner("Evolving network designs with NSGA-II…"):
                st.session_state.results = cached_frontier(d,time_limit,gap,population,generations,search_seed)
        except (RuntimeError,ValueError) as exc:
            st.error(str(exc))

results = st.session_state.results
if results and results.get("algorithm") != "nsga2":
    st.info("Viewing historical MILP samples. Generate Pareto frontier to run NSGA-II.")
all_records = (results["attempts"] if results else [])+st.session_state.extra
pool = (results["front"] if results else [])+[r for r in st.session_state.extra if usable(r)]
records = list({r["design_id"]:r for r in pool}.values())
if not records:
    st.info("Choose Solve selected design or Generate Pareto frontier to begin.")
    st.stop()
lookup = {r["design_id"]:r for r in records}
if "pending_design" in st.session_state:
    st.session_state.design_selection = st.session_state.pop("pending_design")
if st.session_state.get("design_selection") not in lookup:
    st.session_state.design_selection = records[0]["design_id"]
id_selected = st.selectbox("Design to inspect",list(lookup),key="design_selection",format_func=lambda i:f'{i} · {lookup[i]["method"]} · ${lookup[i]["objectives"]["cost"]:,.0f}')
r = lookup[id_selected]
cols = st.columns(2)
for col,k in zip(cols,KEYS):
    col.metric(LABELS[k],f'{r["objectives"][k]:,.1f}')
st.caption(f'Conditional disruption unmet demand: {r["diagnostics"]["conditional_unmet_demand"]:,.1f} units/year ({r["diagnostics"]["conditional_unmet_percent"]:.2f}% of demand). Optimized loss above is unconditional probability weighted.')
network_tab,tradeoff_tab,scenario_tab,diagnostics_tab = st.tabs(["Network design","Objective trade-offs","Scenarios & comparison","Diagnostics & exports"])
with network_tab:
    sid = st.selectbox("Operating scenario",[s["id"] for s in d["scenarios"]],format_func=lambda i:next(s["name"] for s in d["scenarios"] if s["id"]==i))
    stat = next(s for s in r["diagnostics"]["scenarios"] if s["scenario"]==sid)
    c1,c2,c3 = st.columns(3)
    c1.metric("Fulfilled demand (units/year)",f'{stat["fulfilled_demand"]:,.1f}')
    c2.metric("Unmet demand (units/year)",f'{stat["unmet_demand"]:,.1f}')
    c3.metric("Aggregate arc flow (units/year)",f'{stat["aggregate_arc_flow"]:,.1f}')
    st.caption("Arc flow sums both transport legs. Gray warehouses are closed; red warehouses have failed. Solid lines carry flow; dotted activated links carry zero flow.")
    st.plotly_chart(network_map(d,r,sid),use_container_width=True)
with tradeoff_tab:
    st.caption("Approximate Pareto frontier. New searches use NSGA-II; global optimality and completeness are not certified. Select a point to inspect its network.")
    event = st.plotly_chart(tradeoff_plot(records,r),use_container_width=True,on_select="rerun",key="frontier_selection")
    points = event.selection.points
    if points:
        chosen = points[-1].get("customdata")
        if isinstance(chosen,list):
            chosen=chosen[0]
        if chosen in lookup and chosen!=id_selected and st.session_state.get("last_clicked")!=chosen:
            st.session_state.last_clicked=chosen
            # A callback-free rerun applies this before creating the selectbox.
            st.session_state.pending_design=chosen
            st.rerun()

with scenario_tab:
    st.dataframe(pd.DataFrame(r["diagnostics"]["scenarios"]),hide_index=True,width="stretch")
    st.bar_chart(pd.DataFrame(r["diagnostics"]["scenarios"]).set_index("name")[["unmet_demand"]])
    compare = st.multiselect("Compare designs",list(lookup),default=list(lookup)[:2])
    st.dataframe(pd.DataFrame([dict(design=i,**lookup[i]["objectives"],conditional_unmet_percent=lookup[i]["diagnostics"]["conditional_unmet_percent"],warehouses=len(lookup[i]["opened_warehouses"]),links=len(lookup[i]["activated_arcs"])) for i in compare]).set_index("design").T if compare else pd.DataFrame(),width="stretch")
    ts = tables(d,r)
    st.write("Opened warehouses")
    st.dataframe([x for x in ts["facilities"] if x["opened"]],hide_index=True)
    st.write("Activated links")
    st.dataframe([x for x in ts["links"] if x["activated"]],hide_index=True)
with diagnostics_tab:
    st.json(dict(solver=r["solver"],dimensions=r["dimensions"],settings=r["settings"],validation=r["diagnostics"]["violations"]))
    if results:
        for warning in results["normalization"]["warnings"]:
            st.warning(warning)
        if results["normalization"]["nonvarying"]:
            st.info("Non-varying observed objectives: "+", ".join(results["normalization"]["nonvarying"]))
    for attempt in all_records:
        if not usable(attempt) or attempt["solver"]["termination_condition"]!="optimal":
            st.warning(f'{attempt["design_id"]}: {attempt["solver"]["termination_condition"]}; incumbent={attempt["solver"]["has_incumbent"]}')
    st.dataframe([dict(design=a["design_id"],method=a["method"],**a["solver"]) for a in all_records],hide_index=True)
    for name,rows in tables(d,r).items():
        st.download_button(f"Export {name} CSV",csv_text(rows),f'{r["design_id"]}_{name}.csv',mime="text/csv")
    archive=io.BytesIO()
    with zipfile.ZipFile(archive,"w",zipfile.ZIP_DEFLATED) as z:
        z.writestr("instance.json",json.dumps(d,indent=2))
        z.writestr("results.json",json.dumps(results or dict(front=records),indent=2))
        for design in records:
            for name,rows in tables(d,design).items():
                z.writestr(f'{design["design_id"]}/{name}.csv',csv_text(rows))
    st.download_button("Export all results (ZIP)",archive.getvalue(),"network_design_results.zip",mime="application/zip")
