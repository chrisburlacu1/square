"""Improver sessions with file access in an isolated context workspace.

Adapted from `reference/harness2/harness2/core/proposer.py`.
Supports `agy_cli` (`agy`), `claude_cli` (`claude`), `codex_cli` (`codex`), `opencode` (`opencode`),
and scripted/custom proposers without requiring Vertex AI environment variables when running locally.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

SYSTEM_ARG_MAX = 120_000
CHANNELS = ("agy_cli", "claude_cli", "codex_cli", "opencode", "scripted")

_SEM = threading.BoundedSemaphore(4)


@dataclass(frozen=True)
class ChannelSpec:
    """How to reach one model on a local CLI proposer channel.

    `steps` is the maximum agentic tool-step budget written to `opencode.json`
    (`{"agent":{"build":{"steps": steps}}}`) when `kind == "opencode"`.
    """

    kind: str = "codex_cli"
    model: str = "gpt-6-luna"
    effort: str = "medium"
    steps: int = 120
    timeout: int = 1800

    def __post_init__(self) -> None:
        if self.kind not in CHANNELS:
            raise ValueError(f"unknown channel {self.kind!r}; expected one of {CHANNELS}")


class ProposerError(RuntimeError):
    """A call did not produce a usable reply. Never swallowed into an empty string."""

    def __init__(self, message: str, *, attempts: int = 0, cost_usd: float = 0.0):
        super().__init__(message)
        self.attempts = attempts
        self.cost_usd = cost_usd


@dataclass
class Reply:
    """One session: what came back, what it cost, and where the audit trail is."""

    label: str
    text: str
    ok: bool
    cost_usd: float = 0.0
    wall_s: float = 0.0
    attempts: int = 0
    cached: bool = False
    channel: str = ""
    error: str = ""
    audit: Path | None = None
    workspace: Path | None = None
    telemetry: dict = field(default_factory=dict)

    def __bool__(self) -> bool:
        return self.ok


@dataclass
class Proposer:
    """Runs agentic sessions on one channel, with an audit trail and content-addressed cache."""

    spec: ChannelSpec = field(default_factory=ChannelSpec)
    audit_dir: Path | None = None
    attempts: int = 2
    _calls: list[Reply] = field(default_factory=list)

    def env(self) -> dict[str, str]:
        e = dict(os.environ)
        if self.spec.kind == "claude_cli" and self.spec.model:
            e["ANTHROPIC_MODEL"] = self.spec.model
        return e

    def call(
        self,
        mission: str,
        context_dir: Path | str | None,
        label: str,
        *,
        system: str = "",
        timeout: int | None = None,
        max_attempts: int | None = None,
        harvest: str | None = None,
    ) -> Reply:
        """Run one session. Raises ProposerError if no usable reply after `attempts`.

        `harvest` names a subpath of the session's working directory to copy out before that
        directory is destroyed -- e.g. "context/harness", which is how an edited tree comes back.
        """
        cache_key = _call_fingerprint(label, mission, system + "\n" + repr(self.spec), context_dir)
        cached = self._cached(label, cache_key, require_workspace=bool(harvest))
        if cached is not None:
            self._calls.append(cached)
            return cached

        wall = int(timeout or self.spec.timeout)
        tries = max(1, int(self.attempts if max_attempts is None else max_attempts))
        last = ""
        spent_usd = 0.0
        t0 = time.time()
        print(
            f"[square] Running proposer stage `{label}` via `{self.spec.kind}` "
            f"(model={self.spec.model or 'default'})...",
            file=sys.stderr,
            flush=True,
        )
        for attempt in range(1, tries + 1):
            if attempt > 1:
                time.sleep(2 * (attempt - 1))
            tmp = Path(tempfile.mkdtemp(prefix="square-prop-"))
            try:
                if context_dir and Path(context_dir).is_dir():
                    shutil.copytree(context_dir, tmp / "context", dirs_exist_ok=True)
                with _SEM:
                    telemetry: dict = {}
                    if self.spec.kind == "agy_cli":
                        text, cost, err, telemetry = self._agy_cli(tmp, mission, system, wall)
                    elif self.spec.kind == "claude_cli":
                        text, cost, err = self._claude_cli(tmp, mission, system, wall)
                    elif self.spec.kind == "codex_cli":
                        text, cost, err, telemetry = self._codex_cli(tmp, mission, system, wall)
                    else:
                        text, cost, err = self._opencode(tmp, mission, system, wall)
                spent_usd += cost
                if not text.strip():
                    last = err or "empty reply"
                    continue
                r = Reply(
                    label=label,
                    text=text,
                    ok=True,
                    cost_usd=spent_usd,
                    wall_s=round(time.time() - t0, 1),
                    attempts=attempt,
                    channel=self.spec.kind,
                    telemetry=telemetry,
                )
                if harvest:
                    r.workspace = self._harvest(tmp, harvest, label, cache_key)
                self._write_audit(r, mission, system, cache_key)
                self._calls.append(r)
                print(
                    f"[square] Completed `{label}` in {r.wall_s}s (attempt {attempt}/{tries}).",
                    file=sys.stderr,
                    flush=True,
                )
                return r
            except subprocess.TimeoutExpired:
                last = f"timeout after {wall}s"
            except Exception as exc:
                last = f"{type(exc).__name__}: {exc}"
            finally:
                shutil.rmtree(tmp, ignore_errors=True)

        r = Reply(
            label=label,
            text="",
            ok=False,
            wall_s=round(time.time() - t0, 1),
            attempts=tries,
            channel=self.spec.kind,
            error=last,
            cost_usd=spent_usd,
        )
        self._calls.append(r)
        self._write_audit(r, mission, system, cache_key)
        model_tag = f"/{self.spec.model}" if self.spec.model else ""
        msg = f"[{label}] {self.spec.kind}{model_tag}: {last}"
        print(f"[square] Proposer error: {msg}", file=sys.stderr)
        raise ProposerError(
            msg,
            attempts=tries,
            cost_usd=spent_usd,
        )

    def _claude_cli(
        self, cwd: Path, mission: str, system: str, wall: int
    ) -> tuple[str, float, str]:
        cli = shutil.which("claude") or "claude"
        cmd = [
            cli,
            "--dangerously-skip-permissions",
            "-p",
            "--output-format",
            "json",
        ]
        if self.spec.effort:
            cmd += ["--effort", self.spec.effort]
        stdin = mission
        if system:
            if len(system) > SYSTEM_ARG_MAX:
                stdin = f"# SYSTEM INSTRUCTIONS\n\n{system}\n\n# END\n\n{mission}"
                cmd += [
                    "--append-system-prompt",
                    "Follow the SYSTEM INSTRUCTIONS block at the top of the message.",
                ]
            else:
                cmd += ["--append-system-prompt", system]
        p = subprocess.run(
            cmd,
            input=stdin,
            cwd=cwd,
            env=self.env(),
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=wall,
        )
        payload = _parse_json(p.stdout)
        text = str(payload.get("result") or payload.get("text") or "")
        err = ""
        if payload.get("is_error") or payload.get("subtype") not in (None, "success"):
            err = f"CLI error: {payload.get('subtype')} {str(text)[:200]}"
            text = ""
        elif p.returncode != 0 and not text.strip():
            err = f"rc={p.returncode}: {(p.stderr or '')[-300:]}"
        return text, float(payload.get("total_cost_usd") or 0.0), err

    def _codex_cli(
        self, cwd: Path, mission: str, system: str, wall: int
    ) -> tuple[str, float, str, dict]:
        cli = shutil.which("codex") or "codex"
        full_prompt = f"# SYSTEM INSTRUCTIONS\n\n{system}\n\n# END\n\n{mission}" if system else mission
        (cwd / "MISSION.md").write_text(full_prompt, encoding="utf-8")
        out = cwd / "output"
        out.mkdir(exist_ok=True)
        ans = out / "answer.md"
        short_prompt = (
            "Read MISSION.md in the current directory first (which already inlines the key "
            "evidence and harness overview so you do not need to read every file one by one). "
            "Edit only the target files in `context/harness/` in place as needed, and write your "
            "final `<notes>` and `<trigger>` reply to `output/answer.md` AND as your final message."
        )
        cmd = [
            cli,
            "exec",
            short_prompt,
            "--ignore-user-config",
            "--ignore-rules",
            "--skip-git-repo-check",
            "--dangerously-bypass-approvals-and-sandbox",
            "--ephemeral",
            "--json",
            "-o",
            str(ans),
            "-C",
            str(cwd),
        ]
        if self.spec.model:
            cmd += ["-m", self.spec.model]
        if self.spec.effort:
            cmd += ["-c", f'model_reasoning_effort="{self.spec.effort}"']
        p = subprocess.run(
            cmd,
            input="",
            cwd=cwd,
            env=self.env(),
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=wall,
        )
        telemetry, last_msg = _extract_codex_jsonl_telemetry(p.stdout, p.stderr)
        if ans.is_file() and ans.read_text(encoding="utf-8", errors="replace").strip():
            return ans.read_text(encoding="utf-8", errors="replace"), 0.0, "", telemetry
        text = last_msg.strip() or (p.stdout or "").strip()
        err = "" if (p.returncode == 0 or text) else f"rc={p.returncode}: {(p.stderr or '')[-300:]}"
        return text, 0.0, err, telemetry

    def _opencode(self, cwd: Path, mission: str, system: str, wall: int) -> tuple[str, float, str]:
        (cwd / "MISSION.md").write_text(
            (f"{system}\n\n---\n\n" if system else "") + mission, encoding="utf-8"
        )
        (cwd / "opencode.json").write_text(
            json.dumps({"agent": {"build": {"steps": self.spec.steps}}}), encoding="utf-8"
        )
        out = cwd / "output"
        out.mkdir(exist_ok=True)
        prompt = (
            "Read MISSION.md first. Do what it asks. Reply with the requested output as "
            "your final message AND save it verbatim to output/answer.md."
        )
        cli = shutil.which("opencode") or "opencode"
        cmd = [
            cli,
            "run",
            prompt,
            "--dir",
            str(cwd),
            "--model",
            self.spec.model,
            "--format",
            "json",
        ]
        p = subprocess.run(
            cmd,
            cwd=cwd,
            env=self.env(),
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=wall,
        )
        ans = out / "answer.md"
        if ans.is_file() and ans.read_text(errors="replace").strip():
            return ans.read_text(errors="replace"), 0.0, ""
        text = (p.stdout or "").strip()
        return text, 0.0, ("" if text else f"rc={p.returncode}: {(p.stderr or '')[-300:]}")

    def _agy_cli(
        self, cwd: Path, mission: str, system: str, wall: int
    ) -> tuple[str, float, str, dict]:
        cli = shutil.which("agy") or "agy"
        full_prompt = f"# SYSTEM INSTRUCTIONS\n\n{system}\n\n# END\n\n{mission}" if system else mission
        (cwd / "MISSION.md").write_text(full_prompt, encoding="utf-8")
        out = cwd / "output"
        out.mkdir(exist_ok=True)
        short_prompt = (
            "Read MISSION.md in the current directory first (which already inlines the key "
            "evidence and harness overview so you do not need to read every file one by one). "
            "Edit only the target files in `context/harness/` in place as needed, and write your "
            "final `<notes>` and `<trigger>` reply to `output/answer.md` AND as your final message."
        )
        cmd = [
            cli,
            "--dangerously-skip-permissions",
            "--output-format",
            "json",
        ]
        if self.spec.model:
            cmd += ["--model", self.spec.model]
        cmd += ["-p", short_prompt]
        p = subprocess.run(
            cmd,
            input="",
            cwd=cwd,
            env=self.env(),
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=wall,
        )
        payload = _parse_json(p.stdout)
        cost = float(payload.get("total_cost_usd") or payload.get("cost_usd") or 0.0)
        telemetry = _extract_cli_telemetry(payload, p.stdout, p.stderr)
        ans = out / "answer.md"
        if ans.is_file() and ans.read_text(encoding="utf-8", errors="replace").strip():
            return ans.read_text(encoding="utf-8", errors="replace"), cost, "", telemetry
        text = str(
            payload.get("result")
            or payload.get("response")
            or payload.get("text")
            or payload.get("content")
            or ""
        )
        err = ""
        if payload.get("is_error") or payload.get("error") or payload.get("subtype") not in (None, "success"):
            err = f"CLI error: {payload.get('error') or payload.get('subtype')} {str(text)[:200]}"
            text = ""
        elif p.returncode != 0 and not text.strip():
            err = f"rc={p.returncode}: {(p.stderr or '')[-300:]}"
        return text, cost, err, telemetry

    def _harvest(self, tmp: Path, sub: str, label: str, cache_key: str = "") -> Path | None:
        """Copy `tmp/<sub>` into an ephemeral temp workspace for tree reading before session cleanup."""
        del label, cache_key
        src = tmp / sub
        if not src.is_dir():
            return None
        dest = Path(tempfile.mkdtemp(prefix="square-harvest-"))
        shutil.copytree(src, dest, dirs_exist_ok=True)
        return dest

    def _paths(self, label: str, cache_key: str = "") -> dict[str, Path] | None:
        if not self.audit_dir:
            return None
        d = Path(self.audit_dir)
        d.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", label)
        if cache_key:
            safe = f"{safe}.{cache_key}"
        return {
            "meta": d / f"{safe}.meta.json",
        }

    def _cached(
        self, label: str, cache_key: str = "", *, require_workspace: bool = False
    ) -> Reply | None:
        p = self._paths(label, cache_key)
        if not p or not p["meta"].is_file():
            return None
        try:
            meta = json.loads(p["meta"].read_text(encoding="utf-8", errors="replace"))
        except Exception:
            return None
        if not isinstance(meta, dict) or not meta.get("ok"):
            return None
        txt = str(meta.get("response") or "")
        if not txt.strip():
            return None
        ws: Path | None = None
        harvested_files = meta.get("harvested_files")
        if require_workspace:
            if not isinstance(harvested_files, dict) or not harvested_files:
                return None
            ws = Path(tempfile.mkdtemp(prefix="square-harvest-"))
            for rel, content in harvested_files.items():
                dest_file = ws / rel
                dest_file.parent.mkdir(parents=True, exist_ok=True)
                dest_file.write_text(str(content), encoding="utf-8")
        return Reply(
            label=label,
            text=txt,
            ok=True,
            cost_usd=0.0,
            cached=True,
            channel=self.spec.kind,
            audit=p["meta"],
            workspace=ws,
            telemetry=meta.get("telemetry") if isinstance(meta.get("telemetry"), dict) else {},
        )

    def _write_audit(self, r: Reply, mission: str, system: str, cache_key: str = "") -> None:
        p = self._paths(r.label, cache_key)
        if not p:
            return
        meta_dict: dict = {
            "mission": mission,
            "system": system,
            "label": r.label,
            "ok": r.ok,
            "channel": r.channel,
            "model": self.spec.model,
            "effort": self.spec.effort,
            "attempts": r.attempts,
            "wall_s": r.wall_s,
            "cost_usd": r.cost_usd,
            "error": r.error,
            "response": r.text,
        }
        if r.workspace and r.workspace.is_dir():
            harvested: dict[str, str] = {}
            for fp in sorted(r.workspace.rglob("*")):
                if fp.is_file() and "__pycache__" not in fp.parts:
                    rel = fp.relative_to(r.workspace).as_posix()
                    with contextlib.suppress(OSError):
                        harvested[rel] = fp.read_text(encoding="utf-8", errors="replace")
            if harvested:
                meta_dict["harvested_files"] = harvested
        if r.telemetry:
            meta_dict["telemetry"] = r.telemetry
        p["meta"].write_text(
            json.dumps(meta_dict, indent=2),
            encoding="utf-8",
        )
        r.audit = p["meta"]


def _extract_codex_jsonl_telemetry(stdout: str, stderr: str) -> tuple[dict, str]:
    """Parse `codex exec --json` JSONL events into structured telemetry (tokens, tool calls, turns)
    and extract the final assistant message if present.
    """
    tel: dict = {
        "thread_id": "",
        "num_turns": 0,
        "tool_calls_count": 0,
        "tool_calls": [],
        "usage": {},
    }
    last_msg = ""
    for line in (stdout or "").splitlines():
        s = line.strip()
        if not s.startswith("{"):
            continue
        try:
            ev = json.loads(s)
        except json.JSONDecodeError:
            continue
        if not isinstance(ev, dict):
            continue
        etype = str(ev.get("type") or "")
        if etype == "thread.started" and ev.get("thread_id"):
            tel["thread_id"] = ev["thread_id"]
        elif etype == "turn.completed":
            tel["num_turns"] = int(tel.get("num_turns", 0)) + 1
            if isinstance(ev.get("usage"), dict):
                tel["usage"] = ev["usage"]
        elif etype in ("item.completed", "item.started"):
            item = ev.get("item")
            if isinstance(item, dict):
                itype = str(item.get("type") or "")
                if itype in ("agent_message", "assistant_message", "message") and item.get("text"):
                    last_msg = str(item["text"])
                elif itype in ("command_execution", "tool_call", "function_call", "file_change", "mcp_tool_call") and etype == "item.completed":
                    cmd_str = str(
                        item.get("command")
                        or item.get("name")
                        or item.get("changes")
                        or itype
                    )[:200]
                    tel["tool_calls"].append({"type": itype, "detail": cmd_str})
                    tel["tool_calls_count"] = len(tel["tool_calls"])
    if (stderr or "").strip():
        tel["stderr_tail"] = stderr.strip()[-500:]
    return tel, last_msg


def _extract_cli_telemetry(payload: dict, stdout: str, stderr: str) -> dict:
    """Extract non-text telemetry fields (turns, tool calls, token usage, cost, duration) from CLI JSON output."""
    tel: dict = {}
    for k, v in payload.items():
        if k in ("result", "response", "text", "content"):
            continue
        tel[k] = v
    if not tel and (stdout or "").strip():
        tel["stdout_chars"] = len(stdout)
    if (stderr or "").strip():
        tel["stderr_tail"] = stderr.strip()[-500:]
    return tel


def _drop_workspace(paths: dict[str, Path] | None) -> None:
    if paths:
        shutil.rmtree(paths["workspace"], ignore_errors=True)


def _parse_json(stdout: str) -> dict:
    s = (stdout or "").strip()
    if not s:
        return {}
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        for line in reversed(s.splitlines()):
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue
        i, j = s.find("{"), s.rfind("}")
        if 0 <= i < j:
            try:
                return json.loads(s[i : j + 1])
            except json.JSONDecodeError:
                pass
    return {"result": s}


def _call_fingerprint(label: str, mission: str, system: str, context_dir: Path | str | None) -> str:
    """Content-address one call, including its evidence and workspace path."""
    h = hashlib.sha256()
    for value in (label, mission, system):
        h.update(value.encode("utf-8", errors="replace"))
        h.update(b"\0")
    if context_dir:
        root = Path(context_dir)
        if root.is_dir():
            for p in sorted(root.rglob("*")):
                if not p.is_file() or "__pycache__" in p.parts:
                    continue
                h.update(str(p.relative_to(root)).encode("utf-8", errors="replace"))
                h.update(b"\0")
                try:
                    with p.open("rb") as fh:
                        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                            h.update(chunk)
                except OSError as exc:
                    h.update(f"<unreadable:{type(exc).__name__}:{exc}>".encode())
                h.update(b"\0")
    return h.hexdigest()[:16]
