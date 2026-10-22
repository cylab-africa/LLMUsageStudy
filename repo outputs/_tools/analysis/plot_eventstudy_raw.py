#!/usr/bin/env python3
"""RAW-counts event study — the same six panels with NO normalisation.

Deliberately unnormalised, as a control on the main figure. Two things become
visible that the normalised version hides by design:

  * how much of each box is simply between-repo SIZE (ncloc spans 7,931 to
    355,811, so the boxes are tall everywhere and stay tall);
  * that RAW cognitive complexity and RAW code smells drift upward across the
    window, which is the trend an unnormalised reading would report as
    "AI made the code more complex". Panel 2 shows the code base growing at
    the same time -- which is why the main figure divides by size.

Axes are log where a metric spans orders of magnitude; a linear axis would put
every small repository on the floor.
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
PINE="#2C5C4C"; PURPLE="#B98BE8"

def mord(s):
    s=s.astype(str); return s.str[:4].astype(int)*12+s.str[5:7].astype(int)-1

# metric, label, log axis?
METRICS=[("commits","Commits / month\n(raw count)",True),
         ("ncloc","Code size\n(raw ncloc)",True),
         ("cognitive_complexity","Cognitive complexity\n(raw total)",True),
         ("code_smells","Code smells\n(raw total)",True),
         ("technical_debt","Technical debt\n(raw minutes)",True),
         ("ai_review_share","AI share of PR reviews\n(raw proportion)",False)]

def main():
    d=pd.read_csv(PANEL); d["mi"]=mord(d["month"])
    for c,_,_ in METRICS: d[c]=pd.to_numeric(d[c],errors="coerce")
    d["prs_opened"]=pd.to_numeric(d["prs_opened"],errors="coerce")
    a=d.groupby("repo_name")[["adoption_coding","adoption_review"]].first()
    a=a.dropna(subset=["adoption_coding","adoption_review"])
    gap=mord(a["adoption_coding"])-mord(a["adoption_review"])
    g_lo,g_md,g_hi=-gap.max(),-gap.median(),-gap.min()

    x=d[d["adoption_coding"].notna()].copy()
    x["rel"]=x["mi"]-mord(x["adoption_coding"])
    rels=list(range(-10,4))

    fig,axes=plt.subplots(2,3,figsize=(16.5,8.6))
    fig.patch.set_facecolor("white")
    for ax,(metric,label,log) in zip(axes.ravel(),METRICS):
        data,pos,ns=[],[],[]
        for r in rels:
            v=x[x["rel"]==r][metric].replace([np.inf,-np.inf],np.nan).dropna()
            v=v[v>0] if log else v          # log axis cannot show zero
            if len(v)<MIN_REPOS: continue
            data.append(v.values); pos.append(r); ns.append(len(v))
        if not data: ax.set_visible(False); continue
        ax.axvspan(g_lo-0.45,g_hi+0.45,color=PINE,alpha=0.10,zorder=0,lw=0)
        ax.axvline(g_md,color=PINE,lw=1.4,ls=(0,(5,3)),zorder=1)
        ax.axvspan(-0.45,0.45,color=PURPLE,alpha=0.55,zorder=2,lw=0)
        bp=ax.boxplot(data,positions=pos,widths=0.62,showfliers=False,
                      patch_artist=True,zorder=4)
        for b in bp["boxes"]: b.set(facecolor="white",edgecolor="#3A3A3A",linewidth=0.9)
        for k in ("whiskers","caps"):
            for e in bp[k]: e.set(color="#3A3A3A",linewidth=0.9)
        for m in bp["medians"]: m.set(color="#111111",linewidth=1.7)
        if log:
            ax.set_yscale("log")
            ax.yaxis.set_major_formatter(FuncFormatter(
                lambda v,_: ("%g"%v) if v<1000 else ("%gk"%(v/1000))))
        ax.set_xlabel("Month index relative to CODING-AGENT adoption",
                      fontsize=9.5,labelpad=20)
        ax.set_ylabel(label,fontsize=10)
        ax.set_xticks(pos); ax.set_xticklabels([str(r) for r in pos],fontsize=8)
        ax.tick_params(axis="y",labelsize=9)
        ax.grid(axis="y",color="#E6E6E6",lw=.7,zorder=0); ax.set_axisbelow(True)
        for sp in ("top","right"): ax.spines[sp].set_visible(False)
        for sp in ("left","bottom"): ax.spines[sp].set_color("#999999")
        tr=ax.get_xaxis_transform()
        for p,n in zip(pos,ns):
            ax.text(p,-0.105,"%d"%n,transform=tr,ha="center",va="top",
                    fontsize=6.8,color="#B03030" if n<10 else "#909090",clip_on=False)
        ax.text(0.0,-0.105,"n =",transform=ax.transAxes,fontsize=6.8,
                color="#909090",ha="right",va="top")

    handles=[Patch(facecolor=PURPLE,alpha=.55,label="coding-agent adoption (month 0)"),
             Line2D([0],[0],color=PINE,lw=1.4,ls=(0,(5,3)),label="CodeRabbit adoption — median −7"),
             Patch(facecolor=PINE,alpha=.10,label="CodeRabbit range (−9 to −4)")]
    fig.legend(handles=handles,loc="upper center",bbox_to_anchor=(0.5,0.945),
               ncol=3,frameon=False,fontsize=9.5)
    fig.suptitle("MOSIP: RAW values, no normalisation  —  log axes where repositories "
                 "differ by orders of magnitude",fontsize=13,y=0.985)
    fig.tight_layout(rect=[0,0.02,1,0.915])
    p=OUT+"/eventstudy_raw.png"
    fig.savefig(p,dpi=170,facecolor="white"); plt.close(fig)
    print("wrote",p)

if __name__=="__main__": main()
