# Overleaf package — AI adoption in MOSIP

## Upload
1. Overleaf → **New Project → Upload Project** → zip this `paper/` folder
2. Main document: `main.tex` · Compiler: **pdfLaTeX**
3. `acmart` ships with Overleaf, so it compiles unmodified

## Files
| File | Purpose |
|---|---|
| `main.tex` | the draft — content only |
| `preamble.tex` | visual identity: palette, type, boxes, table styles |
| `main.pdf` | compiled reference build (9 pages) |
| `references.bib` | He et al. plus method citations (Tukey, Hyndman–Fan, SonarQube) |
| `figures/eventstudy.png` | Fig. 1 — event study, coding-agent aligned, **raw values** |
| `figures/perrepo.png` | Fig. 2 — per-repository, **raw** size and complexity |
| `figures/eventstudy_normalised.png` | spare — size-conditioned version, if you want it back |
| `figures/commitsize.png` | spare — lines added/deleted per commit |

## Styling
`preamble.tex` reproduces the web report: sage palette, single measured column,
tinted rows for significant results, and three box styles — `findingbox`
(amber, headline results), `cautionbox` (rust, competing explanations),
`goodbox` (pine, constructive). Swap a box type by renaming the environment.

Fonts are the Adobe Source trio, which ships with Overleaf and needs no upload.
For the exact web fonts (Spectral / Public Sans / IBM Plex Mono), switch the
compiler to XeLaTeX and follow the commented `fontspec` block in `preamble.tex`.

## Switching to ACM format for submission
`main-acmart.tex.bak` is the `acmart[sigconf]` version. The prose is identical,
so section bodies copy across; only the preamble and the two `figure*`
environments differ.

## Verified
Compiled with TeX Live 2026 (pdfLaTeX + BibTeX): 9 pages, 0 errors,
0 undefined references.

## Before submitting
- [ ] Authors and affiliations (marked TODO in `main.tex`)
- [ ] Expand related work — currently one citation
- [ ] Decide whether the two `\begin{figure*}` figures stay full-width
- [ ] `\sig{}` bolds significant results; drop it if the venue objects
- [ ] All values are RAW — no normalisation. §3.2 raises but does not
      settle whether quality rose faster than code volume
- [ ] Re-run `_tools/analysis/` if the dataset is refreshed, then update tables
