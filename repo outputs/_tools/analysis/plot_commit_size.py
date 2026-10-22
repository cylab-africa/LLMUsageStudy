#!/usr/bin/env python3
"""Commit SIZE event study — lines added / deleted per commit.

Answers "did commits get bigger after AI arrived?".

  top row     raw lines per commit (log axis)
  bottom row  the same, divided by each repo's own pre-adoption median

IMPORTANT LIMITATION, stated on the figure: the panel data holds monthly
TOTALS, so lines-per-commit here is a monthly MEAN (lines_added / commits),
not the median size of a commit. One bulk import dominates its whole month --
nfiq's 2025-09 is 2 commits and 36,810 lines, i.e. 18,405 "per commit".
A true per-commit distribution needs the git history re-walked commit by
commit; this is the bounded version of that question.
"""
import numpy as np, pandas as pd, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

PANEL="repo outputs/analytics/panel_ai_impact.csv"
OUT="repo outputs/analytics"
MIN_REPOS=6; BASE=(-6,-1)
PINE="#2C5C4C"; PURPLE="#B98BE8"

def mord(s):
    s=s.astype(str); return s.str[:4].astype(int)*12+s.str[5:7].astype(int)-1

def normalise(x,metric):
    out=[]
    for _,g in x.groupby("repo_name"):
        b=g[(g["rel"]>=BASE[0])&(g["rel"]<=BASE[1])][metric].median()
        if np.isfinite(b) and b:
            gg=g.copy(); gg["val"]=gg[metric]/b; out.append(gg)
    return pd.concat(out) if out else pd.DataFrame()

METRICS=[("add_per","Lines ADDED per commit\n(raw)",False,True),
         ("del_per","Lines DELETED per commit\n(raw)",False,True),
         ("churn_per","Total churn per commit\n(added + deleted, raw)",False,True),
         ("add_per","Lines ADDED per commit\n(ratio to pre-adoption)",True,True),
         ("del_per","Lines DELETED per commit\n(ratio to pre-adoption)",True,True),
         ("churn_per","Total churn per commit\n(ratio to pre-adoption)",True,True)]

def main():
    d=pd.read_csv(PANEL); d["mi"]=mord(d["month"])
    for c in ("commits","lines_added","lines_removed"):
        d[c]=pd.to_numeric(d[c],errors="coerce")
    d=d[d["commits"]>0].copy()
    d["add_per"]=d["lines_added"]/d["commits"]
    d["del_per"]=d["lines_removed"]/d["commits"]
    d["churn_per"]=(d["lines_added"]+d["lines_removed"])/d["commits"]

    a=d.groupby("repo_name")[["adoption_coding","adoption_review"]].first()
    a=a.dropna(subset=["adoption_coding","adoption_review"])
    gap=mord(a["adoption_coding"])-mord(a["adoption_review"])
    g_lo,g_md,g_hi=-gap.max(),-gap.median(),-gap.min()

    x=d[d["adoption_coding"].notna()].copy()
    x["rel"]=x["mi"]-mord(x["adoption_coding"])
    rels=list(range(-10,4))

    fig,axes=plt.subplots(2,3,figsize=(16.5,8.8))
    fig.patch.set_facecolor("white")
    for ax,(metric,label,do_norm,log) in zip(axes.ravel(),METRICS):
        src=normalise(x,metric) if do_norm else x.assign(val=x[metric])
        data,pos,ns=[],[],[]
        for r in rels:
            v=src[src["rel"]==r]["val"].replace([np.inf,-np.inf],np.nan).dropna()
            if log: v=v[v>0]
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
        if do_norm: ax.axhline(1.0,color="#888888",lw=.8,ls=(0,(4,3)),zorder=1)
        if log:
            ax.set_yscale("log")
            ax.yaxis.set_major_formatter(FuncFormatter(
                lambda v,_: ("%g"%v) if v<1000 else ("%gk"%(v/1000))))
        ax.set_xlabel("Month index relative to CODING-AGENT adoption",
                      fontsize=9.5,labelpad=20)
        ax.set_ylabel(label,fontsize=9.5)
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
    fig.suptitle("MOSIP: did commits get bigger?  Lines added / deleted per commit",
                 fontsize=13.5,y=0.988)
    fig.text(0.5,0.956,"top row raw · bottom row divided by each repo's own pre-adoption median   ·   "
             "CAVEAT: a monthly MEAN (lines ÷ commits), so one bulk import dominates its month",
             ha="center",fontsize=9,color="#777777")
    fig.legend(handles=handles,loc="upper center",bbox_to_anchor=(0.5,0.936),
               ncol=3,frameon=False,fontsize=9.5)
    fig.tight_layout(rect=[0,0.02,1,0.905])
    p=OUT+"/eventstudy_commit_size.png"
    fig.savefig(p,dpi=170,facecolor="white"); plt.close(fig)
    print("wrote",p)

if __name__=="__main__": main()
