#!/usr/bin/env python3
"""Per-repo before/after slopegraphs + the AI-intensity correlation scatter."""
import numpy as np, pandas as pd, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FixedLocator, FuncFormatter
from scipy import stats

d = pd.read_csv("repo outputs/analytics/panel_ai_impact.csv")
def mord(s):
    s = s.astype(str); return s.str[:4].astype(int)*12 + s.str[5:7].astype(int) - 1
d["mi"] = mord(d["month"])
for c in ("commits","ncloc","cognitive_complexity","code_smells","technical_debt",
          "ai_review_share","prs_opened","ai_ops"):
    d[c] = pd.to_numeric(d[c], errors="coerce")
k = d["ncloc"]/1000.0
d["cx_per_kloc"]=d["cognitive_complexity"]/k
d["smells_per_kloc"]=d["code_smells"]/k
d["debt_per_kloc"]=d["technical_debt"]/k

x = d[d["adoption_review"].notna()].copy()
x["rel"] = x["mi"] - mord(x["adoption_review"])

rows=[]
for repo,g in x.groupby("repo_name"):
    pre  = g[(g["rel"]>=-6)&(g["rel"]<=-1)]
    post = g[(g["rel"]>= 1)&(g["rel"]<= 6)]
    rec={"repo":repo.replace("mosip/","")}
    for m in ("commits","ncloc","cx_per_kloc","smells_per_kloc","debt_per_kloc"):
        rec["pre_"+m]=pre[m].median(); rec["post_"+m]=post[m].median()
    rec["ai_share"]=g[g["rel"]>=1]["ai_review_share"].mean()
    rec["ai_ops_per_pr"]=g["ai_ops"].sum()/max(g["prs_opened"].sum(),1)
    rows.append(rec)
R=pd.DataFrame(rows)

MET=[("cx_per_kloc","Cognitive complexity per 1k lines",False),
     ("smells_per_kloc","Code smells per 1k lines",False),
     ("commits","Commits / month",True)]

fig,axes=plt.subplots(1,3,figsize=(16.5,8.6))
fig.patch.set_facecolor("white")
for ax,(m,title,log) in zip(axes,MET):
    sub=R[["repo","pre_"+m,"post_"+m]].dropna().sort_values("pre_"+m)
    y=np.arange(len(sub))
    for i,(_,r) in enumerate(sub.iterrows()):
        a,b=r["pre_"+m],r["post_"+m]
        up = b>a
        ax.plot([a,b],[i,i],color="#C0553A" if up else "#3E6FA8",lw=1.6,zorder=2,alpha=.85)
        ax.scatter([a],[i],s=26,facecolor="white",edgecolor="#555555",lw=1.1,zorder=3)
        ax.scatter([b],[i],s=34,color="#C0553A" if up else "#3E6FA8",zorder=4)
    ax.set_yticks(y); ax.set_yticklabels(sub["repo"],fontsize=8.5)
    if log:
        # default log locator stacks 2x10^0, 3x10^0 ... into unreadable mush at
        # this width; pin a handful of round ticks and label them plainly
        ax.set_xscale("log")
        ax.xaxis.set_major_locator(FixedLocator([0.5, 1, 2, 5, 10, 20, 50, 100]))
        ax.xaxis.set_minor_locator(FixedLocator([]))
        ax.xaxis.set_major_formatter(FuncFormatter(
            lambda v, _: ("%g" % v) if v >= 1 else "%.1f" % v))
    ax.set_title(title,fontsize=11,pad=10)
    ax.grid(axis="x",color="#EAEAEA",lw=.7); ax.set_axisbelow(True)
    for s in ("top","right","left"): ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color("#999999")
    ax.tick_params(axis="x",labelsize=9)
    ax.set_ylim(-0.8,len(sub)-0.2)
axes[0].set_ylabel("")
fig.suptitle("Per-repository before vs after CodeRabbit adoption  "
             "(hollow = 6 months before, filled = 6 months after)",fontsize=12.5,y=0.975)
fig.text(0.5,0.943,"red = metric rose   ·   blue = metric fell",
         ha="center",fontsize=9.5,color="#666666")
fig.tight_layout(rect=[0,0,1,0.93])
fig.savefig("repo outputs/analytics/perrepo_beforeafter.png",dpi=170,facecolor="white")
plt.close(fig)
print("wrote repo outputs/analytics/perrepo_beforeafter.png")

# ---- correlation scatter -------------------------------------------------
fig,axes=plt.subplots(1,2,figsize=(12.5,5.4))
fig.patch.set_facecolor("white")
pairs=[("ai_ops_per_pr","cx_per_kloc","AI operations per PR","Δ cognitive complexity per 1k lines"),
       ("ai_share","cx_per_kloc","Mean AI share of PR reviews (post)","Δ cognitive complexity per 1k lines")]
for ax,(xi,m,xl,yl) in zip(axes,pairs):
    s=R.copy(); s["dv"]=s["post_"+m]-s["pre_"+m]
    s=s[[xi,"dv","repo"]].dropna()
    rho,p=stats.spearmanr(s[xi],s["dv"])
    ax.axhline(0,color="#BBBBBB",lw=.9,ls=(0,(4,3)))
    ax.scatter(s[xi],s["dv"],s=54,color="#3E6FA8",alpha=.85,edgecolor="white",lw=.8,zorder=3)
    for _,r in s.iterrows():
        ax.annotate(r["repo"],(r[xi],r["dv"]),fontsize=6.6,color="#777777",
                    xytext=(4,3),textcoords="offset points")
    ax.set_xlabel(xl,fontsize=10); ax.set_ylabel(yl,fontsize=10)
    sig = "p = %.3f" % p + ("  (not significant after correcting for 10 tests)" if p>0.005 else "")
    ax.set_title("Spearman ρ = %.3f   %s" % (rho,sig),fontsize=10,pad=8)
    ax.grid(color="#EEEEEE",lw=.7); ax.set_axisbelow(True)
    for sp in ("top","right"): ax.spines[sp].set_visible(False)
    for sp in ("left","bottom"): ax.spines[sp].set_color("#999999")
fig.suptitle("Does more AI activity predict more complexity growth?  n = 18 repositories",
             fontsize=12,y=0.98)
fig.tight_layout(rect=[0,0,1,0.93])
fig.savefig("repo outputs/analytics/intensity_correlation.png",dpi=170,facecolor="white")
print("wrote repo outputs/analytics/intensity_correlation.png")
