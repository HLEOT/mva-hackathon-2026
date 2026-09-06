"""Codex-directed review checkpoints; no inference server or network client.

Workers prepare bounded evidence only after the account's data-use terms have
been confirmed. The active Codex session supplies a structured review. Exact
request hashes prevent old model answers from being relabelled as Codex work.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime

import jsonschema

from mva_track1.common import PROJECT_ROOT, Track1Error, atomic_write_json, ensure_private_dir, load_jsonish, sha256_file, utc_now


class InterpretationError(Track1Error):
    """A review failed its structural or scientific evidence gate."""


class ReviewRequired(Track1Error):
    """Codex review or confirmed data-use terms are needed before resuming."""


def terms_confirmed() -> bool:
    """Never infer provider terms, settings, or permission from a login."""
    path = PROJECT_ROOT / "config/ai_usage.local.yaml"
    data = load_jsonish(path) if path.is_file() else {}
    return (data.get("private_codex_review_authorized") is True
            and data.get("provider_terms_confirmed") is True
            and all(isinstance(data.get(key), str) and data[key].strip()
                    for key in ("hosted_plan", "hosted_data_setting")))


def _digest(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _directory(purpose: str):
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,79}", purpose):
        raise Track1Error("Invalid review purpose")
    return PROJECT_ROOT / "work/private/reviews" / purpose


def _validate_response(response: dict, request: dict, key: str) -> dict:
    if (response.get("request_sha256") != key or response.get("reviewed_by") != "Codex"
            or response.get("review_mode") != "codex_assisted"):
        raise InterpretationError("Response lacks exact request binding or Codex attribution")
    try:
        reviewed_at = datetime.fromisoformat(response["reviewed_at"])
        if reviewed_at.tzinfo is None:
            raise ValueError("timezone required")
        answer = response["answer"]
        jsonschema.validate(answer, request["schema"])
    except (KeyError, TypeError, ValueError, jsonschema.ValidationError) as exc:
        raise InterpretationError("Codex response failed schema or timestamp validation") from exc
    return answer


def review_evidence(system: str, user: str, schema: dict, purpose: str) -> dict:
    """Stop without polling or transmitting evidence; resume with a real review."""
    if not terms_confirmed():
        raise ReviewRequired("Private Codex review awaits confirmed provider terms; no evidence exported")
    request = {"schema_version": 1, "reviewer": "Codex", "purpose": purpose,
               "instructions": system, "evidence": json.loads(user), "schema": schema}
    key = _digest(request)
    directory = ensure_private_dir(_directory(purpose))
    request_path = directory / f"{key}.request.json"
    response_path = directory / f"{key}.response.json"
    if not request_path.exists():
        atomic_write_json(request_path, request)
    elif load_jsonish(request_path) != request:
        raise InterpretationError("Stored review request changed")
    if not response_path.exists():
        atomic_write_json(directory / "pending.json", {"request_sha256": key, "purpose": purpose,
            "status": "awaiting_codex_review", "created_at": utc_now()})
        raise ReviewRequired("Codex review required; inspect ./mva reviews then resume after review")
    answer = _validate_response(load_jsonish(response_path), request, key)
    atomic_write_json(directory / "accepted.json", {"purpose": purpose, "request_sha256": key,
        "response_sha256": sha256_file(response_path), "review_mode": "codex_assisted"})
    pending = directory / "pending.json"
    if pending.exists():
        pending.unlink()  # Remove only the queue pointer, never review evidence.
    return answer


def review_receipt(purpose: str) -> dict:
    receipt = load_jsonish(_directory(purpose) / "accepted.json")
    verify_receipt(receipt)
    return receipt


def verify_receipt(receipt: dict) -> None:
    """Packaging checks actual evidence/answer bytes, not just a reviewer label."""
    if receipt.get("review_mode") != "codex_assisted":
        raise InterpretationError("Current result has no Codex review receipt")
    key = receipt.get("request_sha256", "")
    if not re.fullmatch(r"[0-9a-f]{64}", key):
        raise InterpretationError("Invalid review digest")
    directory = _directory(receipt.get("purpose", ""))
    request = load_jsonish(directory / f"{key}.request.json")
    response = directory / f"{key}.response.json"
    if (request.get("purpose") != receipt["purpose"] or request.get("reviewer") != "Codex"
            or _digest(request) != key or sha256_file(response) != receipt.get("response_sha256")):
        raise InterpretationError("Reviewed evidence or response has changed")
    _validate_response(load_jsonish(response), request, key)


def pending_reviews() -> list[dict]:
    """Queue IDs only: status checks must not expose patient evidence."""
    result = []
    for path in sorted((PROJECT_ROOT / "work/private/reviews").glob("*/pending.json")):
        record = load_jsonish(path)
        purpose, key = record.get("purpose", ""), record.get("request_sha256", "")
        if path.parent != _directory(purpose) or not re.fullmatch(r"[0-9a-f]{64}", key):
            raise Track1Error("Invalid pending review pointer")
        result.append({"purpose": purpose, "request_sha256": key, "status": "awaiting_codex_review",
                       "directory": str(path.parent.relative_to(PROJECT_ROOT))})
    return result
