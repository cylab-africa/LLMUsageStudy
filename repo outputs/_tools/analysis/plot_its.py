#!/usr/bin/env python3
"""ITS figure: observed series, fitted segments, and the counterfactual.

The dashed line is the PRE-ADOPTION TREND EXTRAPOLATED past the event. That is
the whole argument: a codebase grows on its own, and the question is whether
anything happens ABOVE that line. Where observed and counterfactual coincide,
adoption changed nothing.
"""
import numpy as np, pandas as pd, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import statsmodels.formula.api as smf
from matplotlib.lines import Line2D

PURPLE="#B98BE8"; PINE="#2C5C4C"; RUST="#C0472C"; SLATE="#2F6CB0"; GREY="#888888"
WIN=(-10,3)

def mord(s):
    s=s.astype(str); return s.str[:4].astype(int)*12+s.str[5:7].astype(int)-1

d=pd.read_csv("repo outputs/analytics/panel_ai_impact.csv")
d["mi"]=mord(d["month"])
for c in ("ncloc","cognitive_complexity","code_smells","technical_debt"):
    d[c]=pd.to_numeric(d[c],errors="coerce")
d=d[d["adoption_coding"].notna()].copy()
d["tau"]=d["mi"]-mord(d["adoption_coding"])
d=d[(d.tau>=WIN[0])&(d.tau<=WIN[1])]
d["post"]=(d.tau>=0).astype(int); d["tau_post"]=d.tau*d.post

PANELS=[("ncloc","Code size (ncloc)"),
        ("cognitive_complexity","Cognitive complexity"),
        ("code_smells","Code smells"),
        ("technical_debt","Technical debt (minutes)")]

fig,axes=plt.subplots(1,4,figsize=(17.5,4.5))
fig.patch.set_facecolor("white")

for ax,(col,lab) in zip(axes,PANELS):
    x=d[["repo_name","tau","post","tau_post",col]].dropna()
    x=x[x[col]>0].copy(); x["y"]=np.log(x[col])
    keep=[r for r,g in x.groupby("repo_name")
          if (g.tau<0).sum()>=3 and (g.tau>=0).sum()>=1]
    x=x[x.repo_name.isin(keep)]
    m=smf.ols("y ~ tau + post + tau_post + C(repo_name)",data=x).fit(
        cov_type="cluster",cov_kwds={"groups":x.repo_name})
    b1,b2,b3=m.params["tau"],m.params["post"],m.params["tau_post"]
    # repo-demeaned observed series, re-centred on the fitted intercept
    base=x.groupby("repo_name")["y"].transform("mean")
    x["dm"]=x["y"]-base
    obs=x.groupby("tau")["dm"].median()
    a0=np.median([m.params[k] for k in m.params.index if k.startswith("C(repo")] or [0])
    shift=obs.loc[obs.index<0].mean()-np.mean([b1*t for t in obs.index[obs.index<0]])
    taus=np.array(sorted(obs.index))
    fit  = b1*taus + b2*(taus>=0) + b3*np.where(taus>=0,taus,0) + shift
    cfac = b1*taus + shift                      # pre-trend carried forward

    ax.axvspan(-0.45,0.45,color=PURPLE,alpha=.5,lw=0,zorder=0)
    ax.scatter(taus,100*obs.values,s=20,color="#555555",zorder=4,label="observed (median)")
    ax.plot(taus,100*fit,color=RUST,lw=2.0,zorder=3,label="ITS fit")
    ax.plot(taus,100*cfac,color=SLATE,lw=1.8,ls=(0,(5,3)),zorder=3,
            label="counterfactual (pre-trend)")
    ax.set_title("%s\n$\\beta_1$=%+.2f%%/mo  $\\beta_2$=%+.1f%%  $\\beta_3$=%+.2f%%/mo"
                 % (lab,(np.exp(b1)-1)*100,(np.exp(b2)-1)*100,(np.exp(b3)-1)*100),
                 fontsize=9.5)
    ax.set_xlabel("Month relative to coding-agent adoption",fontsize=9)
    ax.grid(axis="y",color="#EFEFEF",lw=.7); ax.set_axisbelow(True)
    for s in ("top","right"): ax.spines[s].set_visible(False)
    for s in ("left","bottom"): ax.spines[s].set_color("#999999")
    ax.tick_params(labelsize=8.5)
axes[0].set_ylabel("log deviation from repo mean (%)",fontsize=9.5)
h=[Line2D([0],[0],marker="o",ls="",color="#555555",label="observed (median across repos)"),
   Line2D([0],[0],color=RUST,lw=2,label="ITS fitted segments"),
   Line2D([0],[0],color=SLATE,lw=1.8,ls=(0,(5,3)),label="counterfactual: pre-trend continued")]
fig.legend(handles=h,loc="upper center",bbox_to_anchor=(0.5,0.075),ncol=3,
           frameon=False,fontsize=9.5)
fig.suptitle("Interrupted time series: observed growth sits on the pre-adoption trend, "
             "not above it",fontsize=12.5,y=0.995)
fig.text(0.5,0.955,"points are medians of repo-demeaned values; lines are the panel fit with "
         "repository fixed effects, so they are not expected to coincide exactly",
         ha="center",fontsize=8.5,color="#777777")
fig.tight_layout(rect=[0,0.08,1,0.93])
p="repo outputs/analytics/its_counterfactual.png"
fig.savefig(p,dpi=170,facecolor="white"); plt.close(fig)
print("wrote",p)
