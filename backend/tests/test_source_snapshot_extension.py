"""Snapshot evolution preserves history and refuses partial/tampered imports."""
from contextlib import ExitStack
import copy
from datetime import date
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from medical.audit_source_snapshot import audit_snapshot, original_asset_path
from medical.build_source_snapshot import build_snapshot
from tests import test_source_snapshot as snapshot_fixtures
from tests.test_source_origins import fixture


class ExtensionTests(unittest.TestCase):
    def context(self, directory):
        root = Path(directory)
        old, medical, raw, state = snapshot_fixtures.SnapshotTests().make_snapshot(root)
        parent = root/"medical-rag-data/datasets/v1"
        shutil.copytree(old, parent)
        stack = ExitStack()
        for module in ("medical.audit_source_snapshot", "medical.build_source_snapshot"):
            stack.enter_context(patch(f"{module}.ROOT", root))
            stack.enter_context(patch(f"{module}.MEDICAL", medical))
        stack.enter_context(patch("medical.build_source_snapshot.repository_version", return_value={"commit": "fixture"}))
        return root, parent, raw, state, stack

    def bundle(self, raw, doc_id):
        doc, origin = fixture(raw)
        doc = doc.model_copy(update={"doc_id": doc_id})
        origin["doc_id"] = doc_id
        return {"document": doc.model_dump(mode="json"), "origin": origin}

    def test_multiple_additions_and_origin_completion_preserve_all_parent_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root, parent, raw, _, stack = self.context(directory)
            with stack:
                before = {str(p.relative_to(parent)): p.read_bytes() for p in parent.rglob("*") if p.is_file()}
                output = parent.with_name("v2")
                origin = self.bundle(raw, "NEW-SOURCE")["origin"]
                report = build_snapshot(parent, output, raw_root=raw, as_of=date(2026, 10, 27),
                                        bundles=[self.bundle(raw, "SECOND"), self.bundle(raw, "THIRD")], origins=[origin])
                self.assertEqual(report["added_doc_ids"], ["NEW-SOURCE", "SECOND", "THIRD"])
                self.assertEqual(report["documents"], 4)
                self.assertEqual(report["pending_origin_documents"], [])
                self.assertFalse(report["serving_index_switched"])
                self.assertEqual(before, {str(p.relative_to(parent)): p.read_bytes() for p in parent.rglob("*") if p.is_file()})
                for path in (parent/"corpus").glob("*.json"):
                    self.assertEqual(path.read_bytes(), (output/"corpus"/path.name).read_bytes())
                with self.assertRaises(FileExistsError):
                    build_snapshot(parent, output, raw_root=raw, origins=[origin])

    def test_parent_mutation_breaks_child_audit(self):
        with tempfile.TemporaryDirectory() as directory:
            root, parent, raw, state, stack = self.context(directory)
            with stack:
                output = parent.with_name("v2")
                build_snapshot(parent, output, raw_root=raw, bundles=[self.bundle(raw, "SECOND")])
                (parent/"snapshot_manifest.json").write_text(json.dumps({**state, "note": "changed"}), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "parent snapshot manifest differs"):
                    audit_snapshot(output, raw)

    def test_new_schema_cannot_drop_ancestry_or_downgrade_its_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            root, parent, raw, _, stack = self.context(directory)
            with stack:
                output = parent.with_name("v2")
                build_snapshot(parent, output, raw_root=raw, bundles=[self.bundle(raw, "SECOND")])
                target = output/"snapshot_manifest.json"
                state = json.loads(target.read_text(encoding="utf-8"))
                for field in ("parent_snapshot", "origin_updates", "added_doc_ids", "schema_version"):
                    bad = dict(state); bad.pop(field)
                    target.write_text(json.dumps(bad), encoding="utf-8")
                    with self.subTest(field=field), self.assertRaises(ValueError):
                        audit_snapshot(output, raw)
                for schema in (0, 3, True, "2"):
                    target.write_text(json.dumps({**state, "schema_version": schema}), encoding="utf-8")
                    with self.subTest(schema=schema), self.assertRaises(ValueError):
                        audit_snapshot(output, raw)

    def test_bad_original_asset_leaves_incomplete_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root, parent, raw, _, stack = self.context(directory)
            with stack:
                output = parent.with_name("v2")
                bundle = self.bundle(raw, "SECOND")
                (raw/"asset.html").write_text("original", encoding="utf-8")
                bundle["origin"]["capture"]["source_asset"] = {"root": "raw", "file": "asset.html", "sha256": "0"*64}
                with self.assertRaisesRegex(ValueError, "original source asset differs"):
                    build_snapshot(parent, output, raw_root=raw, bundles=[bundle])
                state = json.loads((output/"snapshot_manifest.json").read_text(encoding="utf-8"))
                self.assertFalse(state["complete"])
                with self.assertRaisesRegex(ValueError, "incomplete"):
                    audit_snapshot(output, raw)

    def test_raw_asset_and_approved_root_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            root, parent, raw, _, stack = self.context(directory)
            with stack:
                bundle = self.bundle(raw, "SECOND")
                (raw/"asset.html").write_bytes(b"original")
                asset = {"root": "raw", "file": "asset.html", "sha256": hashlib.sha256(b"original").hexdigest()}
                bundle["origin"]["capture"]["source_asset"] = asset
                report = build_snapshot(parent, parent.with_name("v2"), raw_root=raw, bundles=[bundle])
                self.assertEqual(report["original_assets_sha256"]["raw:asset.html"], asset["sha256"])
                for mutation in ({"root": "anywhere"}, {"file": "../outside.html"}, {"file": str(raw/"asset.html")}):
                    with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                        original_asset_path({**asset, **mutation}, raw)

    def test_duplicate_and_unqualified_imports_fail_before_output_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            root, parent, raw, _, stack = self.context(directory)
            with stack:
                bundle = self.bundle(raw, "SECOND")
                for changes, message in (({"language": "en"}, "checked Chinese"),
                                         ({"source_collected_at": "2099-01-01"}, "future"),
                                         ({"next_review_at": "2026-02-01"}, "checked Chinese")):
                    bad = copy.deepcopy(bundle); bad["document"].update(changes)
                    with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, message):
                        build_snapshot(parent, parent.with_name("v2"), raw_root=raw, bundles=[bad], as_of=date(2026, 10, 27))
                    self.assertFalse(parent.with_name("v2").exists())
                with self.assertRaisesRegex(ValueError, "duplicate"):
                    build_snapshot(parent, parent.with_name("v2"), raw_root=raw, bundles=[bundle, bundle])

    def test_origin_updates_cannot_disappear_or_be_misdeclared(self):
        with tempfile.TemporaryDirectory() as directory:
            root, parent, raw, _, stack = self.context(directory)
            with stack:
                output = parent.with_name("v2")
                build_snapshot(parent, output, raw_root=raw, bundles=[self.bundle(raw, "SECOND")])
                target = output/"snapshot_manifest.json"
                state = json.loads(target.read_text(encoding="utf-8"))
                state["origin_updates"] = []
                target.write_text(json.dumps(state), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "origin update declaration"):
                    audit_snapshot(output, raw)


if __name__ == "__main__":
    unittest.main()
