"""Dry-run SAGE-Law authority artifacts.

These functions intentionally do not claim legal correctness. They create the
artifact shape and gate behavior needed for smoke testing before real model and
judge calls are wired in.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

WRAPPERS = ("raw_agent", "rag_agent", "cbea_lcv_legal", "sage_law")


def stable_hash(obj: Any) -> str:
    payload = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_matter_state(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "sage-law.matter-state.v1",
        "task_id": task["task_id"],
        "practice_area": task["practice_area"],
        "work_type": task["work_type"],
        "facts": {
            "source": "harvey_task_materials",
            "document_count": task["document_count"],
            "document_ext_counts": task["document_ext_counts"],
        },
        "documents": {
            "deliverables": task["deliverables"],
        },
        "jurisdiction": {
            "status": "benchmark_proxy",
            "detected_from_task": "jurisdiction_governing_law" in task["failure_modes"],
        },
        "governing_law": {
            "status": "unresolved_unless_supported_by_task_materials",
        },
        "issue_inventory": {
            "source": "harvey_rubric_titles_and_match_criteria",
            "criteria_count": task["criteria_count"],
        },
        "authority_graph": {
            "status": "not_promoted_in_dry_run",
        },
        "confidentiality": {
            "status": "benchmark_proxy",
        },
        "review_state": {
            "level": "machine_only",
        },
        "release_state": {
            "requested": "benchmark_review_draft",
        },
    }


def make_candidate(task: dict[str, Any], wrapper: str) -> dict[str, Any]:
    requested_level = "review_gated_draft" if wrapper == "sage_law" else "ungated_work_product"
    material_claims = [
        {
            "claim_id": f"C{i + 1:03d}",
            "source": "rubric_proxy",
            "description": mode,
        }
        for i, mode in enumerate(task["failure_modes"])
    ]
    return {
        "schema_version": "sage-law.candidate.v1",
        "task_id": task["task_id"],
        "wrapper": wrapper,
        "artifact_type": task["work_type"] or "legal_work_product",
        "requested_authority_level": requested_level,
        "audience": "benchmark_reviewer",
        "material_claims": material_claims,
        "jurisdiction_claims": {
            "present": "jurisdiction_governing_law" in task["failure_modes"],
        },
        "governing_law_claims": {
            "present": "jurisdiction_governing_law" in task["failure_modes"],
        },
        "issue_map": {
            "criteria_count": task["criteria_count"],
            "required_issue_source": "harvey_rubric",
        },
        "citation_map": {
            "required": "source_support" in task["failure_modes"],
        },
        "release_mode": "benchmark_review_draft",
        "privilege_labels": ["benchmark_proxy"],
        "required_predicates": required_predicates(task),
        "forbidden_effects": forbidden_effects(task),
    }


def required_predicates(task: dict[str, Any]) -> list[str]:
    predicates = ["trace_reconstructable", "issue_inventory_loaded"]
    mode_to_predicate = {
        "source_support": "source_support_checked",
        "jurisdiction_governing_law": "jurisdiction_checked",
        "authority_status": "authority_status_checked",
        "issue_coverage": "issue_coverage_checked",
        "recommendation_authority": "recommendation_gate_checked",
        "privilege_release_review": "release_gate_checked",
    }
    for mode in task["failure_modes"]:
        predicates.append(mode_to_predicate[mode])
    return sorted(set(predicates))


def forbidden_effects(task: dict[str, Any]) -> list[str]:
    effects = ["release_without_trace"]
    if "source_support" in task["failure_modes"]:
        effects.append("uncited_legal_conclusion")
    if "jurisdiction_governing_law" in task["failure_modes"]:
        effects.append("controlling_authority_without_jurisdiction_receipt")
    if "recommendation_authority" in task["failure_modes"]:
        effects.append("client_action_recommendation_without_recommendation_receipt")
    if "privilege_release_review" in task["failure_modes"]:
        effects.append("external_release_without_review_or_privilege_receipt")
    return effects


def make_witnesses(task: dict[str, Any]) -> list[dict[str, Any]]:
    witnesses = [
        {
            "witness_id": "issue_inventory.harvey_rubric",
            "type": "issue_witness",
            "promoted": True,
            "source": "task.criteria",
            "scope": {"criteria_count": task["criteria_count"]},
        },
        {
            "witness_id": "document_record.harvey_documents",
            "type": "fact_witness",
            "promoted": True,
            "source": "task.documents",
            "scope": {"document_count": task["document_count"]},
        },
    ]
    if "jurisdiction_governing_law" in task["failure_modes"]:
        witnesses.append(
            {
                "witness_id": "jurisdiction.detected_from_rubric",
                "type": "jurisdiction_witness",
                "promoted": False,
                "source": "dry_run_detection",
                "scope": {"requires_manual_or_benchmark_grounding": True},
            }
        )
    if "authority_status" in task["failure_modes"]:
        witnesses.append(
            {
                "witness_id": "authority_status.detected_from_rubric",
                "type": "authority_status_witness",
                "promoted": False,
                "source": "dry_run_detection",
                "scope": {"requires_manual_or_benchmark_grounding": True},
            }
        )
    return witnesses


def make_validators(task: dict[str, Any], wrapper: str) -> list[dict[str, Any]]:
    validators = []
    for predicate in required_predicates(task):
        validators.append(
            {
                "validator_id": f"validator.{predicate}",
                "predicate": predicate,
                "type": "structural_dry_run",
                "passed": wrapper == "sage_law" or predicate in {"trace_reconstructable", "issue_inventory_loaded"},
                "notes": "Dry-run predicate check only; real run must bind source spans, model outputs, and judge/audit labels.",
            }
        )
    return validators


def make_debt(task: dict[str, Any], wrapper: str, validators: list[dict[str, Any]]) -> dict[str, Any]:
    unsatisfied = [v["predicate"] for v in validators if not v["passed"]]
    debt_by_type: dict[str, list[str]] = {}
    for predicate in unsatisfied:
        debt_type = predicate.replace("_checked", "_debt")
        debt_by_type.setdefault(debt_type, []).append(predicate)
    return {
        "schema_version": "sage-law.coverage-debt.v1",
        "task_id": task["task_id"],
        "wrapper": wrapper,
        "unsatisfied_predicates": unsatisfied,
        "debt_by_type": debt_by_type,
        "blocking": bool(unsatisfied),
    }


def make_receipts(
    task: dict[str, Any],
    wrapper: str,
    candidate: dict[str, Any],
    matter_state: dict[str, Any],
    validators: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    receipts = []
    if wrapper != "sage_law":
        return receipts
    matter_hash = stable_hash(matter_state)
    artifact_hash = stable_hash(candidate)
    for validator in validators:
        if not validator["passed"]:
            continue
        receipt_type = predicate_to_receipt_type(validator["predicate"])
        receipts.append(
            {
                "receipt_id": f"{receipt_type}.{validator['predicate']}",
                "receipt_type": receipt_type,
                "artifact_hash": artifact_hash,
                "matter_hash": matter_hash,
                "claim_ids": [claim["claim_id"] for claim in candidate["material_claims"]],
                "witness_ids": ["issue_inventory.harvey_rubric", "document_record.harvey_documents"],
                "validator_ids": [validator["validator_id"]],
                "jurisdiction": "benchmark_proxy",
                "authority_status": "not_characterized_in_dry_run",
                "review_scope": "benchmark_review_draft",
                "audience": candidate["audience"],
                "release_mode": candidate["release_mode"],
                "issued_at": now_iso(),
                "expires_at": None,
                "gate_id": receipt_type.replace("Receipt", "Gate"),
            }
        )
    return receipts


def predicate_to_receipt_type(predicate: str) -> str:
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


def make_gate_decision(
    task: dict[str, Any],
    wrapper: str,
    debt: dict[str, Any],
    receipts: list[dict[str, Any]],
) -> dict[str, Any]:
    if wrapper != "sage_law":
        return {
            "schema_version": "sage-law.gate-decision.v1",
            "wrapper": wrapper,
            "decision": "ungated_baseline_output",
            "release_mode": "baseline_output",
            "blocking_debt": debt["blocking"],
            "receipt_count": len(receipts),
        }
    required_release = "release_gate_checked" in required_predicates(task)
    has_release = any(r["receipt_type"] == "releaseReceipt" for r in receipts)
    decision = "review_gated_draft"
    if required_release and not has_release:
        decision = "attorney_review_required"
    if debt["blocking"]:
        decision = "blocked_or_escalated"
    return {
        "schema_version": "sage-law.gate-decision.v1",
        "wrapper": wrapper,
        "decision": decision,
        "release_mode": "benchmark_review_draft",
        "blocking_debt": debt["blocking"],
        "receipt_count": len(receipts),
    }


def make_artifact_bundle(task: dict[str, Any], wrapper: str) -> dict[str, Any]:
    matter_state = make_matter_state(task)
    candidate = make_candidate(task, wrapper)
    witnesses = make_witnesses(task)
    validators = make_validators(task, wrapper)
    debt = make_debt(task, wrapper, validators)
    receipts = make_receipts(task, wrapper, candidate, matter_state, validators)
    gate = make_gate_decision(task, wrapper, debt, receipts)
    return {
        "matter_state": matter_state,
        "candidate": candidate,
        "witnesses": witnesses,
        "validators": validators,
        "coverage_debt": debt,
        "receipts": receipts,
        "gate_decision": gate,
    }
