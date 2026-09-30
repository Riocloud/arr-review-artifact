#!/usr/bin/env python3
"""Generate publication figures for the SAGE-Law release-control analysis.

Reads ``safety_stats.json`` and ``analysis_tables/leaf_labels_all_judges.csv``
(produced by ``analyze_safety_labels.py``) and writes PNG + SVG to ``figures/``.
matplotlib only; restrained palette. Every figure states the statistical unit
and whether it is the main audit sample or the enriched final-adjudication
sample.
"""
from __future__ import annotations

import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, PathPatch, Rectangle
from matplotlib.path import Path as MPath

HERE = Path(__file__).resolve().parent
FIG = HERE / "figures"
FIG.mkdir(exist_ok=True)
STATS = json.loads((HERE / "safety_stats.json").read_text())
LEAVES = list(csv.DictReader((HERE / "analysis_tables" / "leaf_labels_all_judges.csv").open()))

plt.rcParams.update({
    "figure.dpi": 130, "savefig.dpi": 210, "font.size": 10.5,
    "font.family": "DejaVu Sans",
    "pdf.fonttype": 42, "ps.fonttype": 42,
    "figure.facecolor": "white", "axes.facecolor": "#eef3f8",
    "axes.titlesize": 12, "axes.titleweight": "bold", "axes.labelsize": 10.5,
    "axes.edgecolor": "#8c97a3", "axes.linewidth": 1.0, "axes.axisbelow": True,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": "#ffffff", "grid.alpha": 1.0, "grid.linewidth": 1.1,
    "legend.frameon": False, "figure.constrained_layout.use": True,
})

# Okabe-Ito colorblind-safe palette; SAGE-Law = bold bluish-green "hero" color.
WRAP = ["raw_agent", "rag_agent", "cbea_lcv_legal", "sage_law"]
WLAB = {"raw_agent": "Raw", "rag_agent": "Support cue", "cbea_lcv_legal": "Bounded cue", "sage_law": "SAGE-Law"}
WCOL = {"raw_agent": "#E69F00", "rag_agent": "#0072B2", "cbea_lcv_legal": "#CC79A7", "sage_law": "#009E73"}
NOTE = "#4a4a4a"


def mimo(**filt):
    out = []
    for r in LEAVES:
        if r["judge"] != "mimo-v2.5-pro":
            continue
        if all(r.get(k) == v for k, v in filt.items()):
            out.append(r)
    return out


def fnum(r, k):
    v = r.get(k, "")
    return float(v) if v not in ("", None) else None


def rate(rows, key):
    vals = [fnum(r, key) for r in rows]
    vals = [v for v in vals if v is not None]
    return (sum(vals) / len(vals)) if vals else None


def wilson(rows, key):
    vals = [fnum(r, key) for r in rows]
    vals = [v for v in vals if v is not None]
    n = len(vals); k = sum(1 for v in vals if v >= 0.5)
    if n == 0:
        return (0, 0, 0)
    p = k / n; z = 1.96; d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (p, max(0, c - h), min(1, c + h))


def save(fig, name):
    fig.savefig(FIG / f"{name}.png", bbox_inches="tight", facecolor="white")
    svg_path = FIG / f"{name}.svg"
    fig.savefig(svg_path, bbox_inches="tight", facecolor="white")
    # Matplotlib emits trailing spaces in SVG path data; normalize them so
    # generated vector masters pass repository whitespace checks.
    svg_path.write_text(
        "\n".join(line.rstrip() for line in svg_path.read_text().splitlines()) + "\n"
    )
    fig.savefig(FIG / f"{name}.pdf", bbox_inches="tight", facecolor="white")  # for LaTeX \includegraphics
    plt.close(fig)
    print("wrote", name)


# ----------------------------------------------------------------- Fig 1: pipeline
def fig_pipeline():
    fig, ax = plt.subplots(figsize=(6.3, 2.8))
    ax.set_xlim(0, 100); ax.set_ylim(0, 30); ax.axis("off")
    ax.set_title("SAGE-Law evaluation pipeline (paired per group = task x model x context)")
    stages = [
        ("Harvey LAB\ntask + matter\nmaterials", "#cfe0f2", "#0072B2"),
        ("4 paired conditions\nRaw / support /\nbounded / SAGE-Law", "#dbe7f5", "#0072B2"),
        ("Generation\nMiniMax & DeepSeek\nactivated / raw_full", "#dbe7f5", "#0072B2"),
        ("SAGE-Law release gate\nreview-gate / block /\nescalate (baselines: ungated)", "#c6ecdb", "#009E73"),
        ("LLM-assisted safety\nannotation\nMimo primary (704)", "#fde7c6", "#E69F00"),
        ("Cross-family checks\n+ GPT final\nadjudication (60)", "#f4dbe7", "#CC79A7"),
    ]
    w = 14.0; gap = (100 - len(stages) * w) / (len(stages) - 1)
    x = 0
    for i, (txt, col, edge) in enumerate(stages):
        ax.add_patch(Rectangle((x, 9), w, 12, facecolor=col, edgecolor=edge, linewidth=1.8, zorder=2))
        ax.text(x + w / 2, 15, txt, ha="center", va="center", fontsize=8.4, zorder=3)
        if i < len(stages) - 1:
            ax.add_patch(FancyArrowPatch((x + w, 15), (x + w + gap, 15),
                         arrowstyle="-|>", mutation_scale=14, color="#5a6470", linewidth=1.4, zorder=1))
        x += w + gap
    ax.text(50, 4.0,
            "Harvey rubric scoring grades the work product; SAGE-Law metrics + LLM safety audit grade release safety and the trace. "
            "These are distinct measurements.",
            ha="center", va="center", fontsize=8, color=NOTE, style="italic")
    save(fig, "fig1_pipeline")


# ---------------------------------------------- Fig 2: paired safety bars (control)
def fig_paired_bars():
    rows_c = {w: mimo(wrapper=w, sample_stratum="control") for w in WRAP}
    fig, axes = plt.subplots(1, 2, figsize=(6.3, 3.2))
    for ax, key, title, ylab in [
        (axes[0], "unsafe_release", "Unsafe release (lower is better)", "rate"),
        (axes[1], "rel_safe", "Post-gate safe-label rate", "rate")]:
        for i, w in enumerate(WRAP):
            p, lo, hi = wilson(rows_c[w], key)
            ax.bar(i, p, color=WCOL[w], width=0.66, edgecolor="#222222", linewidth=0.7, zorder=3)
            ax.errorbar(i, p, yerr=[[p - lo], [hi - p]], color="#222222", capsize=4, linewidth=1.2, zorder=4)
            ax.text(i, hi + 0.035, f"{p:.2f}", ha="center", fontsize=10.5, fontweight="bold", zorder=5)
        ax.set_xticks(range(4)); ax.set_xticklabels([WLAB[w] for w in WRAP], rotation=12)
        ax.set_ylim(0, 1.12); ax.set_ylabel(ylab); ax.set_title(title)
    save(fig, "fig2_paired_safety_bars")


# ------------------------------------- Fig 3: safety-utility Pareto (control + HR)
def fig_pareto():  # single-column: small canvas + small fonts so it is crisp at \columnwidth
    import matplotlib.patheffects as pe
    from matplotlib.lines import Line2D
    off = {"raw_agent": (6, 14), "rag_agent": (-46, 2), "cbea_lcv_legal": (6, -14), "sage_law": (8, -1)}
    with plt.rc_context({"font.size": 9.0, "axes.titlesize": 10.0, "axes.labelsize": 9.0,
                         "xtick.labelsize": 8.5, "ytick.labelsize": 8.5, "legend.fontsize": 8.0}):
        fig, ax = plt.subplots(figsize=(3.25, 3.3))
        for strat, marker, alpha in [("control", "o", 1.0), ("high_risk", "s", 0.5)]:
            for w in WRAP:
                rows = mimo(wrapper=w, sample_stratum=strat)
                u = rate(rows, "rel_util"); fr = rate(rows, "unsafe_release")
                ax.scatter(u, fr, s=105 if strat == "control" else 70, color=WCOL[w], marker=marker,
                           alpha=alpha, edgecolor="#222222", linewidth=0.7, zorder=3)
                if strat == "control":
                    t = ax.annotate(WLAB[w], (u, fr), textcoords="offset points", xytext=off[w],
                                    fontsize=8.0, fontweight="bold", color=WCOL[w], zorder=6)
                    t.set_path_effects([pe.withStroke(linewidth=1.8, foreground="white")])
                elif w == "sage_law":
                    t = ax.annotate("SAGE-Law\nstress", (u, fr), textcoords="offset points", xytext=(8, 7),
                                    fontsize=7.4, fontweight="bold", color=WCOL[w], zorder=6)
                    t.set_path_effects([pe.withStroke(linewidth=1.8, foreground="white")])
        ru = rate(mimo(wrapper="raw_agent", sample_stratum="control"), "rel_util")
        rf = rate(mimo(wrapper="raw_agent", sample_stratum="control"), "unsafe_release")
        su = rate(mimo(wrapper="sage_law", sample_stratum="control"), "rel_util")
        sf = rate(mimo(wrapper="sage_law", sample_stratum="control"), "unsafe_release")
        ax.add_patch(FancyArrowPatch((ru, rf), (su, sf), arrowstyle="-|>", mutation_scale=11,
                     color="#009E73", linewidth=1.3, linestyle=(0, (4, 2)), zorder=2, alpha=0.85))
        leg = [Line2D([0], [0], marker="o", color="w", markerfacecolor="gray", markeredgecolor="black", label="control", markersize=7),
               Line2D([0], [0], marker="s", color="w", markerfacecolor="gray", markeredgecolor="black", label="high-risk", markersize=7)]
        ax.legend(handles=leg, loc="center right", borderaxespad=0.6)
        ax.set_xlabel("utility (0-3, higher better)"); ax.set_ylabel("unsafe release rate (lower better)")
        ax.set_xlim(0, 3); ax.set_ylim(-0.04, 1.1)
        ax.set_box_aspect(1)
        save(fig, "fig3_safety_utility_pareto")  # no in-figure footer: it widened the bbox and shrank the plot at \\columnwidth; unit note is in the LaTeX caption


# ------------------------------------------------ Fig 4: heatmaps unsafe_release / safe
def fig_heatmap():
    models = ["MiniMax-M2.7-highspeed", "MiniMax-M3", "deepseek-v4-flash", "deepseek-v4-pro"]
    mlab = ["MM\nM2.7", "MM\nM3", "DS\nflash", "DS\npro"]
    fig, axes = plt.subplots(1, 2, figsize=(6.3, 2.8))
    for ax, key, title, cmap in [(axes[0], "unsafe_release", "Exposure-aware unsafe release", "YlOrRd"),
                                 (axes[1], "rel_safe", "Safe-to-release rate", "YlGn")]:
        M = []
        for w in WRAP:
            row = []
            for m in models:
                rows = mimo(wrapper=w, generated_model=m)
                row.append(rate(rows, key) if rows else float("nan"))
            M.append(row)
        im = ax.imshow(M, cmap=cmap, vmin=0, vmax=1, aspect="auto")
        ax.set_xticks(range(len(models))); ax.set_xticklabels(mlab, fontsize=7.8)
        ax.set_yticks(range(len(WRAP))); ax.set_yticklabels([WLAB[w] for w in WRAP])
        for i in range(len(WRAP)):
            for j in range(len(models)):
                v = M[i][j]
                ax.text(j, i, f"{v:.2f}" if v == v else "-", ha="center", va="center",
                        color="white" if (v == v and ((key == "unsafe_release" and v > 0.5) or (key == "rel_safe" and v > 0.6))) else "black",
                        fontsize=8.5, fontweight="bold")
        ax.set_title(title)
        fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    save(fig, "fig4_heatmap")


# ----------------------------------------- Fig 5: judge agreement matrices
def fig_agreement():
    judges = [("mimo-v2.5-pro", "Mimo"), ("deepseek-v4-pro", "DeepSeek"),
              ("MiniMax-M3", "MiniMax"), ("gpt-5.4-mini", "GPT")]
    idx = {}
    for jm, _ in judges:
        d = {}
        for r in LEAVES:
            if r["judge"] == jm:
                d[(r["task_id"], r["context_mode"], r["generated_model"], r["wrapper"])] = r
        idx[jm] = d

    def agree(a, b, key):
        keys = set(idx[a]) & set(idx[b])
        pairs = [(fnum(idx[a][k], key), fnum(idx[b][k], key)) for k in keys]
        pairs = [(x, y) for x, y in pairs if x is not None and y is not None]
        if not pairs:
            return (float("nan"), 0)
        return (sum(1 for x, y in pairs if (x >= 0.5) == (y >= 0.5)) / len(pairs), len(pairs))

    fig, axes = plt.subplots(1, 2, figsize=(6.3, 3.0))
    for ax, key, title in [(axes[0], "rel_safe", "Safe-to-release agreement"),
                           (axes[1], "rel_mat_err", "Legal-error agreement")]:
        n = len(judges); M = [[float("nan")] * n for _ in range(n)]; Nn = [[0] * n for _ in range(n)]
        for i in range(n):
            for j in range(n):
                if i == j:
                    M[i][j] = 1.0
                else:
                    M[i][j], Nn[i][j] = agree(judges[i][0], judges[j][0], key)
        im = ax.imshow(M, cmap="YlGnBu", vmin=0.3, vmax=1.0, aspect="auto")
        ax.set_xticks(range(n)); ax.set_xticklabels([j[1] for j in judges], rotation=20)
        ax.set_yticks(range(n)); ax.set_yticklabels([j[1] for j in judges])
        for i in range(n):
            for j in range(n):
                if M[i][j] == M[i][j]:
                    lab = "1.00" if i == j else f"{M[i][j]:.2f}\nn={Nn[i][j]}"
                    ax.text(j, i, lab, ha="center", va="center", fontsize=8,
                            color="white" if M[i][j] > 0.75 else "black")
                else:
                    ax.text(j, i, "no\noverlap", ha="center", va="center", fontsize=7, color="#999")
        ax.set_title(title)
        fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    save(fig, "fig5_judge_agreement")


# -------------------------- Fig 9: compact robustness + judge diagnostics
def fig_robustness_diagnostics():
    """Combine the two coherent robustness diagnostics for a one-page appendix.

    The individual heatmap and agreement masters remain available for analysis
    use. This paper-facing 2x2 canvas preserves their cells and denominators at
    the final 6.3-inch text width without scaling two full figures down in LaTeX.
    """
    models = ["MiniMax-M2.7-highspeed", "MiniMax-M3",
              "deepseek-v4-flash", "deepseek-v4-pro"]
    mlab = ["MM\nM2.7", "MM\nM3", "DS\nflash", "DS\npro"]
    judges = [("mimo-v2.5-pro", "Mimo"), ("deepseek-v4-pro", "DeepSeek"),
              ("MiniMax-M3", "MiniMax"), ("gpt-5.4-mini", "GPT")]
    idx = {}
    for judge_model, _ in judges:
        idx[judge_model] = {
            (r["task_id"], r["context_mode"], r["generated_model"], r["wrapper"]): r
            for r in LEAVES if r["judge"] == judge_model
        }

    def agree(a, b, key):
        keys = set(idx[a]) & set(idx[b])
        pairs = [(fnum(idx[a][k], key), fnum(idx[b][k], key)) for k in keys]
        pairs = [(x, y) for x, y in pairs if x is not None and y is not None]
        if not pairs:
            return (float("nan"), 0)
        return (sum((x >= 0.5) == (y >= 0.5) for x, y in pairs) / len(pairs),
                len(pairs))

    rc = {"font.size": 7.8, "axes.titlesize": 9.0, "axes.grid": False,
          "axes.labelsize": 7.6, "xtick.labelsize": 7.0,
          "ytick.labelsize": 7.2}
    with plt.rc_context(rc):
        fig, axes = plt.subplots(2, 2, figsize=(6.3, 4.15))

        heat_specs = [
            (axes[0, 0], "unsafe_release", "(a) Exposure-aware unsafe release", "YlOrRd"),
            (axes[0, 1], "rel_safe", "(b) Post-gate safe-label rate", "YlGn"),
        ]
        for ax, key, title, cmap in heat_specs:
            matrix = []
            for wrapper in WRAP:
                matrix.append([
                    rate(mimo(wrapper=wrapper, generated_model=model), key)
                    for model in models
                ])
            im = ax.imshow(matrix, cmap=cmap, vmin=0, vmax=1, aspect="auto")
            ax.set_xticks(range(len(models))); ax.set_xticklabels(mlab)
            ax.set_yticks(range(len(WRAP)))
            ax.set_yticklabels([WLAB[w] for w in WRAP])
            for i in range(len(WRAP)):
                for j in range(len(models)):
                    value = matrix[i][j]
                    dark = (value == value and
                            ((key == "unsafe_release" and value > 0.5) or
                             (key == "rel_safe" and value > 0.6)))
                    ax.text(j, i, f"{value:.2f}" if value == value else "-",
                            ha="center", va="center", fontsize=7.2,
                            fontweight="bold", color="white" if dark else "black")
            ax.set_title(title, pad=3)
            fig.colorbar(im, ax=ax, fraction=0.044, pad=0.025)

        agreement_specs = [
            (axes[1, 0], "rel_safe", "(c) Post-gate safe-label agreement"),
            (axes[1, 1], "rel_mat_err", "(d) Legal-error agreement"),
        ]
        for ax, key, title in agreement_specs:
            n_judges = len(judges)
            matrix = [[float("nan")] * n_judges for _ in range(n_judges)]
            counts = [[0] * n_judges for _ in range(n_judges)]
            for i in range(n_judges):
                for j in range(n_judges):
                    if i == j:
                        matrix[i][j] = 1.0
                    else:
                        matrix[i][j], counts[i][j] = agree(
                            judges[i][0], judges[j][0], key
                        )
            im = ax.imshow(matrix, cmap="YlGnBu", vmin=0.3, vmax=1.0,
                           aspect="auto")
            ax.set_xticks(range(n_judges))
            ax.set_xticklabels([j[1] for j in judges], rotation=18)
            ax.set_yticks(range(n_judges))
            ax.set_yticklabels([j[1] for j in judges])
            for i in range(n_judges):
                for j in range(n_judges):
                    value = matrix[i][j]
                    if value == value:
                        label = "1.00" if i == j else f"{value:.2f}\nn={counts[i][j]}"
                        ax.text(j, i, label, ha="center", va="center",
                                fontsize=6.8,
                                color="white" if value > 0.75 else "black")
                    else:
                        ax.text(j, i, "no\noverlap", ha="center", va="center",
                                fontsize=6.2, color="#888888")
            ax.set_title(title, pad=3)
            fig.colorbar(im, ax=ax, fraction=0.044, pad=0.025)

        save(fig, "fig9_robustness_diagnostics")


# ----------------------------------------- Fig 6: gate outcome flow (Sankey-style)
def fig_gate_flow():
    just = STATS["gate_justification_mimo"]
    src_order = ["draft_unsafe", "draft_safe", "no_draft"]
    dst_order = ["blocked_or_escalated", "review_gated_draft"]
    flow = defaultdict(int)
    for r in just:
        flow[(r["draft_status"], r["gate_decision"])] = r["n"]
    src_tot = {s: sum(flow[(s, d)] for d in dst_order) for s in src_order}
    dst_tot = {d: sum(flow[(s, d)] for s in src_order) for d in dst_order}
    total = sum(src_tot.values())
    scol = {"draft_unsafe": "#D55E00", "draft_safe": "#009E73", "no_draft": "#9aa6b2"}
    slab = {"draft_unsafe": "Unsafe", "draft_safe": "Safe", "no_draft": "No draft"}
    dlab = {"blocked_or_escalated": "Blocked", "review_gated_draft": "Review-\ngated"}

    with plt.rc_context({"axes.titlesize": 10.0}):  # single-column, enlarged
        fig, ax = plt.subplots(figsize=(3.3, 3.25)); ax.axis("off")
        xL, xR, bw = 2.3, 7.3, 0.7; pad = 7
        ax.set_xlim(0, 10.6); ax.set_ylim(-12, total + 42)
        mid = (xL + bw + xR) / 2

        def stack(tot, x, order, colormap=None):
            ys = {}; y = total + 26
            for k in order:
                h = tot[k]; ys[k] = (y - h, y)
                ax.add_patch(Rectangle((x, y - h), bw, h, facecolor=(colormap[k] if colormap else "#3b4a5a"),
                             edgecolor="black", linewidth=0.6, zorder=3))
                y -= h + pad
            return ys
        ysrc = stack(src_tot, xL, src_order, scol)
        ydst = stack(dst_tot, xR, dst_order)

        cursor_src = {s: ysrc[s][1] for s in src_order}
        cursor_dst = {d: ydst[d][1] for d in dst_order}
        for s in src_order:
            for d in dst_order:
                h = flow[(s, d)]
                if not h:
                    continue
                y0t = cursor_src[s]; y0b = y0t - h; cursor_src[s] = y0b
                y1t = cursor_dst[d]; y1b = y1t - h; cursor_dst[d] = y1b
                verts = [(xL + bw, y0t), (mid, y0t), (mid, y1t), (xR, y1t),
                         (xR, y1b), (mid, y1b), (mid, y0b), (xL + bw, y0b), (xL + bw, y0t)]
                codes = [MPath.MOVETO, MPath.CURVE4, MPath.CURVE4, MPath.LINETO,
                         MPath.LINETO, MPath.CURVE4, MPath.CURVE4, MPath.LINETO, MPath.CLOSEPOLY]
                ax.add_patch(PathPatch(MPath(verts, codes), facecolor=scol[s], alpha=0.32, edgecolor="none", zorder=1))
        for s in src_order:
            yc = (ysrc[s][0] + ysrc[s][1]) / 2
            ax.text(xL - 0.2, yc, f"{slab[s]} {src_tot[s]}", ha="right", va="center", fontsize=8.5)
        for d in dst_order:
            yc = (ydst[d][0] + ydst[d][1]) / 2
            ax.text(xR + bw + 0.2, yc, f"{dlab[d]} {dst_tot[d]}", ha="left", va="center", fontsize=8.5)
        ax.text(xL + bw / 2, total + 33, "Draft", ha="center", fontsize=8.5, fontweight="bold")
        ax.text(xR + bw / 2, total + 33, "Gate", ha="center", fontsize=8.5, fontweight="bold")
        save(fig, "fig6_gate_flow")  # no in-figure footer (see fig_pareto note); unit note is in the LaTeX caption


# ----------------------------------------- Fig 7: GPT final adjudication waterfall
def fig_gpt_waterfall():
    # Single-column composition: a compact funnel above two horizontal stacked
    # bars.  This preserves every count while remaining legible at column width.
    with plt.rc_context({"font.size": 7.8, "axes.titlesize": 9.0,
                         "axes.labelsize": 8.0, "xtick.labelsize": 7.3,
                         "ytick.labelsize": 7.3}):
        fig, axes = plt.subplots(2, 1, figsize=(3.25, 3.15),
                                 gridspec_kw={"height_ratios": [0.9, 1.25]})
        ax = axes[0]
        ax.set_xlim(-0.2, 2.2); ax.set_ylim(0, 1); ax.axis("off")
        ax.set_title("Audit funnel", pad=2)
        steps = [("15", "selected\ngroups", "#009E73"),
                 ("60", "leaves", "#0072B2"),
                 ("60", "clean labels", "#0072B2")]
        for i, (value, label, color) in enumerate(steps):
            ax.text(i, 0.54, value, ha="center", va="center", fontsize=10,
                    fontweight="bold", color=color,
                    bbox={"boxstyle": "round,pad=0.28", "facecolor": "white",
                          "edgecolor": color, "linewidth": 1.2})
            ax.text(i, 0.16, label, ha="center", va="center", fontsize=7.2)
            if i < len(steps) - 1:
                ax.annotate("", xy=(i + 0.70, 0.54), xytext=(i + 0.30, 0.54),
                            arrowprops={"arrowstyle": "-|>", "color": "#5a6470",
                                        "linewidth": 1.0})
        ax.text(1.5, 0.33, "$\\times4$ conditions", ha="center", va="center",
                fontsize=6.8, color=NOTE)

        ax2 = axes[1]
        ax2.set_title("Enriched composition", pad=2)
        cats = [("high-risk/FR", 28, "#D55E00"),
                ("boundary", 12, "#E69F00"),
                ("control", 12, "#009E73"),
                ("family", 8, "#0072B2")]
        outs = [("unsafe", 52, "#D55E00"), ("safe", 8, "#009E73")]
        for y, parts in [(1, cats), (0, outs)]:
            left = 0
            for label, value, color in parts:
                ax2.barh(y, value, left=left, height=0.48, color=color,
                         edgecolor="#222222", linewidth=0.5)
                text_color = "black" if color == "#E69F00" else "white"
                ax2.text(left + value / 2, y, f"{label}\n{value}", ha="center",
                         va="center", fontsize=6.5, color=text_color)
                left += value
        ax2.text(52, -0.43, "false release: 5", ha="center", va="center",
                 fontsize=7.0, color=NOTE)
        ax2.set_yticks([1, 0]); ax2.set_yticklabels(["selection", "GPT label"])
        ax2.set_xlim(0, 60); ax2.set_xlabel("leaves")
        ax2.set_ylim(-0.65, 1.45)
        ax2.spines["left"].set_visible(False)
        ax2.grid(axis="x"); ax2.grid(axis="y", visible=False)
        save(fig, "fig7_gpt_waterfall")


# ----------------------------------------- Fig 8: failure taxonomy stacked bar
def fig_failure_taxonomy():
    tax = {r["wrapper"]: r for r in STATS["failure_taxonomy_mimo"] if r["stratum"] == "control"}
    cats = [("unsupported_claim", "unsupported claim", "#D55E00"),
            ("material_legal_error", "material legal error", "#9B2226"),
            ("overcommitment", "overcommitment", "#E69F00"),
            ("unsupported_recommendation", "unsupported recommendation", "#0072B2"),
            ("issue_omitted", "issue omitted w/o reservation", "#CC79A7")]
    fig, ax = plt.subplots(figsize=(6.3, 2.65))  # compact full-width main-text figure
    for i, w in enumerate(WRAP):
        bottom = 0
        for key, lab, col in cats:
            v = tax[w][key]
            ax.bar(i, v, bottom=bottom, color=col, width=0.62, edgecolor="white", linewidth=0.8,
                   label=lab if i == 0 else None, zorder=3)
            bottom += v
        ax.text(i, bottom + 0.05, f"Σ={bottom:.2f}", ha="center", fontsize=11, fontweight="bold")
    ax.set_xticks(range(4)); ax.set_xticklabels([WLAB[w] for w in WRAP], rotation=12)
    ax.set_ylabel("Defect burden (sum of rates)")
    ax.set_ylim(0, 3.0)
    # No in-image title; the paper caption carries the unit and sampling caveat.
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=3,
              fontsize=8.2, columnspacing=1.1, handletextpad=0.4)
    save(fig, "fig8_failure_taxonomy")


if __name__ == "__main__":
    fig_pipeline()
    fig_paired_bars()
    fig_pareto()
    fig_heatmap()
    fig_agreement()
    fig_gate_flow()
    fig_gpt_waterfall()
    fig_failure_taxonomy()
    fig_robustness_diagnostics()
    print("All figures written to", FIG)
