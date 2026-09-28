"""Offline quantity audit; lexical overlap is NOT medical entailment.

Flags Arabic-number quantities absent from retrieved evidence. No remote calls,
no automatic rewriting, and no runtime logging of user health conversations.
"""
import argparse
import json
import re
import unicodedata
from pathlib import Path


_NUMBER = r"\d+(?:\.\d+)?"
_UNIT = r"毫克|毫升|分钟|小时|公斤|千克|千卡|摄氏度|mmhg|mmol/l|mg|ml|kg|°c|周|天|年|月|岁|次|片|粒|克|升|分|度|%"
_QUANTITY = re.compile(rf"(?<![0-9a-z.])({_NUMBER})(?:\s*([-–—~～至到])\s*({_NUMBER}))?\s*({_UNIT})(?![a-z])", re.I)


def quantities(text: str) -> list[dict]:
    text = unicodedata.normalize("NFKC", text).lower()
    # Links and reference identifiers do not constitute numerical claims.
    text = re.sub(r"https?://[^\s)]+|\[e\d+\]", "", text)
    result = []
    for match in _QUANTITY.finditer(text):
        low, _, high, unit = match.groups()
        unit = {"mg": "毫克", "ml": "毫升", "kg": "千克", "公斤": "千克",
                "°c": "摄氏度"}.get(unit, unit)
        # NFKC turns ℃ into °C.
        key = f"{low}{'-' + high if high else ''}{unit}"
        result.append({"quantity": match.group(), "key": key})
    return result


def audit_answer(answer: str, hits: list[dict]) -> dict:
    evidence = {}
    for hit in hits:
        for item in quantities(str(hit.get("text") or "")):
            evidence.setdefault(item["key"], set()).add(str(hit.get("doc_id") or "unknown"))
    seen = set()
    observations = []
    for item in quantities(answer):
        if item["key"] in seen:
            continue
        seen.add(item["key"])
        docs = sorted(evidence.get(item["key"], []))
        observations.append({**item, "matching_doc_ids": docs,
                             "status": "lexical_match_only" if docs else "not_found_in_evidence"})
    return {
        "audit_version": "arabic_quantities_v1",
        "scope": "lexical_screen_only_not_medical_or_semantic_verification",
        "quantity_count": len(observations),
        "unmatched_count": sum(x["status"] == "not_found_in_evidence" for x in observations),
        "observations": observations,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="local JSON with answer and hits")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = json.loads(args.input.read_text(encoding="utf-8"))
    report = audit_answer(source["answer"], source.get("hits", []))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
