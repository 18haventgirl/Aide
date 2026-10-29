"""Fail-closed contracts for FUTURE development/held-out evidence datasets.

Passing this catches mechanical leakage; it cannot prove semantic independence
or turn developer-written questions into an external blind evaluation.
"""
from collections import Counter
import re
import unicodedata

from ..evaluate import validate_cases
from .metrics import validate_references


def normalized_query(case):
    def normalize(value):
        if not isinstance(value, str):
            raise ValueError("query and history must be strings")
        return "".join(c for c in unicodedata.normalize("NFKC", value).lower() if c.isalnum())
    # Mirror evaluate(): only followup history reaches the retrieval query.
    # Preserve the role boundary rather than concatenating facts into the query.
    history = case.get("history", "") if case.get("kind") == "followup" else ""
    return normalize(case["query"])+"\n"+normalize(history)


def _grams(text):
    n = 3 if len(text) >= 16 else 2
    return {text[i:i+n] for i in range(max(1, len(text)-n+1))}


def validate_partitions(partitions, documents, *, similarity_threshold=.85, exposure_sets=None):
    if set(partitions) != {"development", "validation"}:
        raise ValueError("expected development and validation partitions")
    if type(similarity_threshold) not in {int, float} or not .5 <= similarity_threshold <= 1:
        raise ValueError("invalid near-duplicate threshold")
    owners, normalized, families, templates = {}, {}, {}, {}
    errors, prepared = [], {}
    document_ids = {d.doc_id for d in documents}
    for split, cases in partitions.items():
        validate_cases(cases)
        validate_references(cases, documents)
        prepared[split] = []
        for case in cases:
            identifier = case["id"]
            if case.get("kind", "supported") != "followup" and case.get("history", "") != "":
                errors.append({"case": identifier, "reason": "history_unused_by_query_contract"})
            if not set(case.get("forbidden_doc_ids", [])).issubset(document_ids):
                errors.append({"case": identifier, "reason": "unknown_forbidden_source"})
            if identifier in owners: errors.append({"case": identifier, "reason": "id_reused", "other_split": owners[identifier]})
            owners[identifier] = split
            for field, ledger in (("family_id", families), ("template_id", templates)):
                value = case.get(field)
                if not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{2,63}", value):
                    errors.append({"case": identifier, "reason": f"invalid_{field}"})
                    continue
                if value in ledger and ledger[value] != split:
                    errors.append({"case": identifier, "reason": f"cross_split_{field}", "value": value})
                ledger[value] = split
            if case.get("split") != split or not isinstance(case.get("topic"), str) or not case["topic"].strip():
                errors.append({"case": identifier, "reason": "missing_or_wrong_partition_metadata"})
            if split == "validation" and case.get("exposed_for_changes") is not False:
                errors.append({"case": identifier, "reason": "validation_exposure_unverified_or_exposed"})
            elif type(case.get("exposed_for_changes")) is not bool:
                errors.append({"case": identifier, "reason": "exposure_metadata_not_boolean"})
            if case.get("kind", "supported") in {"supported", "followup"}:
                sources = {r["doc_id"] for r in case.get("expected_evidence", [])}
                if sources != set(case.get("expected_doc_ids", [])):
                    errors.append({"case": identifier, "reason": "positive_sources_need_exact_range_labels"})
            norm = normalized_query(case)
            if norm in normalized:
                errors.append({"case": identifier, "reason": "duplicate_query_and_facts", "other_case": normalized[norm]})
            normalized[norm] = identifier
            prepared[split].append((case, _grams(norm)))
    similar = []
    for left, a in prepared["development"]:
        for right, b in prepared["validation"]:
            score = len(a & b)/len(a | b) if a or b else 1
            if score >= similarity_threshold:
                similar.append({"development": left["id"], "validation": right["id"], "jaccard": round(score, 4)})
    prior_matches = []
    for name, cases in (exposure_sets or {}).items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError("exposure set requires a name")
        # Prior labels may refer to an older corpus, so validate their shape only.
        validate_cases(cases)
        for prior in cases:
            norm = normalized_query(prior)
            grams = _grams(norm)
            for current, current_grams in prepared["validation"]:
                reasons = []
                if current["id"] == prior["id"]: reasons.append("exposed_id_reused")
                if normalized_query(current) == norm: reasons.append("exposed_query_and_facts_reused")
                for field in ("family_id", "template_id"):
                    if isinstance(prior.get(field), str) and prior[field] == current.get(field):
                        reasons.append(f"exposed_{field}_reused")
                score = len(grams & current_grams)/len(grams | current_grams) if grams or current_grams else 1
                if score >= similarity_threshold: reasons.append("exposed_near_duplicate")
                if reasons:
                    prior_matches.append({"validation": current["id"], "exposure_set": name,
                                          "exposed_case": prior["id"], "reasons": reasons,
                                          "jaccard": round(score, 4)})
    return {"contract": "evidence_partition_v2", "valid": not errors and not similar and not prior_matches,
            "scope": "mechanical_leakage_checks_not_external_blindness_or_semantic_independence",
            "errors": errors, "near_duplicates_requiring_review": similar,
            "prior_exposure_matches": prior_matches,
            "exposure_sets_checked": {name: len(cases) for name, cases in (exposure_sets or {}).items()},
            "similarity_threshold": similarity_threshold,
            "counts": {split: dict(Counter(c.get("kind", "supported") for c in cases)) for split, cases in partitions.items()},
            "shared_source_ids": sorted({d for c in partitions["development"] for d in c.get("expected_doc_ids", [])}
                                        & {d for c in partitions["validation"] for d in c.get("expected_doc_ids", [])})}
