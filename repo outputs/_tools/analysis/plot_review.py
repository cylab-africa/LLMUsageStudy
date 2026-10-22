#!/usr/bin/env python3
"""Code-review practice: coverage and actor mix, indexed to review-bot adoption."""
import numpy as np, pandas as pd, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

PINE="#2C5C4C"; RUST="#C0472C"; SLATE="#2F6CB0"; AMBER="#B8860B"; PURPLE="#B98BE8"
R=pd.read_csv("repo outputs/analytics/review_actor_monthly.csv")
ad=pd.read_csv("repo outputs/analytics/panel_ai_impact.csv")
a=ad.groupby("repo_name")["adoption_review"].first()
R=R.join(a,on="repo_name"); R=R[R.adoption_review.notna()&(R.month<="2026-08")].copy()
def mo(s): return s.str[:4].astype(int)*12+s.str[5:7].astype(int)-1
R["tau"]=mo(R.month.astype(str))-mo(R.adoption_review.astype(str))
R=R[(R.tau>=-10)&(R.tau<=9)]
for c,n in (("cov_any","prs_reviewed"),("cov_hum","prs_human"),("cov_ai","prs_ai")):
    R[c]=R[n]/R.prs.replace(0,np.nan)

fig,axes=plt.subplots(1,3,figsize=(16.5,4.9))
fig.patch.set_facecolor("white")

# --- panel A: coverage, median across repos -------------------------------
ax=axes[0]
rels=sorted(R.tau.unique())
for num,color,lab in (("prs_reviewed","#333333","any review"),
                      ("prs_human",SLATE,"human review"),("prs_ai",RUST,"AI review")):
    xs,ys=[],[]
    for t in rels:
        w=R[R.tau==t]
        if w.repo_name.nunique()>=6 and w.prs.sum()>0:
            xs.append(t); ys.append(w[num].sum()/w.prs.sum())
    ax.plot(xs,ys,color=color,lw=1.9,label=lab); ax.scatter(xs,ys,s=14,color=color)
ax.axvspan(-0.45,0.45,color=PURPLE,alpha=.5,lw=0,zorder=0)
ax.set_ylim(0,1); ax.set_ylabel("fraction of PRs receiving a review\n(pooled across repos)",fontsize=9.5)
ax.set_title("A · Review coverage",fontsize=11,loc="left")
ax.legend(fontsize=8.5,frameon=False)

# --- panel B: reviews per PR (volume), the contrasting measure ------------
ax=axes[1]
R["vol_hum"]=R.n_human/R.prs.replace(0,np.nan)
R["vol_ai"] =R.n_ai/R.prs.replace(0,np.nan)
for num,color,lab in (("n_human",SLATE,"human reviews / PR"),
                      ("n_ai",RUST,"AI reviews / PR")):
    xs,ys=[],[]
    for t in rels:
        w=R[R.tau==t]
        if w.repo_name.nunique()>=6 and w.prs.sum()>0:
            xs.append(t); ys.append(w[num].sum()/w.prs.sum())
    ax.plot(xs,ys,color=color,lw=1.9,label=lab); ax.scatter(xs,ys,s=14,color=color)
ax.axvspan(-0.45,0.45,color=PURPLE,alpha=.5,lw=0,zorder=0)
ax.set_ylabel("review submissions per PR",fontsize=10)
ax.set_title("B · Review volume",fontsize=11,loc="left")
ax.legend(fontsize=8.5,frameon=False)

# --- panel C: who reviews, stacked share ----------------------------------
ax=axes[2]
agg=R.groupby("tau")[["n_human","n_ai","n_otherbot"]].sum()
agg=agg[agg.sum(axis=1)>0]
tot=agg.sum(axis=1)
ax.stackplot(agg.index,100*agg.n_human/tot,100*agg.n_ai/tot,100*agg.n_otherbot/tot,
             colors=[SLATE,RUST,AMBER],alpha=.85,
             labels=["human","AI review bot","other bot (Dependabot etc.)"])
ax.axvline(0,color=PURPLE,lw=3,alpha=.75)
ax.set_ylim(0,100); ax.set_ylabel("share of review submissions (%)",fontsize=10)
ax.set_title("C · Who reviews",fontsize=11,loc="left")
ax.legend(fontsize=8.5,frameon=False,loc="lower left")

for ax in axes:
    ax.set_xlabel("Month relative to AI review-bot adoption",fontsize=9.5)
    ax.grid(axis="y",color="#EFEFEF",lw=.7); ax.set_axisbelow(True)
    for s in ("top","right"): ax.spines[s].set_visible(False)
    for s in ("left","bottom"): ax.spines[s].set_color("#999999")
    ax.tick_params(labelsize=8.5)
fig.suptitle("MOSIP code review: the bot raised AI coverage to ~18% of PRs while human "
             "coverage continued its pre-existing decline",fontsize=12.5,y=1.0)
fig.tight_layout(rect=[0,0,1,0.93])
p="repo outputs/analytics/review_practice.png"
fig.savefig(p,dpi=170,facecolor="white"); plt.close(fig)
print("wrote",p)
