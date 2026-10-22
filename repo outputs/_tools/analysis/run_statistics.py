#!/usr/bin/env python3
import numpy as np, pandas as pd
from scipy import stats

d = pd.read_csv("repo outputs/analytics/panel_ai_impact.csv")
def mord(s):
    s = s.astype(str); return s.str[:4].astype(int)*12 + s.str[5:7].astype(int) - 1
d["mi"] = mord(d["month"])
for c in ("commits","ncloc","cognitive_complexity","code_smells","technical_debt",
          "ai_review_share","prs_opened","contributors","ai_ops"):
    d[c] = pd.to_numeric(d[c], errors="coerce")
k = d["ncloc"]/1000.0
d["cx_per_kloc"]=d["cognitive_complexity"]/k
d["smells_per_kloc"]=d["code_smells"]/k
d["debt_per_kloc"]=d["technical_debt"]/k

print("="*74)
print("DIAGNOSTIC 1 — is adoption staggered enough for an event study?")
print("="*74)
for lab,col in (("review",'adoption_review'),("coding",'adoption_coding')):
    a = d[d[col].notna()].groupby("repo_name")[col].first()
    vc = a.value_counts().sort_index()
    print("\n%s adoption months: %s" % (lab, dict(vc)))
    print("  distinct months: %d over %d repos | modal month holds %d/%d (%.0f%%)"
          % (len(vc), len(a), vc.max(), len(a), 100*vc.max()/len(a)))
    x = d[d[col].notna()].copy(); x["rel"]=x["mi"]-mord(x[col])
    r = stats.pearsonr(x["rel"], x["mi"])
    print("  corr(relative month, CALENDAR month) r = %.3f" % r[0])

print()
print("="*74)
print("DIAGNOSTIC 2 — repo-level paired pre/post (Wilcoxon signed-rank)")
print("="*74)
METS=[("commits","commits/mo"),("ncloc","ncloc"),("cx_per_kloc","cognitive cx /kloc"),
      ("smells_per_kloc","code smells /kloc"),("debt_per_kloc","tech debt /kloc"),
      ("prs_opened","PRs opened/mo")]
for lab,col in (("REVIEW-BOT (CodeRabbit)",'adoption_review'),
                ("CODING-AGENT (Cursor/Codex/Claude)",'adoption_coding')):
    x = d[d[col].notna()].copy(); x["rel"]=x["mi"]-mord(x[col])
    print("\n--- split at %s adoption ---" % lab)
    print("%-22s %9s %9s %8s %9s %s" % ("metric","pre med","post med","ratio","p","n"))
    for m,name in METS:
        rows=[]
        for repo,g in x.groupby("repo_name"):
            pre=g[(g["rel"]>=-6)&(g["rel"]<=-1)][m].median()
            post=g[(g["rel"]>=1)&(g["rel"]<=6)][m].median()
            if np.isfinite(pre) and np.isfinite(post): rows.append((pre,post))
        if len(rows)<6: print("%-22s  (n=%d too few)"%(name,len(rows))); continue
        pre=np.array([r[0] for r in rows]); post=np.array([r[1] for r in rows])
        try: p=stats.wilcoxon(pre,post).pvalue
        except Exception: p=float("nan")
        ratio = np.median(post)/np.median(pre) if np.median(pre) else float("nan")
        star = "***" if p<0.01 else "**" if p<0.05 else "*" if p<0.10 else ""
        print("%-22s %9.2f %9.2f %8.2f %9.4f %2d %s"%(name,np.median(pre),np.median(post),ratio,p,len(rows),star))

print()
print("="*74)
print("DIAGNOSTIC 3 — does AI INTENSITY correlate with the change? (Spearman)")
print("="*74)
x = d[d['adoption_review'].notna()].copy(); x["rel"]=x["mi"]-mord(x['adoption_review'])
rows=[]
for repo,g in x.groupby("repo_name"):
    post=g[g["rel"]>=1]; pre=g[(g["rel"]>=-6)&(g["rel"]<=-1)]
    if post.empty or pre.empty: continue
    rec={"repo":repo,
         "ai_share":post["ai_review_share"].mean(),
         "ai_ops":g["ai_ops"].sum(),
         "ai_ops_per_pr":g["ai_ops"].sum()/max(g["prs_opened"].sum(),1)}
    for m in ("cx_per_kloc","smells_per_kloc","debt_per_kloc","commits","ncloc"):
        a,b=pre[m].median(),post[m].median()
        rec["d_"+m]=(b-a) if np.isfinite(a) and np.isfinite(b) else np.nan
        rec["r_"+m]=(b/a) if np.isfinite(a) and np.isfinite(b) and a else np.nan
    rows.append(rec)
R=pd.DataFrame(rows)
print("repos with usable pre+post: %d\n" % len(R))
print("%-34s %7s %8s  %s" % ("AI intensity  vs  outcome","rho","p",""))
for ai in ("ai_share","ai_ops_per_pr"):
    for out in ("d_cx_per_kloc","d_smells_per_kloc","d_debt_per_kloc","r_commits","r_ncloc"):
        s=R[[ai,out]].dropna()
        if len(s)<6: continue
        rho,p=stats.spearmanr(s[ai],s[out])
        star = "***" if p<0.01 else "**" if p<0.05 else "*" if p<0.10 else "ns"
        print("%-34s %7.3f %8.3f  %s (n=%d)" % ("%s vs %s"%(ai,out), rho, p, star, len(s)))
R.to_csv("repo outputs/analytics/repo_intensity_vs_change.csv", index=False)
print("\nwrote repo outputs/analytics/repo_intensity_vs_change.csv")
