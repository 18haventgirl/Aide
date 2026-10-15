"""Source-range retention metrics, distinct from semantic answer correctness."""
from ..source_provenance import body_hash


def validate_references(cases, documents):
    by_id = {doc.doc_id: doc for doc in documents}
    for case in cases:
        references = case.get("expected_evidence", [])
        if not isinstance(references, list):
            raise ValueError(f"invalid evidence labels: {case['id']}")
        seen = set()
        for reference in references:
            if not isinstance(reference, dict):
                raise ValueError(f"invalid evidence labels: {case['id']}")
            doc_id = reference.get("doc_id")
            if not isinstance(doc_id, str) or doc_id not in by_id or doc_id in seen:
                raise ValueError(f"invalid or duplicate evidence source: {case['id']}")
            seen.add(doc_id)
            doc = by_id[doc_id]
            if (doc_id not in case.get("expected_doc_ids", []) or type(reference.get("version")) is not int
                    or reference.get("version") != doc.version
                    or reference.get("body_sha256") != body_hash(doc.body)):
                raise ValueError(f"evidence source snapshot mismatch: {case['id']}")
            if not reference.get("ranges"):
                raise ValueError(f"empty evidence ranges: {case['id']}")
            for field in ("ranges", "required_conditions"):
                ranges = reference.get(field, [])
                if not isinstance(ranges, list):
                    raise ValueError(f"invalid evidence ranges: {case['id']}")
                unique = set()
                for span in ranges:
                    if (not isinstance(span, list) or len(span) != 2
                            or any(type(n) is not int for n in span)
                            or not 0 <= span[0] < span[1] <= len(doc.body)
                            or not doc.body[span[0]:span[1]].strip() or tuple(span) in unique):
                        raise ValueError(f"invalid evidence range: {case['id']}")
                    unique.add(tuple(span))


def score_ranges(pack, references, documents):
    covered = {}
    for row in pack["hits"]:
        mapping = row["source_mapping"]
        doc = documents.get(row["doc_id"])
        if (not doc or mapping["status"] == "unmapped" or mapping.get("document_version") != doc.version
                or mapping.get("body_sha256") != body_hash(doc.body)):
            continue
        covered.setdefault(doc.doc_id, []).extend(mapping["ranges"])

    def retained(doc, span):
        positions = {i for start, end in covered.get(doc.doc_id, []) for i in range(start, end)}
        required = {i for i in range(*span) if not doc.body[i].isspace()}
        return bool(required) and required.issubset(positions)

    spans, conditions = [], []
    for ref in references:
        doc = documents[ref["doc_id"]]
        spans.extend(retained(doc, span) for span in ref["ranges"])
        conditions.extend(retained(doc, span) for span in ref.get("required_conditions", []))
    return {"evidence_spans": len(spans), "retained_spans": sum(spans),
            "critical_conditions": len(conditions), "retained_conditions": sum(conditions)}
