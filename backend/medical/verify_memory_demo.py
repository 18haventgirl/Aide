"""Check persisted synthetic browser acceptance. Never opens the user's database."""
import argparse
import json
from pathlib import Path
import sqlite3


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    root = args.directory.resolve()
    allowed = Path(__file__).resolve().parents[1] / "data"
    if not root.is_relative_to(allowed) or not root.name.startswith("memory_acceptance"):
        raise ValueError("acceptance must use the isolated fixture directory")
    fixture = json.loads((root / "fixture.json").read_text(encoding="utf-8"))
    with sqlite3.connect((root / "aide.sqlite").as_uri() + "?mode=ro", uri=True) as database:
        database.row_factory = sqlite3.Row
        health = [dict(row) for row in database.execute("SELECT * FROM health_records WHERE user_id=1 AND status!='deleted'")]
        messages = [dict(row) for row in database.execute("SELECT id,conversation_id_str,sender_type,content,extra_data FROM chat_messages ORDER BY id")]
        headache = next(row for row in health if row["id"] == fixture["headache_id"])
        vital = next((row for row in health if row["record_type"] == "vital" and row["source"] == "conversation"), None)
        source = next((row for row in messages if vital and str(row["id"]) == vital["source_message_id"]), None)
        summaries = [row for row in messages if row["sender_type"] == "ai" and "18:15" in row["content"] and "36.8" in row["content"]]
        cross_session = any(vital and row["conversation_id_str"] != vital["source_conversation_id"] for row in summaries)
        correct_weekdays = any("2026-10-08（周四）" in row["content"] and "2026-10-09（周五）" in row["content"] for row in summaries)
        grounded = [json.loads(row["extra_data"]) for row in messages if row["extra_data"]]
        sources = sorted({item["doc_id"] for metadata in grounded if metadata.get("knowledge_status") == "grounded" for item in metadata.get("citations", [])})
        checks = {
            "headache_correction_1815": "18:15:00" in headache["observed_at"],
            "three_health_records_no_summary_or_rag_extra_writes": len(health) == 3,
            "vital_time_and_measurement": bool(vital and "09:00:00" in vital["observed_at"] and "36.8" in vital["summary"]),
            "source_is_saved_human_message": bool(source and source["sender_type"] == "human" and source["conversation_id_str"] == vital["source_conversation_id"]),
            "cross_conversation_summary": cross_session,
            "correct_weekday_summary": correct_weekdays,
            "rag_source_metadata": "NHC-HL2024-32" in sources,
        }
        report = {"scope": "synthetic_browser_api_storage_official_llm_acceptance_not_clinical",
            "fixture": fixture, "checks": checks, "passed": all(checks.values()),
            "health_count": len(health), "message_count": len(messages), "rag_doc_ids": sources,
            "retained_failures": {
                "first_wrong_resource_summary": any("没有找到任何身体状况相关的记录" in row["content"] for row in messages if row["sender_type"] == "ai"),
                "weekday_before_fix": any("2026-10-08（周三）" in row["content"] for row in messages if row["sender_type"] == "ai"),
                "noncanonical_detail_keys": bool(vital and "体温" in json.loads(vital["details_json"])),
            }, "limits": "small supervised synthetic flow; no clinical judgement or full network matrix; token cost not measured"}
    (root / "acceptance.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "checks": checks, "report": str(root / "acceptance.json")}, ensure_ascii=False))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__": main()
