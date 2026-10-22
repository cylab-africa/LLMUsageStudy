#!/usr/bin/env python3
"""Event study re-centred on CODING-AGENT adoption, with the earlier CodeRabbit
event also marked.

tau = 0 is now the first Cursor / Codex / Claude Code action. The review-bot
rollout preceded it by a median of 7 months (range 4-9), so it appears as a
band at tau = -9..-4 with its median at -7 rather than as a single line.

Caveat carried into the figure: the coding-agent wave is recent, so the post
window is thin. Every box is annotated with its own n so the thinning is
visible rather than implied.
"""
import numpy as np, pandas as pd, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

PANEL="repo outputs/analytics/panel_ai_impact.csv"
OUT="repo outputs/analytics"
MIN_REPOS=6
BASE=(-6,-1)
PINE="#2C5C4C"; AMBER="#B8860B"; PURPLE="#B98BE8"; SLATE="#3E6FA8"

def mord(s):
    s=s.astype(str); return s.str[:4].astype(int)*12+s.str[5:7].astype(int)-1

def load():
    d=pd.read_csv(PANEL); d["mi"]=mord(d["month"])
    for c in ("commits","ncloc","cognitive_complexity","code_smells",
              "technical_debt","ai_review_share","prs_opened"):
        d[c]=pd.to_numeric(d[c],errors="coerce")
    k=d["ncloc"]/1000.0
    d["cx_per_kloc"]=d["cognitive_complexity"]/k
    d["smells_per_kloc"]=d["code_smells"]/k
    d["debt_per_kloc"]=d["technical_debt"]/k
    return d

def normalise(x,metric):
    out=[]
    for _,g in x.groupby("repo_name"):
        b=g[(g["rel"]>=BASE[0])&(g["rel"]<=BASE[1])][metric].median()
        if np.isfinite(b) and b:
            gg=g.copy(); gg["val"]=gg[metric]/b; out.append(gg)
    return pd.concat(out) if out else pd.DataFrame()

METRICS=[("commits","Commits / month\n(ratio to pre-adoption)",True,True),
         ("ncloc","Code size ncloc\n(ratio to pre-adoption)",True,False),
         ("cx_per_kloc","Cognitive complexity\nper 1k lines",False,False),
         ("smells_per_kloc","Code smells\nper 1k lines",False,False),
         ("debt_per_kloc","Technical debt (min)\nper 1k lines",False,False),
         ("ai_review_share","AI share of PR reviews",False,False)]

def main():
    d=load()
    a=d.groupby("repo_name")[["adoption_coding","adoption_review"]].first()
    a=a.dropna(subset=["adoption_coding","adoption_review"])   # gist adopted neither
    gap=mord(a["adoption_coding"])-mord(a["adoption_review"])
    g_lo,g_md,g_hi=-gap.max(),-gap.median(),-gap.min()

    x=d[d["adoption_coding"].notna()].copy()
    x["rel"]=x["mi"]-mord(x["adoption_coding"])
    rels=list(range(-10,4))

    fig,axes=plt.subplots(2,3,figsize=(16.5,8.6))
    fig.patch.set_facecolor("white")
    for ax,(metric,label,do_norm,log) in zip(axes.ravel(),METRICS):
        src=normalise(x,metric) if do_norm else x.assign(val=x[metric])
        data,pos,ns=[],[],[]
        for r in rels:
            v=src[src["rel"]==r]["val"].replace([np.inf,-np.inf],np.nan).dropna()
            if len(v)<MIN_REPOS: continue
            data.append(v.values); pos.append(r); ns.append(len(v))
        if not data: ax.set_visible(False); continue

        # CodeRabbit era: band across its observed range, line at the median
        ax.axvspan(g_lo-0.45,g_hi+0.45,color=PINE,alpha=0.10,zorder=0,lw=0)
        ax.axvline(g_md,color=PINE,lw=1.4,ls=(0,(5,3)),zorder=1)
        # coding-agent adoption
        ax.axvspan(-0.45,0.45,color=PURPLE,alpha=0.55,zorder=2,lw=0)

        bp=ax.boxplot(data,positions=pos,widths=0.62,showfliers=False,
                      patch_artist=True,zorder=4)
        for b in bp["boxes"]: b.set(facecolor="white",edgecolor="#3A3A3A",linewidth=0.9)
        for k in ("whiskers","caps"):
            for e in bp[k]: e.set(color="#3A3A3A",linewidth=0.9)
        for m in bp["medians"]: m.set(color="#111111",linewidth=1.7)
        if do_norm: ax.axhline(1.0,color="#888888",lw=0.8,ls=(0,(4,3)),zorder=1)
        if log:
            ax.set_yscale("log")
            ax.yaxis.set_major_formatter(FuncFormatter(
                lambda v,_:("%g"%v) if v>=0.1 else "%.2g"%v))

        ax.set_xlabel("Month index relative to CODING-AGENT adoption",
                      fontsize=9.5,labelpad=20)
        ax.set_ylabel(label,fontsize=10)
        ax.set_xticks(pos)
        ax.set_xticklabels([str(r) for r in pos],fontsize=8)
        ax.tick_params(axis="y",labelsize=9)
        ax.grid(axis="y",color="#E6E6E6",lw=.7,zorder=0); ax.set_axisbelow(True)
        for s in ("top","right"): ax.spines[s].set_visible(False)
        for s in ("left","bottom"): ax.spines[s].set_color("#999999")
        # n under every box, so a thin tail cannot read as a solid one.
        # Blended transform: x in DATA coords, y in AXES fraction -- keeps the
        # row at a fixed offset regardless of linear vs log y-scaling.
        tr=ax.get_xaxis_transform()
        for p,n in zip(pos,ns):
            ax.text(p,-0.105,"%d"%n,transform=tr,ha="center",va="top",
                    fontsize=6.8,color="#B03030" if n<10 else "#909090",
                    clip_on=False)
        ax.text(0.0,-0.105,"n =",transform=ax.transAxes,fontsize=6.8,
                color="#909090",ha="right",va="top")

    handles=[Patch(facecolor=PURPLE,alpha=.55,label="coding-agent adoption (month 0)"),
             Line2D([0],[0],color=PINE,lw=1.4,ls=(0,(5,3)),
                    label="CodeRabbit adoption — median −7"),
             Patch(facecolor=PINE,alpha=.10,label="CodeRabbit range (−9 to −4)")]
    fig.legend(handles=handles,loc="upper center",bbox_to_anchor=(0.5,0.945),
               ncol=3,frameon=False,fontsize=9.5)
    fig.suptitle("MOSIP: metrics indexed to each repository's AI CODING-AGENT adoption "
                 "(Cursor / Codex / Claude Code)",fontsize=13,y=0.985)
    fig.tight_layout(rect=[0,0.02,1,0.915])
    p=OUT+"/eventstudy_coding_v2.png"
    fig.savefig(p,dpi=170,facecolor="white"); plt.close(fig)
    print("wrote",p)

if __name__=="__main__": main()
