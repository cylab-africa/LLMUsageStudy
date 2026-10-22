#!/usr/bin/env python3
"""One panel per repository, in REAL UNITS. No normalisation anywhere.

An earlier version divided BOTH series by each repo's pre-adoption median so the
panels shared a y-scale. That was a mistake for the complexity line: cognitive
complexity per 1k lines is ALREADY size-normalised, so dividing it again by its
own baseline produced a ratio of a ratio -- hard to read, and it discarded the
level, which is the thing a per-repo view exists to show (nfiq sits at ~155
complexity/kloc, bio-utils at ~5; that is the interesting fact about them).

So: raw values, twin axes, one panel per repo.

  LEFT  axis, blue   ncloc in thousands   -- how much code
  RIGHT axis, red    cognitive complexity -- raw total, not a rate

Both axes start at ZERO. That matters: with autoscaling, a series that varies
by 1% fills the panel and looks volatile. Anchored at zero, flat looks flat.

Comparability across repos is the pooled box plot's job, not this figure's.
"""
import numpy as np, pandas as pd, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

PANEL="repo outputs/analytics/panel_ai_impact.csv"
OUT="repo outputs/analytics"
PINE="#2C5C4C"; PURPLE="#8E5FC4"; SLATE="#2F6CB0"; RUST="#C0472C"

def mord(s):
    s=s.astype(str); return s.str[:4].astype(int)*12+s.str[5:7].astype(int)-1
def m1(v): return int(str(v)[:4])*12+int(str(v)[5:7])-1

d=pd.read_csv(PANEL); d["mi"]=mord(d["month"])
for c in ("ncloc","cognitive_complexity"): d[c]=pd.to_numeric(d[c],errors="coerce")
d["kloc"]=d["ncloc"]/1000.0
d["cx"]=d["cognitive_complexity"]          # RAW total, not per-kloc

lo,hi=d["mi"].min(),d["mi"].max()
ticks=[m for m in range(lo,hi+1) if (m%12) in (0,6)]
labs=["%d-%02d"%(m//12,m%12+1) for m in ticks]

repos=sorted(d["repo_name"].unique())
fig,axes=plt.subplots(4,5,figsize=(19,11.5),sharex=True)
fig.patch.set_facecolor("white")

for ax,repo in zip(axes.ravel(),repos):
    g=d[d["repo_name"]==repo].sort_values("mi")
    name=repo.replace("mosip/","")
    ac=g["adoption_coding"].dropna(); ar=g["adoption_review"].dropna()
    ac=m1(ac.iloc[0]) if len(ac) else None
    ar=m1(ar.iloc[0]) if len(ar) else None

    k=g[["mi","kloc"]].dropna(); c=g[["mi","cx"]].dropna()
    ax2=ax.twinx()
    if ar is not None: ax.axvline(ar,color=PINE,lw=1.2,ls=(0,(5,3)),zorder=1)
    if ac is not None: ax.axvspan(ac-0.45,ac+0.45,color=PURPLE,alpha=0.28,lw=0,zorder=0)

    if len(k):
        ax.plot(k["mi"],k["kloc"],color=SLATE,lw=1.7,zorder=3)
        ax.scatter(k["mi"],k["kloc"],s=8,color=SLATE,zorder=4)
        ax.set_ylim(0,max(k["kloc"].max()*1.18,1e-6))
    if len(c):
        ax2.plot(c["mi"],c["cx"],color=RUST,lw=1.7,zorder=3)
        ax2.scatter(c["mi"],c["cx"],s=8,color=RUST,zorder=4)
        ax2.set_ylim(0,max(c["cx"].max()*1.18,1e-6))

    # state the levels in words, since the two axes have different scales
    sub=""
    if len(k) and len(c):
        sub=("%.0fk→%.0fk lines · cx %.0f→%.0f total"
             % (k["kloc"].iloc[0],k["kloc"].iloc[-1],c["cx"].iloc[0],c["cx"].iloc[-1]))
    elif len(k):
        sub="%.0fk→%.0fk lines · no complexity data"%(k["kloc"].iloc[0],k["kloc"].iloc[-1])
    else:
        sub="no SonarQube data"
    ax.set_title(name if ac is not None else name+"  (no AI detected)",
                 fontsize=9.5,pad=13)
    ax.text(0.5,1.015,sub,transform=ax.transAxes,ha="center",va="bottom",
            fontsize=6.9,color="#777777")

    ax.tick_params(axis="y",labelsize=7,colors=SLATE)
    ax2.tick_params(axis="y",labelsize=7,colors=RUST)
    ax.tick_params(axis="x",labelsize=7.5)
    ax.grid(axis="y",color="#F0F0F0",lw=.6); ax.set_axisbelow(True)
    for sp in ("top",): ax.spines[sp].set_visible(False); ax2.spines[sp].set_visible(False)
    ax.spines["left"].set_color(SLATE); ax2.spines["right"].set_color(RUST)
    ax2.spines["left"].set_color(SLATE)

for ax in axes.ravel()[len(repos):]: ax.set_visible(False)
for ax in axes[-1,:]:
    ax.set_xticks(ticks); ax.set_xticklabels(labs,rotation=45,ha="right",fontsize=7.5)

handles=[Line2D([0],[0],color=SLATE,lw=1.8,label="Code size, thousands of lines (LEFT axis)"),
         Line2D([0],[0],color=RUST,lw=1.8,label="Cognitive complexity, raw total (RIGHT axis)"),
         Patch(facecolor=PURPLE,alpha=.28,label="Coding-agent adoption"),
         Line2D([0],[0],color=PINE,lw=1.2,ls=(0,(5,3)),label="CodeRabbit adoption")]
fig.suptitle("All 20 MOSIP repositories — raw code size and raw cognitive complexity",
             fontsize=13.5,y=0.988)
fig.text(0.5,0.958,"raw values, no normalisation  ·  both axes start at zero, so a flat line "
         "is genuinely flat  ·  the two axes have different scales, so read each "
         "line against its own side",ha="center",fontsize=9,color="#777777")
fig.legend(handles=handles,loc="upper center",bbox_to_anchor=(0.5,0.938),
           ncol=4,frameon=False,fontsize=9.5)
fig.tight_layout(rect=[0,0,1,0.9])
p=OUT+"/permultiples_all_repos.png"
fig.savefig(p,dpi=165,facecolor="white"); plt.close(fig)
print("wrote",p)
