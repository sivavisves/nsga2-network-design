"""Plotly dashboard charts and a deterministic two-panel teaching animation."""
import numpy as np
import plotly.graph_objects as go
from .model import KEYS

LABELS = {"cost":"Expected annual cost (USD)", "expected_unmet_demand":"Expected disruption unmet demand (units/year)"}
COLORS = {"plant":"#213e72", "warehouse":"#ef872f", "customer":"#1c9c93"}


def network_map(d,r,scenario="normal"):
    nodes = {n["id"]:n for n in d["nodes"]}
    scenarios = {s["id"]:s for s in d["scenarios"]}
    s = scenarios[scenario]
    fig = go.Figure()
    flow = r["shipments"][scenario]
    largest = max(max(flow.values()),1)
    for a in d["arcs"]:
        if a["id"] not in r["activated_arcs"]:
            continue
        n1,n2 = nodes[a["source"]],nodes[a["target"]]
        x = flow[a["id"]]
        fig.add_trace(go.Scatter(x=[n1["x"],n2["x"]], y=[n1["y"],n2["y"]], mode="lines", line=dict(width=0.5+5*x/largest,color="#4988bc" if x>1e-6 else "#c9cfd5",dash="solid" if x>1e-6 else "dot"), showlegend=False,
                                 text=f'{a["id"]} (directed)<br>Flow: {x:.1f} units/year<br>Available capacity: {a["capacity"]*s.get("arc_fraction",{}).get(a["id"],1):.1f}<br>Variable cost: ${a["cost"]:.2f}/unit<br>Activation: ${a["fixed_cost"]:.0f}/year', hoverinfo="text"))
    for kind,symbol in [("plant","triangle-up"),("warehouse","square"),("customer","circle")]:
        ns = [n for n in d["nodes"] if n["kind"]==kind]
        text = []
        for n in ns:
            desc = f'{n["id"]} · {kind}'
            if kind == "warehouse":
                desc += f'<br>{"Opened" if n["id"] in r["opened_warehouses"] else "Closed"}<br>Available capacity: {n["capacity"]*s.get("warehouse_availability",{}).get(n["id"],1):.1f}<br>Opening: ${n["fixed_cost"]:.0f}/year'
            elif kind == "plant":
                desc += f'<br>Available supply: {n["supply"]*s.get("plant_fraction",{}).get(n["id"],1):.1f}'
            else:
                desc += f'<br>Demand: {n["demand"]}<br>Unmet: {r["unmet_demand"][scenario][n["id"]]:.1f}'
            text.append(desc)
        fig.add_trace(go.Scatter(x=[n["x"] for n in ns], y=[n["y"] for n in ns], mode="markers+text", text=[n["id"] for n in ns], textposition="top center",textfont=dict(size=9), hovertext=text, hoverinfo="text",name=kind.title(),
                                 marker=dict(symbol=symbol,size=12 if kind!="customer" else 7,color=["#d5d8dd" if kind=="warehouse" and n["id"] not in r["opened_warehouses"] else "#d84646" if kind=="warehouse" and s.get("warehouse_availability",{}).get(n["id"],1)==0 else COLORS[kind] for n in ns],line=dict(width=1,color="white"))))
    fig.update_layout(title=s["name"],xaxis_title="x (km)",yaxis_title="y (km)",height=600,margin=dict(l=10,r=10,t=50,b=10),legend=dict(orientation="h"))
    fig.update_yaxes(scaleanchor="x",scaleratio=1,range=[-7,107])
    fig.update_xaxes(range=[-7,107])
    return fig


def tradeoff_plot(records, selected=None):
    fig = go.Figure()
    for method in sorted({r["method"] for r in records}):
        rows = [r for r in records if r["method"]==method]
        fig.add_trace(go.Scatter(
            x=[r["objectives"]["cost"] for r in rows],
            y=[r["objectives"]["expected_unmet_demand"] for r in rows],
            mode="markers", name=method, customdata=[r["design_id"] for r in rows],
            hovertemplate="%{customdata}<br>Cost: $%{x:,.0f}/year<br>Expected disruption unmet: %{y:,.1f} units/year<extra></extra>",
            marker=dict(size=10)))
    if selected:
        o = selected["objectives"]
        fig.add_trace(go.Scatter(x=[o["cost"]],y=[o["expected_unmet_demand"]],mode="markers",
            marker=dict(size=17,color="#ef872f",symbol="star"),name="Selected design",
            customdata=[selected["design_id"]]))
    fig.update_layout(xaxis_title=LABELS["cost"],yaxis_title=LABELS["expected_unmet_demand"],height=520)
    return fig


def animate(d,results,path,fps=3):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.animation import FuncAnimation, PillowWriter
    from matplotlib.lines import Line2D
    from .multiobjective import usable, nondominated
    front = results["front"]
    evolutionary = results.get("algorithm") == "nsga2"
    if not front:
        raise ValueError("Cannot animate an empty frontier")
    nodes = {n["id"]:n for n in d["nodes"]}
    attempts = results["attempts"]
    good = [r for r in attempts if usable(r)]
    # Hold endpoints and a representative spread of final tradeoffs.
    choices = [front[i] for i in sorted(set(np.linspace(0,len(front)-1,min(12,len(front))).round().astype(int)))]
    # Show generation checkpoints, not thousands of near-identical evaluations.
    counts = sorted(set(np.linspace(min(2,len(attempts)),len(attempts),min(28,len(attempts))).round().astype(int)))
    checkpoint_fronts, archive, previous = {}, [], 0
    for count in counts:
        archive = nondominated(archive+attempts[previous:count])
        checkpoint_fronts[count] = archive
        previous = count
    frames = [("sampling", i, None, "normal") for i in counts]
    frames += [("tour",len(attempts),r,s["id"]) for r in choices for s in [d["scenarios"][0],max(d["scenarios"][1:], key=lambda s:sum(r["unmet_demand"][s["id"]].values()))]]
    frames += [frames[-1]]*4
    fig = plt.figure(figsize=(15,6.8),facecolor="#fbfcfe")
    left = fig.add_axes([0.08,0.15,0.40,0.67])
    right = fig.add_axes([0.55,0.15,0.41,0.67])
    low = np.min([[r["objectives"][k] for k in KEYS[:2]] for r in good],axis=0)
    high = np.max([[r["objectives"][k] for k in KEYS[:2]] for r in good],axis=0)
    span = np.maximum(high-low,1)
    final_values = np.array([[r["objectives"][k] for k in KEYS[:2]] for r in front])
    final_low, final_high = final_values.min(axis=0), final_values.max(axis=0)
    final_span = np.maximum(final_high-final_low,1)
    def update(frame):
        phase,count,selected,sid = frame
        left.clear(); right.clear()
        seen = [r for r in attempts[:count] if usable(r)]
        current = checkpoint_fronts[count]
        if selected is None:
            values = np.array([[r["objectives"][k] for k in KEYS] for r in current])
            scaled = (values-values.min(axis=0))/np.maximum(np.ptp(values,axis=0),1)
            selected = current[int(np.argmin(np.sum(scaled**2,axis=1)))]
        if seen and phase=="sampling":
            left.scatter([r["objectives"]["cost"] for r in seen],[r["objectives"]["expected_unmet_demand"] for r in seen],s=22,c="#cbd1db",alpha=0.15,label="Feasible samples")
        shown = current if phase=="sampling" else front
        left.scatter([r["objectives"]["cost"] for r in shown],[r["objectives"]["expected_unmet_demand"] for r in shown],c="#3477c9",s=48,edgecolors="#24324a",linewidths=0.6,label="Nondominated samples",zorder=3)
        o=selected["objectives"]
        left.scatter(o["cost"],o["expected_unmet_demand"],marker="*",s=260,c="#ff9b37",edgecolor="#1c2d45",zorder=4,label="Network shown")
        lo,hi,delta = (low,high,span) if phase=="sampling" else (final_low,final_high,final_span)
        left.set(xlim=(lo[0]-.08*delta[0],hi[0]+.08*delta[0]),ylim=(lo[1]-.08*delta[1],hi[1]+.08*delta[1]),xlabel="Expected annual cost (USD)",ylabel="Expected disruption unmet demand (units/year)",title=(f'NSGA-II · generation {attempts[count-1]["settings"].get("generation",0)} · {len(current)} frontier designs' if evolutionary else f'Sampling: {count}/{len(attempts)} solves') if phase=="sampling" else "Trade-off tour · final approximate frontier")
        left.ticklabel_format(style="sci",axis="both",scilimits=(0,0))
        left.grid(alpha=.15); left.legend(loc="upper right",fontsize=8)
        s = next(s for s in d["scenarios"] if s["id"]==sid)
        flow = selected["shipments"][sid]
        largest = max(max(flow.values()),1)
        for a in d["arcs"]:
            if a["id"] not in selected["activated_arcs"]:
                continue
            n1,n2=nodes[a["source"]],nodes[a["target"]]
            x = flow[a["id"]]
            if x<=1e-6:
                continue
            right.annotate("",xy=(n2["x"],n2["y"]),xytext=(n1["x"],n1["y"]),arrowprops=dict(arrowstyle="->",lw=.4+2.4*x/largest,color="#327db0",alpha=.5,shrinkA=4,shrinkB=4))
        for kind,marker in [("plant","^"),("warehouse","s"),("customer","o")]:
            for n in d["nodes"]:
                if n["kind"]!=kind:
                    continue
                opened = kind!="warehouse" or n["id"] in selected["opened_warehouses"]
                failed = kind=="warehouse" and s.get("warehouse_availability",{}).get(n["id"],1)==0
                color = "#d84646" if failed else COLORS[kind] if opened else "#e4e6eb"
                size = 100 if kind!="customer" else 30
                right.scatter(n["x"],n["y"],marker=marker,s=size,c=color,edgecolors="#333c4d",linewidths=.5,zorder=4)
                if failed:
                    right.scatter(n["x"],n["y"],marker="x",s=120,c="#842626",zorder=5)
        placed = []
        for n in sorted(d["nodes"],key=lambda n:({"plant":0,"warehouse":1,"customer":2}[n["kind"]],n["id"])):
            for dx,dy in [(1.1,1.8),(1.1,-2.8),(-4.5,1.8),(-4.5,-2.8),(1.1,4.8),(-4.5,4.8),(3.5,-5.0)]:
                tx,ty = n["x"]+dx,n["y"]+dy
                if all(abs(tx-px)>5 or abs(ty-py)>3 for px,py in placed):
                    break
            placed.append((tx,ty))
            right.annotate(n["id"],xy=(n["x"],n["y"]),xytext=(tx,ty),fontsize=7,arrowprops=dict(arrowstyle="-",lw=.3,color="#9fa9b4"))
        stat = next(x for x in selected["diagnostics"]["scenarios"] if x["scenario"]==sid)
        right.set(xlim=(-5,108),ylim=(-5,108),xlabel="x (km)",ylabel="y (km)",title=f'{s["name"]}\nServed {stat["fulfilled_demand"]:,.0f} · unmet {stat["unmet_demand"]:,.0f} units/year')
        right.set_aspect("equal"); right.grid(alpha=.12)
        right.legend(handles=[Line2D([],[],marker=m,color="w",markerfacecolor=COLORS[k],label=k.title(),markersize=8) for k,m in [("plant","^"),("warehouse","s"),("customer","o")]],loc="lower left",fontsize=8)
        fig.suptitle("Facility location & network design | cost · disruption resilience",fontsize=18,y=.98)
        footer.set_text(f'${o["cost"]:,.0f}/year  |  {o["expected_unmet_demand"]:,.1f} expected unmet units/year\n{len(selected["opened_warehouses"])} warehouses · {len(selected["activated_arcs"])} active links · approximate frontier')
    footer = fig.text(.5,.025,"",ha="center",fontsize=11,color="#263b57")
    animation=FuncAnimation(fig,update,frames=frames,interval=1000/fps,repeat=True)
    animation.save(str(path),writer=PillowWriter(fps=fps),dpi=100)
    fig.savefig(str(path).rsplit(".",1)[0]+".png",dpi=130)
    plt.close(fig)
