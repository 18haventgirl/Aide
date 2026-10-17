"""Resumable, serial REAL model comparison in fresh isolated processes.

No serving index or .env is modified. Each failed attempt is immutable; resume
creates a new output. This can be stopped between configurations safely.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

from .experiment import MEDICAL, digest, load_suite, repository_version
from .knowledge_base import load_corpus


CONFIGURATIONS = {
    "legacy-256": {"rerank_max_length": 256, "input_policy": "legacy", "chunk_strategy": "legacy"},
    "bridge-512": {"rerank_max_length": 512, "input_policy": "legacy", "chunk_strategy": "legacy"},
    "child180-pair256": {"rerank_max_length": 256, "input_policy": "query_first_v1", "chunk_strategy": "token-v1", "child_tokens": 180},
    "child220-pair384": {"rerank_max_length": 384, "input_policy": "query_first_v1", "chunk_strategy": "token-v1", "child_tokens": 220},
}


def run(directory, configurations=None, resume=False):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    # OS advisory locks are released after a crash. Keep the lock file, so a
    # second resume cannot unlink/recreate it while the first job owns it.
    with (directory/"matrix.lock").open("a+b") as lock:
        lock.seek(0, 2)
        if not lock.tell():
            lock.write(b"0"); lock.flush()
        lock.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError("another process owns this experiment matrix") from exc
        try:
            return _run(directory, configurations, resume)
        finally:
            lock.seek(0)
            if os.name == "nt": msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else: fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _run(directory, configurations=None, resume=False):
    path = directory/"matrix.json"
    code = repository_version()
    if code.get("tracked_changes") is not False:
        raise ValueError("commit tracked implementation changes before starting/resuming the real comparison")
    suite_path = MEDICAL/"evaluation/suite_v5.json"
    suite, _ = load_suite(suite_path)
    signature = {"code": code, "suite_sha256": digest(suite),
                 "corpus_sha256": digest([d.model_dump(mode="json") for d in load_corpus(MEDICAL/"source_corpus")]),
                 "configurations": CONFIGURATIONS, "profiles": ["hybrid", "rerank"],
                 "metric_contract": "evidence-v1", "k": 5}
    if resume:
        report = json.loads(path.read_text(encoding="utf-8"))
        if report["signature"] != signature:
            raise ValueError("code/data/config changed; start a new matrix directory")
    else:
        report = {"scope": "exposed_development_and_regression_not_blind_not_clinical", "signature": signature,
                  "started_at_utc": datetime.now(timezone.utc).isoformat(), "complete": False,
                  "performance_scope": "fixed_order_descriptive_not_randomized_performance_acceptance",
                  "attempts": {name: [] for name in CONFIGURATIONS}}
        with path.open("x", encoding="utf-8") as handle: json.dump(report, handle)

    def save():
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
        temporary.replace(path)
    chosen = configurations or list(CONFIGURATIONS)
    if not chosen or set(chosen)-set(CONFIGURATIONS) or len(set(chosen)) != len(chosen):
        raise ValueError("invalid or repeated matrix selection")
    for name in chosen:
        if report["attempts"][name] and report["attempts"][name][-1]["complete"]:
            continue
        attempt = len(report["attempts"][name])+1
        output = directory/f"{name}_attempt{attempt:02d}.json"
        args = [sys.executable, "-m", "medical.experiment", "--suite", str(suite_path),
                "--output", str(output), "--profiles", "hybrid", "rerank"]
        for key, value in CONFIGURATIONS[name].items():
            args.extend(["--"+key.replace("_", "-"), str(value)])
        row = {"output": output.name, "complete": False, "state": "running"}
        report["attempts"][name].append(row)
        report["stage"] = name
        save()
        # Child inherits the caller's UTF8/offline environment. stdout contains
        # only public evaluation IDs/aggregate metrics, no user data or keys.
        result = subprocess.run(args, cwd=MEDICAL.parent,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        raw = json.loads(output.read_text(encoding="utf-8")) if output.is_file() else {}
        row.update(complete=bool(raw.get("complete")) and result.returncode == 0,
                   exit_code=result.returncode, failure_type=raw.get("failure_type"))
        row["state"] = "finished" if row["complete"] else ("awaiting_memory" if row["failure_type"] == "MemoryBudgetError" else "failed")
        save()
        if not row["complete"]:
            return report
    report["complete"] = all(rows and rows[-1]["complete"] for rows in report["attempts"].values())
    report["stage"] = "finished" if report["complete"] else "selected_configurations_finished"
    save()
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--configuration", action="append", choices=CONFIGURATIONS)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    result = run(args.directory, args.configuration, args.resume)
    print(json.dumps({"complete": result["complete"], "stage": result["stage"]}))
