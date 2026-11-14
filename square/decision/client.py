"""Client abstraction for the Gemini Decisions API (`gemini-decision-1`).

Uses Python's standard-library `urllib.request` against the `v1beta/decisions` endpoint
so Square retains zero mandatory third-party package dependencies, while also providing
a deterministic `ScriptedDecisionClient` for unit testing.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

DEFAULT_DECISION_MODEL = "gemini-decision-1"
DEFAULT_DECISION_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/decisions"
MAX_QUESTIONS_PER_CALL = 1_000


class DecisionAPIError(RuntimeError):
    """Raised when the Gemini Decisions API request fails or returns an invalid payload."""


@dataclass(frozen=True)
class NoulAnswer:
    """Calibrated boolean probability answer (`type == 'noul'`)."""

    probability: float
    confidence: float


@dataclass(frozen=True)
class ChoiceAnswer:
    """Calibrated multiple-choice answer (`type == 'choice'`)."""

    choice: str
    probabilities: dict[str, float]
    confidence: float


@dataclass
class DecisionResponse:
    """Normalized response from one `gemini-decision-1` evaluation batch."""

    model: str
    noul_answers: dict[str, NoulAnswer] = field(default_factory=dict)
    choice_answers: dict[str, ChoiceAnswer] = field(default_factory=dict)
    wall_ms: float = 0.0
    input_chars: int = 0
    question_count: int = 0
    raw_payload: dict[str, Any] = field(default_factory=dict)


class DecisionClient(Protocol):
    """Protocol for evaluating a batch of typed questions against a shared input."""

    def decide(
        self,
        input_text: str,
        questions: Mapping[str, Mapping[str, Any]],
        *,
        model: str = DEFAULT_DECISION_MODEL,
    ) -> DecisionResponse: ...


def resolve_gemini_api_key(explicit_key: str | None = None) -> str:
    """Resolve `GEMINI_API_KEY` or `GOOGLE_API_KEY` from argument, environment, or `.env` files."""
    if explicit_key and explicit_key.strip():
        return explicit_key.strip()
    for env_name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        val = os.environ.get(env_name, "").strip()
        if val:
            return val

    candidate_env_files = [
        Path.cwd() / ".env",
        Path.home() / ".square" / ".env",
        Path.home() / ".gemini" / ".env",
    ]
    for env_file in candidate_env_files:
        try:
            if not env_file.is_file():
                continue
            for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
                s = line.strip()
                if not s or s.startswith("#") or "=" not in s:
                    continue
                k, _, v = s.partition("=")
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k in ("GEMINI_API_KEY", "GOOGLE_API_KEY") and v:
                    return v
        except OSError:
            continue
    return ""


def parse_decision_payload(
    payload: Mapping[str, Any],
    *,
    model: str = DEFAULT_DECISION_MODEL,
    wall_ms: float = 0.0,
    input_chars: int = 0,
    question_count: int = 0,
) -> DecisionResponse:
    """Parse raw JSON from `/v1beta/decisions` into typed `NoulAnswer` and `ChoiceAnswer` maps."""
    answers = payload.get("answers")
    if not isinstance(answers, Mapping):
        raise DecisionAPIError(
            f"Malformed Decisions API response: missing 'answers' map in {list(payload.keys())}"
        )

    noul_map: dict[str, NoulAnswer] = {}
    choice_map: dict[str, ChoiceAnswer] = {}

    for q_id, ans in answers.items():
        if not isinstance(ans, Mapping):
            continue
        q_type = str(ans.get("type") or "")
        conf = float(ans.get("confidence") or 0.0)
        if q_type == "noul" or "noul" in ans:
            prob = float(ans.get("noul") or 0.0)
            noul_map[str(q_id)] = NoulAnswer(probability=prob, confidence=conf)
        elif q_type == "choice" or "choice" in ans:
            selected = str(ans.get("choice") or "")
            raw_probs = ans.get("probabilities")
            probs: dict[str, float] = {}
            if isinstance(raw_probs, Mapping):
                probs = {str(k): float(v) for k, v in raw_probs.items()}
            choice_map[str(q_id)] = ChoiceAnswer(
                choice=selected,
                probabilities=probs,
                confidence=conf,
            )

    return DecisionResponse(
        model=model,
        noul_answers=noul_map,
        choice_answers=choice_map,
        wall_ms=round(wall_ms, 1),
        input_chars=input_chars,
        question_count=question_count,
        raw_payload=dict(payload),
    )


@dataclass
class GeminiDecisionClient:
    """Zero-dependency REST client for Google's `v1beta/decisions` API (`gemini-decision-1`)."""

    api_key: str | None = None
    endpoint: str = DEFAULT_DECISION_ENDPOINT
    timeout_s: int = 60

    def decide(
        self,
        input_text: str,
        questions: Mapping[str, Mapping[str, Any]],
        *,
        model: str = DEFAULT_DECISION_MODEL,
    ) -> DecisionResponse:
        if not questions:
            raise ValueError("questions map must not be empty")
        if len(questions) > MAX_QUESTIONS_PER_CALL:
            raise ValueError(
                f"Decisions API supports at most {MAX_QUESTIONS_PER_CALL} questions per call; "
                f"got {len(questions)}"
            )

        key = resolve_gemini_api_key(self.api_key)
        if not key:
            raise DecisionAPIError(
                "No Gemini API key found. Set GEMINI_API_KEY (or GOOGLE_API_KEY) in your "
                "environment or in ~/.square/.env before running `square triage`."
            )

        body = json.dumps(
            {
                "model": model,
                "input": input_text,
                "questions": dict(questions),
            }
        ).encode("utf-8")

        req = urllib.request.Request(
            self.endpoint,
            data=body,
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": key,
            },
            method="POST",
        )

        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                raw_bytes = resp.read()
        except urllib.error.HTTPError as exc:
            err_body = ""
            try:
                err_body = exc.read().decode("utf-8", errors="replace")[:500]
            except Exception:
                pass
            raise DecisionAPIError(
                f"Decisions API HTTP {exc.code}: {err_body or exc.reason}"
            ) from exc
        except urllib.error.URLError as exc:
            raise DecisionAPIError(f"Decisions API network error: {exc.reason}") from exc

        wall_ms = (time.perf_counter() - t0) * 1000.0
        try:
            payload = json.loads(raw_bytes.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as exc:
            raise DecisionAPIError(f"Invalid JSON from Decisions API: {exc}") from exc

        return parse_decision_payload(
            payload,
            model=model,
            wall_ms=wall_ms,
            input_chars=len(input_text),
            question_count=len(questions),
        )


@dataclass
class ScriptedDecisionClient:
    """Deterministic in-memory `DecisionClient` for unit tests."""

    responder: Callable[[str, Mapping[str, Mapping[str, Any]]], Mapping[str, Any]]
    calls: list[tuple[str, dict[str, dict[str, Any]]]] = field(default_factory=list)

    def decide(
        self,
        input_text: str,
        questions: Mapping[str, Mapping[str, Any]],
        *,
        model: str = DEFAULT_DECISION_MODEL,
    ) -> DecisionResponse:
        q_copy = {str(k): dict(v) for k, v in questions.items()}
        self.calls.append((input_text, q_copy))
        raw = self.responder(input_text, q_copy)
        return parse_decision_payload(
            raw,
            model=model,
            wall_ms=1.0,
            input_chars=len(input_text),
            question_count=len(q_copy),
        )
