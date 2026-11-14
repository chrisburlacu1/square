"""Versioned, append-only candidate and trial records owned by Square."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

from .lease import file_lock


def fingerprint(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class EvidenceStore:
    def __init__(self, root: Path):
        self.root = Path(root) / "evidence"

    def put(self, kind: str, value: dict) -> str:
        if kind not in {"candidates", "trials", "decisions", "sources"}:
            raise ValueError("Unknown evidence kind")
        key = fingerprint(value)
        directory = self.root / kind
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{key}.json"
        with file_lock(self.root / "write.lock"):
            if not path.exists():
                fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as out:
                        json.dump(value, out, indent=2, ensure_ascii=False)
                        out.flush()
                        os.fsync(out.fileno())
                    os.replace(tmp, path)
                finally:
                    Path(tmp).unlink(missing_ok=True)
        return key

    def get(self, kind: str, key: str) -> dict:
        if kind not in {"candidates", "trials", "decisions", "sources"} or len(key) != 64 or any(c not in "0123456789abcdef" for c in key):
            raise ValueError("Invalid evidence reference")
        value = json.loads((self.root / kind / f"{key}.json").read_text(encoding="utf-8"))
        if fingerprint(value) != key:
            raise ValueError("Evidence contents changed")
        return value

    def candidate(self, tree: dict[str, str], *, case_id: str, notes: str, parent: str = "") -> str:
        if parent:
            self.get("candidates", parent)
        return self.put("candidates", {"schema_version": 1, "tree": tree,
            "case_id": case_id, "notes": notes, "parent": parent})

    def trial(self, candidate: str, *, input_id: str, completed: bool,
              correct: bool | None, helped: bool | None, regression: bool | None,
              details: str, runner: str) -> str:
        self.get("candidates", candidate)
        if not input_id.strip() or not details.strip() or not runner.strip():
            raise ValueError("Trial needs input identity, details, and runner")
        if type(completed) is not bool or any(x is not None and type(x) is not bool for x in (correct, helped, regression)):
            raise ValueError("Trial results must be booleans or unknown")
        return self.put("trials", {"schema_version": 1, "candidate": candidate,
            "input_id": input_id, "completed": completed, "correct": correct,
            "helped": helped, "regression": regression, "details": details, "runner": runner})

    def assess(self, candidate: str, trials: list[str]) -> dict:
        self.get("candidates", candidate)
        records = [self.get("trials", key) for key in sorted(set(trials))]
        if any(r["candidate"] != candidate for r in records):
            raise ValueError("Trial belongs to a different candidate version")
        if any(r["completed"] and (r["correct"] is False or r["regression"] is True) for r in records):
            status = "rejected"
        elif records and all(r["completed"] and r["correct"] is True and r["helped"] is True and r["regression"] is False for r in records) and len({r["input_id"] for r in records}) >= 2:
            status = "supported_in_recorded_trials"
        else:
            status = "needs_more_evidence"
        decision = {"schema_version": 1, "policy_version": 1, "candidate": candidate,
                    "trials": sorted(set(trials)), "status": status}
        decision["id"] = self.put("decisions", decision)
        return decision
