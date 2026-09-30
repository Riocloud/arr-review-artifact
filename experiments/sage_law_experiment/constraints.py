"""Post-model SAGE-Law constraints and release adapter.

This module is intentionally outside the model call path. Prompts may ask for
careful behavior, but only this layer decides whether generated work product is
eligible for the benchmark output channel.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .authority import make_artifact_bundle, required_predicates
from .deliverables import write_deliverable_set


def evaluate_constraints(
    task: dict[str, Any],
    wrapper: str,
    deliverables: dict[str, str],
    task_context: dict[str, Any] | None = None,
    parse_error: str | None = None,
) -> dict[str, Any]:
    if wrapper != "sage_law":
        bundle = make_artifact_bundle(task, wrapper)
        bundle["candidate"]["artifact_hash"] = artifact_hash(deliverables)
        bundle["candidate"]["expected_deliverables"] = list(deliverables)
        return bundle

    predicates = required_predicates(task)
    if "output_contract_checked" not in predicates:
        predicates = sorted(set(predicates + ["output_contract_checked"]))

    validators = [
        validator("trace_reconstructable", True, "Trace artifacts are written by the harness."),
        validator("issue_inventory_loaded", bool(task.get("criteria_count", 0)), "Issue inventory comes from Harvey criteria."),
        validator("output_contract_checked", output_contract_ok(task, deliverables) and not parse_error, parse_error or "All expected deliverables parsed."),
    ]
    validator_map = {v["predicate"]: v for v in validators}

    dynamic_checks = {
        "source_support_checked": source_support_ok(task, deliverables),
        "jurisdiction_checked": jurisdiction_ok(task, deliverables),
        "authority_status_checked": authority_status_ok(task, deliverables),
        "issue_coverage_checked": issue_coverage_ok(task, deliverables, task_context),
        "recommendation_gate_checked": recommendation_gate_ok(task, deliverables),
        "release_gate_checked": release_gate_ok(task, deliverables),
    }
    dynamic_notes = {
        "source_support_checked": "Requires source/citation/document markers for source-sensitive tasks.",
        "jurisdiction_checked": "Requires jurisdiction/governing-law markers for jurisdiction-sensitive tasks.",
        "authority_status_checked": "Requires bounded authority-status characterization for authority-sensitive tasks.",
        "issue_coverage_checked": "Requires visible coverage of rubric-derived issue terms.",
        "recommendation_gate_checked": "Client-action recommendations must be review-gated or reserved.",
        "release_gate_checked": "Release receipt can be issued only if all required predicates pass.",
    }
    for predicate_name in predicates:
        if predicate_name in validator_map:
            continue
        passed = dynamic_checks.get(predicate_name, True)
        validators.append(validator(predicate_name, passed, dynamic_notes.get(predicate_name, "Predicate satisfied.")))

    unsatisfied = [v["predicate"] for v in validators if not v["passed"]]
    has_blocking_debt = bool(unsatisfied)
    candidate = make_artifact_bundle(task, wrapper)["candidate"]
    candidate["artifact_hash"] = artifact_hash(deliverables)
    candidate["expected_deliverables"] = list(deliverables)
    candidate["release_mode"] = "benchmark_review_draft"

    receipts = []
    for v in validators:
        if v["passed"]:
            receipt_type = receipt_type_for(v["predicate"])
            if receipt_type != "releaseReceipt":
                receipts.append(receipt(receipt_type, v, candidate))
    if not has_blocking_debt:
        release_validator = validator_map_by_predicate(validators).get("release_gate_checked")
        receipts.append(receipt("releaseReceipt", release_validator or validators[0], candidate))

    gate = {
        "schema_version": "sage-law.gate-decision.v1",
        "wrapper": wrapper,
        "decision": "blocked_or_escalated" if has_blocking_debt else "review_gated_draft",
        "release_mode": "benchmark_review_draft",
        "blocking_debt": has_blocking_debt,
        "receipt_count": len(receipts),
        "artifact_hash": candidate["artifact_hash"],
    }
    debt = {
        "schema_version": "sage-law.coverage-debt.v1",
        "task_id": task["task_id"],
        "wrapper": wrapper,
        "unsatisfied_predicates": unsatisfied,
        "debt_by_type": debt_by_type(unsatisfied),
        "blocking": has_blocking_debt,
    }

    base = make_artifact_bundle(task, wrapper)
    base.update(
        {
            "candidate": candidate,
            "validators": validators,
            "coverage_debt": debt,
            "receipts": receipts,
            "gate_decision": gate,
        }
    )
    return base


def apply_release_adapter(
    run_dir: Path,
    task: dict[str, Any],
    wrapper: str,
    deliverables: dict[str, str],
    bundle: dict[str, Any],
) -> None:
    if wrapper != "sage_law":
        write_deliverable_set(run_dir / "output", deliverables)
        return

    write_deliverable_set(run_dir / "review_output", deliverables)
    gate = bundle["gate_decision"]
    if gate["decision"] == "review_gated_draft":
        write_deliverable_set(run_dir / "output", deliverables)
        return

    notice = blocked_deliverables(task, bundle)
    write_deliverable_set(run_dir / "output", notice)


def output_contract_ok(task: dict[str, Any], deliverables: dict[str, str]) -> bool:
    expected = set(task.get("deliverables") or [])
    if not expected:
        return bool(deliverables)
    return expected.issubset(deliverables) and all(deliverables[name].strip() for name in expected)


def source_support_ok(task: dict[str, Any], deliverables: dict[str, str]) -> bool:
    if "source_support" not in task.get("failure_modes", []):
        return True
    text = joined(deliverables)
    return bool(re.search(r"\b(source|citation|cited|document|exhibit|clause|section|according to|based on)\b", text, re.I))


def jurisdiction_ok(task: dict[str, Any], deliverables: dict[str, str]) -> bool:
    if "jurisdiction_governing_law" not in task.get("failure_modes", []):
        return True
    text = joined(deliverables)
    return bool(re.search(r"\b(jurisdiction|governing law|forum|venue|delaware|new york|california|texas|federal)\b", text, re.I))


def authority_status_ok(task: dict[str, Any], deliverables: dict[str, str]) -> bool:
    if "authority_status" not in task.get("failure_modes", []):
        return True
    text = joined(deliverables)
    if re.search(r"\b(controlling|binding|governing)\b", text, re.I):
        return bool(re.search(r"\b(authority status|jurisdiction|source|citation|cited|persuasive|unless counsel confirms)\b", text, re.I))
    return bool(re.search(r"\b(authority|statute|regulation|case|citation|source|persuasive)\b", text, re.I))


def issue_coverage_ok(task: dict[str, Any], deliverables: dict[str, str], task_context: dict[str, Any] | None) -> bool:
    if "issue_coverage" not in task.get("failure_modes", []):
        return True
    text = joined(deliverables).lower()
    criteria = (task_context or {}).get("task", {}).get("criteria") or []
    terms = []
    for criterion in criteria[:12]:
        title = criterion.get("title", "")
        terms.extend(word for word in re.findall(r"[A-Za-z][A-Za-z-]{3,}", title.lower()) if word not in STOPWORDS)
    if not terms:
        return len(text) > 500
    covered = sum(1 for term in sorted(set(terms)) if term in text)
    return covered >= min(3, max(1, len(set(terms)) // 4))


def recommendation_gate_ok(task: dict[str, Any], deliverables: dict[str, str]) -> bool:
    if "recommendation_authority" not in task.get("failure_modes", []):
        return True
    text = joined(deliverables)
    has_recommendation = bool(re.search(r"\b(recommend|should|must|client action|terminate|file|send|execute)\b", text, re.I))
    if not has_recommendation:
        return True
    return bool(re.search(r"\b(attorney review|counsel review|review required|coverage debt|escalat|reserved|draft)\b", text, re.I))


def release_gate_ok(task: dict[str, Any], deliverables: dict[str, str]) -> bool:
    if "privilege_release_review" not in task.get("failure_modes", []):
        return True
    text = joined(deliverables)
    return bool(
        re.search(
            r"\b(attorney review|counsel review|review required|privilege|confidential|redact|benchmark review|draft)\b",
            text,
            re.I,
        )
    )


def blocked_deliverables(task: dict[str, Any], bundle: dict[str, Any]) -> dict[str, str]:
    predicates = bundle["coverage_debt"]["unsatisfied_predicates"]
    text = "\n".join(
        [
            "BLOCKED_BY_SAGE_LAW",
            "",
            "This benchmark artifact was not released as work product because the external SAGE-Law release adapter found blocking coverage debt.",
            "",
            "Unsatisfied predicates:",
            *[f"- {predicate}" for predicate in predicates],
        ]
    )
    return {filename: text for filename in task.get("deliverables", [])}


def validator(predicate: str, passed: bool, notes: str) -> dict[str, Any]:
    return {
        "validator_id": f"validator.{predicate}",
        "predicate": predicate,
        "type": "external_harness",
        "passed": bool(passed),
        "notes": notes,
    }


def receipt(receipt_type: str, validator_obj: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "receipt_id": f"{receipt_type}.{validator_obj['predicate']}",
        "receipt_type": receipt_type,
        "artifact_hash": candidate["artifact_hash"],
        "matter_hash": candidate["task_id"],
        "claim_ids": [claim["claim_id"] for claim in candidate.get("material_claims", [])],
        "witness_ids": [],
        "validator_ids": [validator_obj["validator_id"]],
        "jurisdiction": "benchmark_proxy",
        "authority_status": "policy_checked_not_legal_truth",
        "review_scope": "benchmark_review_draft",
        "audience": candidate.get("audience", "benchmark_reviewer"),
        "release_mode": candidate.get("release_mode", "benchmark_review_draft"),
        "issued_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": None,
        "gate_id": receipt_type.replace("Receipt", "Gate"),
    }


def receipt_type_for(predicate: str) -> str:
    if predicate.startswith("source"):
        return "citationReceipt"
    if predicate.startswith("jurisdiction"):
        return "jurisdictionReceipt"
    if predicate.startswith("authority"):
        return "authorityStatusReceipt"
    if predicate.startswith("issue"):
        return "issueCoverageReceipt"
    if predicate.startswith("recommendation"):
        return "recommendationReceipt"
    if predicate.startswith("release"):
        return "releaseReceipt"
    if predicate.startswith("trace"):
        return "traceReceipt"
    return "evidenceReceipt"


def debt_by_type(predicates: list[str]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for predicate in predicates:
        key = predicate.replace("_checked", "_debt")
        grouped.setdefault(key, []).append(predicate)
    return grouped


def validator_map_by_predicate(validators: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {v["predicate"]: v for v in validators}


def artifact_hash(deliverables: dict[str, str]) -> str:
    payload = json.dumps(deliverables, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def joined(deliverables: dict[str, str]) -> str:
    return "\n\n".join(deliverables.values())


STOPWORDS = {
    "with",
    "from",
    "that",
    "this",
    "into",
    "should",
    "agent",
    "output",
    "produced",
    "listed",
    "assigned",
    "different",
}
