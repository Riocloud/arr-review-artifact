#!/usr/bin/env python3
"""SAGE-Law safety-label analysis (stdlib only, reproducible).

Reads the frozen LLM-judge safety-annotation label files under
``results/audits/llm_judge_labels/`` and the per-leaf ``gate_decision.json``
under ``experiments/runs/`` and produces the analysis tables and a master
``safety_stats.json`` consumed by the summary docs and figure scripts.

Design notes / definitions (see results/manual_audit_protocol.md and
safety_annotation_lab.py for the source schema):

- Paired comparison unit = group = (task_id, context_mode, generated_model).
  Within a group the four wrappers are paired conditions. This historical
  master analysis resamples paired groups; ``task_clustered_sensitivity.py``
  separately resamples tasks from the frozen leaf table because some tasks
  contribute multiple groups.
- "released" surface = the gated/exposed artifact (post-gate for sage_law,
  ungated baseline output otherwise) -> release safety.
- "review_draft" surface = sage_law internal draft before the release adapter
  -> draft quality. Only present for sage_law leaves.
- safe_to_release_derived is taken directly from the judge (already derived from
  sublabels per the annotation prompt).
- rel_unsafe is the not-safe-to-release complement on the released surface.
- unsafe_release is exposure-aware: exposed substantive artifact AND not
  safe_to_release. This separates blocked status artifacts from unsafe releases.
- false_release/false_refusal/false_downgrade are the judge gate labels.
- Strata are outcome-informed: high_risk is selected using SAGE gate/score
  signals, then control is spread-selected from the remainder. Both support
  descriptive within-sample contrasts, not population prevalence.
- Primary judge = mimo-v2.5-pro (cross-family to every generator).
  Cross-checks: deepseek-v4-pro on MiniMax-generated leaves; MiniMax-M3 on
  DeepSeek-generated leaves (both cross-family). GPT-5.4-mini = final
  adjudication sample (60 leaves, enriched).

No raw provider payloads, judge rationales, evidence snippets, or artifact text
are written to any output. Only structural fields and numeric/boolean/
categorical labels are emitted.
"""
from __future__ import annotations

import csv
import glob
import json
import math
import os
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
EXPERIMENTS = HERE.parents[1]  # audits -> results -> experiments
LABEL_DIR = HERE / "llm_judge_labels"
TABLES = HERE / "analysis_tables"
if __name__ == "__main__" and (
    not LABEL_DIR.is_dir() or not any(LABEL_DIR.glob("*.jsonl"))
    or not (EXPERIMENTS / "runs").is_dir()
):
    raise SystemExit(
        "Frozen raw labels and run artifacts are absent from this review package. "
        "Use reproduce.py for analysis of the included tables. No outputs were replaced."
    )
TABLES.mkdir(parents=True, exist_ok=True)

WRAPPERS = ("raw_agent", "rag_agent", "cbea_lcv_legal", "sage_law")
BASELINES = ("raw_agent", "rag_agent", "cbea_lcv_legal")
SEED = 20260606
N_BOOT = 2000

MIMO_PATTERNS = (
    "mimo_v2_5_pro_main_safety.shard-*.jsonl",
    "mimo_v2_5_pro_main_safety.tail-retry-*.jsonl",
    "mimo_v2_5_pro_main_safety.retry8192-*.jsonl",
)
DEEPSEEK_PATTERNS = ("deepseek_v4_pro_on_minimax_subset.jsonl",)
MINIMAX_PATTERNS = (
    "minimax_m3_on_deepseek_subset.shard-*.jsonl",
    "minimax_m3_on_deepseek_subset.tail-pr8-*.jsonl",
)
GPT_PATTERNS = ("gpt_5_4_mini_final_adjudication_15groups.ok.jsonl",)


# --------------------------------------------------------------------------- IO
def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def leaf_key(row: dict[str, Any]):
    vals = (row.get("task_id"), row.get("context_mode"), row.get("generated_model"), row.get("wrapper"))
    if all(isinstance(v, str) and v for v in vals):
        return vals
    return None


def load_ok(patterns) -> dict[tuple, dict[str, Any]]:
    """Load ok rows, dedup by leaf_key keeping the last occurrence (retries win)."""
    by_leaf: dict[tuple, dict[str, Any]] = {}
    raw = ok = err = 0
    err_kinds: Counter = Counter()
    for pat in patterns:
        for p in sorted(LABEL_DIR.glob(pat)):
            for r in read_jsonl(p):
                raw += 1
                if r.get("status") == "ok":
                    ok += 1
                    k = leaf_key(r)
                    if k:
                        by_leaf[k] = r
                elif r.get("status") == "error":
                    err += 1
                    err_kinds[str(r.get("error") or "unknown").split(":", 1)[0]] += 1
    load_ok.stats = {"raw": raw, "ok": ok, "error": err, "unique": len(by_leaf), "err_kinds": dict(err_kinds)}
    return by_leaf


def xlate(path: str) -> Path:
    """Resolve a recorded host leaf_path under the local experiments/runs tree."""
    if "/runs/" in path:
        return EXPERIMENTS / "runs" / path.split("/runs/", 1)[1]
    return Path(path)


_GATE_CACHE: dict[str, str] = {}


def gate_decision(leaf_path: str | None) -> str:
    if not leaf_path:
        return "unknown"
    if leaf_path in _GATE_CACHE:
        return _GATE_CACHE[leaf_path]
    p = xlate(leaf_path) / "gate_decision.json"
    dec = "missing"
    if p.is_file():
        try:
            dec = json.loads(p.read_text()).get("decision", "none")
        except Exception:
            dec = "error"
    _GATE_CACHE[leaf_path] = dec
    return dec


def exposed_artifact(decision: str) -> int | None:
    """Whether a substantive artifact was exposed to the user."""
    if decision in {"ungated_baseline_output", "review_gated_draft", "released"}:
        return 1
    if decision in {"blocked_or_escalated", "blocked", "escalated"}:
        return 0
    return None


# --------------------------------------------------------------- label extract
def _b(x) -> int | None:
    return int(x) if isinstance(x, bool) else (None if x is None else (1 if x else 0))


def _i(x) -> int | None:
    if isinstance(x, bool):
        return int(x)
    if isinstance(x, (int, float)):
        return int(x)
    return None


def surface(ann: dict, name: str) -> dict:
    d = ann.get(name)
    return d if isinstance(d, dict) else {}


def leaf_record(row: dict[str, Any], judge: str) -> dict[str, Any]:
    ann = row.get("annotation") if isinstance(row.get("annotation"), dict) else {}
    rel = surface(ann, "released")
    rev = ann.get("review_draft") if isinstance(ann.get("review_draft"), dict) else None
    gate = surface(ann, "gate")
    dec = gate_decision(row.get("leaf_path"))
    rec = {
        "judge": judge,
        "study": row.get("study"),
        "sample_stratum": row.get("sample_stratum"),
        "selection_category": row.get("selection_category"),
        "task_id": row.get("task_id"),
        "context_mode": row.get("context_mode"),
        "generated_model": row.get("generated_model"),
        "generated_family": family(row.get("generated_model") or ""),
        "wrapper": row.get("wrapper"),
        "gate_decision": dec,
        "trace_reconstructable": ann.get("trace_reconstructable"),
        "confidence": ann.get("confidence"),
        # released surface
        "rel_safe": _b(rel.get("safe_to_release_derived")),
        "rel_mat_err": _b(rel.get("material_legal_error_present")),
        "rel_overcommit": _b(rel.get("overcommitment_present")),
        "rel_unsup_rec": _b(rel.get("unsupported_recommendation_present")),
        "rel_issue_omit": _b(rel.get("material_issue_omitted_without_reservation")),
        "rel_unsup_claims": _i(rel.get("unsupported_material_claim_count")),
        "rel_contra_claims": _i(rel.get("contradicted_material_claim_count")),
        "rel_util": _i(rel.get("utility_score")),
        "rel_cov": _i(rel.get("criteria_coverage_score")),
        "rel_claims_audited": _i(rel.get("material_claims_audited")),
        # gate labels
        "false_release": _b(gate.get("false_release")),
        "false_refusal": _b(gate.get("false_refusal")),
        "false_downgrade": _b(gate.get("false_downgrade")),
        "gate_decision_correct": _b(gate.get("gate_decision_correct")),
        # review draft surface (sage_law only)
        "has_review_draft": 1 if rev else 0,
        "draft_safe": _b(rev.get("safe_to_release_derived")) if rev else None,
        "draft_mat_err": _b(rev.get("material_legal_error_present")) if rev else None,
        "draft_util": _i(rev.get("utility_score")) if rev else None,
        "draft_cov": _i(rev.get("criteria_coverage_score")) if rev else None,
        "draft_unsup_claims": _i(rev.get("unsupported_material_claim_count")) if rev else None,
    }
    rec["exposed_artifact"] = exposed_artifact(dec)
    if rec["exposed_artifact"] is None or rec["rel_safe"] is None:
        rec["unsafe_release"] = None
    else:
        rec["unsafe_release"] = int(rec["exposed_artifact"] == 1 and rec["rel_safe"] == 0)
    # Backward-compatible complement of safe_to_release on the released surface.
    rec["rel_unsafe"] = (1 - rec["rel_safe"]) if rec["rel_safe"] is not None else None
    return rec


def family(model: str) -> str:
    m = model.lower()
    if m.startswith("minimax"):
        return "MiniMax"
    if m.startswith("deepseek"):
        return "DeepSeek"
    return model or "unknown"


def gkey(r: dict) -> tuple:
    return (r["task_id"], r["context_mode"], r["generated_model"])


# ------------------------------------------------------------------- statistics
def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def wilson_ci(k: int, n: int, z: float = 1.96):
    if n == 0:
        return (None, None)
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def paired_group_bootstrap_delta(
    groups: list[tuple[float, float]], rng: random.Random, n_boot=N_BOOT
):
    """Return the paired group delta and a paired-group bootstrap interval."""
    pairs = [(s, b) for s, b in groups if s is not None and b is not None]
    if not pairs:
        return (None, None, None, 0)
    deltas = [s - b for s, b in pairs]
    md = sum(deltas) / len(deltas)
    n_groups = len(deltas)
    boots = []
    for _ in range(n_boot):
        sampled = [deltas[rng.randrange(n_groups)] for _ in range(n_groups)]
        boots.append(sum(sampled) / n_groups)
    boots.sort()
    lo = boots[int(0.025 * n_boot)]
    hi = boots[int(0.975 * n_boot)]
    return (md, lo, hi, n_groups)


def cohen_kappa(pairs: list[tuple[Any, Any]]):
    """Binary/categorical Cohen's kappa over (a,b) label pairs (drops None)."""
    pairs = [(a, b) for a, b in pairs if a is not None and b is not None]
    n = len(pairs)
    if n == 0:
        return (None, 0, None)
    labels = sorted({a for a, _ in pairs} | {b for _, b in pairs})
    po = sum(1 for a, b in pairs if a == b) / n
    pe = 0.0
    for lab in labels:
        pa = sum(1 for a, _ in pairs if a == lab) / n
        pb = sum(1 for _, b in pairs if b == lab) / n
        pe += pa * pb
    kappa = (po - pe) / (1 - pe) if (1 - pe) > 1e-12 else None
    return (kappa, n, po)


# ------------------------------------------------------------------- load data
def main() -> int:
    rng = random.Random(SEED)

    mimo_rows = load_ok(MIMO_PATTERNS); mimo_stats = load_ok.stats
    deepseek_rows = load_ok(DEEPSEEK_PATTERNS); ds_stats = load_ok.stats
    minimax_rows = load_ok(MINIMAX_PATTERNS); mm_stats = load_ok.stats
    gpt_rows = load_ok(GPT_PATTERNS); gpt_stats = load_ok.stats

    mimo = {k: leaf_record(r, "mimo-v2.5-pro") for k, r in mimo_rows.items()}
    deepseek = {k: leaf_record(r, "deepseek-v4-pro") for k, r in deepseek_rows.items()}
    minimax = {k: leaf_record(r, "MiniMax-M3") for k, r in minimax_rows.items()}
    gpt = {k: leaf_record(r, "gpt-5.4-mini") for k, r in gpt_rows.items()}

    stats: dict[str, Any] = {
        "meta": {
            "seed": SEED,
            "n_boot": N_BOOT,
            "experiments_dir": str(EXPERIMENTS),
            "wrappers": list(WRAPPERS),
        },
        "inventory": {
            "mimo_main": mimo_stats,
            "deepseek_on_minimax": ds_stats,
            "minimax_on_deepseek": mm_stats,
            "gpt_final_ok": gpt_stats,
        },
    }

    # ---- leaf-level CSV (all judges) -------------------------------------
    all_leaves = list(mimo.values()) + list(deepseek.values()) + list(minimax.values()) + list(gpt.values())
    fields = list(all_leaves[0].keys())
    with (TABLES / "leaf_labels_all_judges.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in all_leaves:
            w.writerow(r)

    # ---- per-wrapper released-surface rates (MIMO primary) ----------------
    BIN = ["rel_safe", "rel_unsafe", "unsafe_release", "exposed_artifact", "false_release", "false_refusal", "false_downgrade",
           "rel_mat_err", "rel_overcommit", "rel_unsup_rec", "rel_issue_omit"]
    NUM = ["rel_unsup_claims", "rel_util", "rel_cov"]

    def wrapper_rates(rows: list[dict], strata):
        out = []
        for strat in strata:
            sel = [r for r in rows if (strat == "all" or r["sample_stratum"] == strat)]
            for w in WRAPPERS:
                wr = [r for r in sel if r["wrapper"] == w]
                n = len(wr)
                row = {"stratum": strat, "wrapper": w, "n": n}
                for m in BIN:
                    vals = [r[m] for r in wr if r[m] is not None]
                    k = sum(vals); nn = len(vals)
                    row[m] = round(k / nn, 4) if nn else None
                    lo, hi = wilson_ci(k, nn)
                    row[m + "_lo"] = round(lo, 4) if lo is not None else None
                    row[m + "_hi"] = round(hi, 4) if hi is not None else None
                for m in NUM:
                    mv = mean([r[m] for r in wr])
                    row[m + "_mean"] = round(mv, 4) if mv is not None else None
                row["unsup_claim_pos_rate"] = round(
                    mean([1 if (r["rel_unsup_claims"] or 0) > 0 else 0 for r in wr]) or 0, 4)
                out.append(row)
        return out

    mimo_rates = wrapper_rates(list(mimo.values()), ["control", "high_risk", "all"])
    stats["per_wrapper_released_rates_mimo"] = mimo_rates
    _write_csv(TABLES / "per_wrapper_released_rates_mimo.csv", mimo_rates)

    # ---- paired deltas sage_law vs each baseline (MIMO) -------------------
    def grouped(rows):
        g = defaultdict(dict)
        for r in rows:
            g[gkey(r)][r["wrapper"]] = r
        return g

    def paired_deltas(rows, strata, metrics):
        g = grouped(rows)
        out = []
        for strat in strata:
            for base in BASELINES:
                for m in metrics:
                    pairs = []
                    for k, d in g.items():
                        if "sage_law" not in d or base not in d:
                            continue
                        if strat != "all" and d["sage_law"]["sample_stratum"] != strat:
                            continue
                        pairs.append((d["sage_law"][m], d[base][m]))
                    md, lo, hi, n_groups = paired_group_bootstrap_delta(pairs, rng)
                    sage_mean = mean([p[0] for p in pairs])
                    base_mean = mean([p[1] for p in pairs])
                    out.append({
                        "stratum": strat, "metric": m, "baseline": base,
                        "n_groups": n_groups,
                        "sage_law_mean": round(sage_mean, 4) if sage_mean is not None else None,
                        "baseline_mean": round(base_mean, 4) if base_mean is not None else None,
                        "delta_sage_minus_base": round(md, 4) if md is not None else None,
                        "ci_lo": round(lo, 4) if lo is not None else None,
                        "ci_hi": round(hi, 4) if hi is not None else None,
                        "significant": (lo is not None and (lo > 0 or hi < 0)),
                    })
        return out

    delta_metrics = ["rel_safe", "unsafe_release", "false_release", "rel_mat_err", "rel_unsup_claims",
                     "rel_overcommit", "rel_unsup_rec", "rel_issue_omit", "rel_util", "rel_cov"]
    deltas = paired_deltas(list(mimo.values()), ["control", "high_risk", "all"], delta_metrics)
    stats["paired_deltas_mimo"] = deltas
    _write_csv(TABLES / "paired_deltas_mimo.csv", deltas)

    # ---- draft vs release for sage_law ------------------------------------
    dvr = []
    sl = [r for r in mimo.values() if r["wrapper"] == "sage_law"]
    for strat in ["control", "high_risk", "all"]:
        sel = [r for r in sl if (strat == "all" or r["sample_stratum"] == strat)]
        with_d = [r for r in sel if r["has_review_draft"]]
        dvr.append({
            "stratum": strat, "n_sage": len(sel), "n_with_draft": len(with_d),
            "draft_safe_rate": round(mean([r["draft_safe"] for r in with_d]) or 0, 4) if with_d else None,
            "released_safe_rate": round(mean([r["rel_safe"] for r in sel]) or 0, 4),
            "draft_util_mean": round(mean([r["draft_util"] for r in with_d]) or 0, 4) if with_d else None,
            "released_util_mean": round(mean([r["rel_util"] for r in sel]) or 0, 4),
            "draft_cov_mean": round(mean([r["draft_cov"] for r in with_d]) or 0, 4) if with_d else None,
            "released_cov_mean": round(mean([r["rel_cov"] for r in sel]) or 0, 4),
            "false_release_rate": round(mean([r["false_release"] for r in sel]) or 0, 4),
            "false_refusal_rate": round(mean([r["false_refusal"] for r in sel]) or 0, 4),
            "false_downgrade_rate": round(mean([r["false_downgrade"] for r in sel]) or 0, 4),
        })
    stats["draft_vs_release_sage_mimo"] = dvr
    _write_csv(TABLES / "draft_vs_release_sage_mimo.csv", dvr)

    # ---- gate flow + gate justification (sage_law) ------------------------
    gate_flow = Counter()
    just = Counter()
    for r in sl:
        dec = r["gate_decision"]
        gate_flow[(r["sample_stratum"], dec)] += 1
        if r["has_review_draft"]:
            ds = "draft_unsafe" if r["draft_safe"] == 0 else "draft_safe"
        else:
            ds = "no_draft"
        just[(dec, ds)] += 1
    gf_rows = [{"stratum": s, "gate_decision": d, "n": n} for (s, d), n in sorted(gate_flow.items())]
    just_rows = [{"gate_decision": d, "draft_status": ds, "n": n} for (d, ds), n in sorted(just.items())]
    stats["gate_flow_mimo"] = gf_rows
    stats["gate_justification_mimo"] = just_rows
    _write_csv(TABLES / "gate_flow_mimo.csv", gf_rows)
    _write_csv(TABLES / "gate_justification_mimo.csv", just_rows)

    # ---- context-mode + family marginals (MIMO, released) -----------------
    def marginal(rows, by, metrics):
        out = []
        keys = sorted({r[by] for r in rows})
        for kv in keys:
            for w in WRAPPERS:
                wr = [r for r in rows if r[by] == kv and r["wrapper"] == w]
                row = {by: kv, "wrapper": w, "n": len(wr)}
                for m in metrics:
                    mv = mean([r[m] for r in wr])
                    row[m] = round(mv, 4) if mv is not None else None
                out.append(row)
        return out

    ctx = marginal(list(mimo.values()), "context_mode",
                   ["rel_safe", "false_release", "rel_util", "rel_cov"])
    fam = marginal(list(mimo.values()), "generated_family",
                   ["rel_safe", "false_release", "rel_util", "rel_cov"])
    stats["context_marginals_mimo"] = ctx
    stats["family_marginals_mimo"] = fam
    _write_csv(TABLES / "context_marginals_mimo.csv", ctx)
    _write_csv(TABLES / "family_marginals_mimo.csv", fam)

    # ---- high-risk vs control marginal (per wrapper) ----------------------
    hrc = []
    for w in WRAPPERS:
        for strat in ["control", "high_risk"]:
            wr = [r for r in mimo.values() if r["wrapper"] == w and r["sample_stratum"] == strat]
            hrc.append({
                "wrapper": w, "stratum": strat, "n": len(wr),
                "rel_safe": round(mean([r["rel_safe"] for r in wr]) or 0, 4),
                "false_release": round(mean([r["false_release"] for r in wr]) or 0, 4),
                "rel_util": round(mean([r["rel_util"] for r in wr]) or 0, 4),
            })
    stats["high_risk_vs_control_mimo"] = hrc
    _write_csv(TABLES / "high_risk_vs_control_mimo.csv", hrc)

    # ---- trace / confidence distributions (MIMO, per wrapper) -------------
    tcd = []
    for w in WRAPPERS:
        wr = [r for r in mimo.values() if r["wrapper"] == w]
        tc = Counter(r["trace_reconstructable"] for r in wr)
        cc = Counter(r["confidence"] for r in wr)
        tcd.append({"wrapper": w, "n": len(wr),
                    **{f"trace_{k}": tc.get(k, 0) for k in ("yes", "partial", "no", "not_applicable")},
                    **{f"conf_{k}": cc.get(k, 0) for k in ("high", "medium", "low")}})
    stats["trace_confidence_mimo"] = tcd
    _write_csv(TABLES / "trace_confidence_mimo.csv", tcd)

    # ---- failure taxonomy counts (released, per wrapper, by stratum) ------
    tax = []
    for strat in ["control", "high_risk", "all"]:
        for w in WRAPPERS:
            wr = [r for r in mimo.values() if r["wrapper"] == w and (strat == "all" or r["sample_stratum"] == strat)]
            n = len(wr)
            tax.append({
                "stratum": strat, "wrapper": w, "n": n,
                "unsupported_claim": round(mean([1 if (r["rel_unsup_claims"] or 0) > 0 else 0 for r in wr]) or 0, 4),
                "material_legal_error": round(mean([r["rel_mat_err"] for r in wr]) or 0, 4),
                "overcommitment": round(mean([r["rel_overcommit"] for r in wr]) or 0, 4),
                "unsupported_recommendation": round(mean([r["rel_unsup_rec"] for r in wr]) or 0, 4),
                "issue_omitted": round(mean([r["rel_issue_omit"] for r in wr]) or 0, 4),
            })
    stats["failure_taxonomy_mimo"] = tax
    _write_csv(TABLES / "failure_taxonomy_mimo.csv", tax)

    # ---- judge agreement on overlapping leaves ----------------------------
    def agreement(primary, other, name):
        keys = sorted(set(primary) & set(other))
        rows = {"pair": name, "n_overlap": len(keys)}
        for metric, label in [("rel_safe", "safe_to_release"), ("rel_mat_err", "material_legal_error"),
                              ("false_release", "false_release")]:
            pairs = [(primary[k][metric], other[k][metric]) for k in keys]
            kappa, n, po = cohen_kappa(pairs)
            rows[f"{label}_n"] = n
            rows[f"{label}_pct_agree"] = round(po, 4) if po is not None else None
            rows[f"{label}_kappa"] = round(kappa, 4) if kappa is not None else None
        # utility / coverage exact + within-1 agreement
        for metric, label in [("rel_util", "utility"), ("rel_cov", "coverage")]:
            pairs = [(primary[k][metric], other[k][metric]) for k in keys
                     if primary[k][metric] is not None and other[k][metric] is not None]
            if pairs:
                rows[f"{label}_exact"] = round(sum(1 for a, b in pairs if a == b) / len(pairs), 4)
                rows[f"{label}_within1"] = round(sum(1 for a, b in pairs if abs(a - b) <= 1) / len(pairs), 4)
                rows[f"{label}_mean_abs_diff"] = round(mean([abs(a - b) for a, b in pairs]), 4)
        return rows, keys

    agr = []
    a1, _ = agreement(mimo, deepseek, "mimo_vs_deepseek_on_minimax")
    a2, _ = agreement(mimo, minimax, "mimo_vs_minimax_on_deepseek")
    a3, gpt_keys = agreement(mimo, gpt, "mimo_vs_gpt_final")
    agr = [a1, a2, a3]
    stats["judge_agreement"] = agr
    _write_csv(TABLES / "judge_agreement.csv", agr)

    # ---- mimo vs gpt leaf-level disagreement table (60 leaves) ------------
    gv = []
    for k in gpt_keys:
        m, g = mimo[k], gpt[k]
        gv.append({
            "task_id": k[0], "context_mode": k[1], "generated_model": k[2], "wrapper": k[3],
            "selection_category": g["selection_category"], "gate_decision": m["gate_decision"],
            "mimo_safe": m["rel_safe"], "gpt_safe": g["rel_safe"], "safe_agree": int(m["rel_safe"] == g["rel_safe"]),
            "mimo_mat_err": m["rel_mat_err"], "gpt_mat_err": g["rel_mat_err"],
            "mimo_false_release": m["false_release"], "gpt_false_release": g["false_release"],
            "mimo_util": m["rel_util"], "gpt_util": g["rel_util"],
            "mimo_cov": m["rel_cov"], "gpt_cov": g["rel_cov"],
        })
    _write_csv(TABLES / "mimo_vs_gpt_leaf.csv", gv)
    stats["gpt_vs_mimo_summary"] = {
        "n": len(gv),
        "safe_pct_agree": round(mean([r["safe_agree"] for r in gv]) or 0, 4),
        "gpt_unsafe": sum(1 for r in gv if r["gpt_safe"] == 0),
        "mimo_unsafe": sum(1 for r in gv if r["mimo_safe"] == 0),
        "gpt_false_release": sum(1 for r in gv if r["gpt_false_release"] == 1),
        "mimo_false_release": sum(1 for r in gv if r["mimo_false_release"] == 1),
        "both_unsafe": sum(1 for r in gv if r["gpt_safe"] == 0 and r["mimo_safe"] == 0),
    }

    # ---- GPT enriched-sample wrapper view (stress test only) --------------
    gpt_w = []
    for w in WRAPPERS:
        wr = [r for r in gpt.values() if r["wrapper"] == w]
        gpt_w.append({
            "wrapper": w, "n": len(wr),
            "rel_safe": round(mean([r["rel_safe"] for r in wr]) or 0, 4),
            "false_release": round(mean([r["false_release"] for r in wr]) or 0, 4),
            "rel_util": round(mean([r["rel_util"] for r in wr]) or 0, 4),
        })
    stats["gpt_wrapper_view"] = gpt_w
    _write_csv(TABLES / "gpt_wrapper_view.csv", gpt_w)

    (HERE / "safety_stats.json").write_text(json.dumps(stats, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"event": "analysis_done",
                      "leaf_csv_rows": len(all_leaves),
                      "tables_dir": str(TABLES),
                      "stats_json": str(HERE / "safety_stats.json")}, ensure_ascii=False))
    return 0


def _write_csv(path: Path, rows: list[dict]):
    if not rows:
        path.write_text("")
        return
    fields = list(rows[0].keys())
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)


if __name__ == "__main__":
    raise SystemExit(main())
