"""Versioned public-only HTTP responses with per-request provenance.

The optional installed database skills supply their canonical-source metadata.
A portable HTTP implementation uses the same documented read-only endpoints
when those skills are not installed. Neither route reads private input files.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

import requests

from mva_track1.common import PROJECT_ROOT, Track1Error, atomic_write_json, load_jsonish, sha256_file, utc_now

ROOT = PROJECT_ROOT / "resources/public/evidence"
BASES = {"chembl": "https://www.ebi.ac.uk/chembl/api/data", "reactome": "https://reactome.org/ContentService",
         "entrez": "https://eutils.ncbi.nlm.nih.gov/entrez/eutils", "fda": "https://api.fda.gov"}
SKILLS = {"chembl": "chembl-skill", "reactome": "reactome-skill", "entrez": "ncbi-entrez-skill"}


def _skill_script(source: str) -> Path | None:
    if source not in SKILLS:
        return None
    configured = os.environ.get("MVA_DATABASE_SKILLS")
    roots = [Path(configured)] if configured else sorted(
        (Path.home() / ".codex/plugins/cache/openai-curated-remote/life-sciences-databases").glob("*/skills"), reverse=True)
    name = "ncbi_entrez.py" if source == "entrez" else "rest_request.py"
    return next((root / SKILLS[source] / "scripts" / name for root in roots
                 if (root / SKILLS[source] / "scripts" / name).is_file()), None)


def fetch(source: str, path: str, params: dict | None = None, *, xml: bool = False) -> dict:
    """Return a receipt for one bounded public request, including empty/failure.

    Only named HTTPS database hosts are accepted. Callers construct queries
    exclusively from public config and IDs returned by public databases.
    """
    if source not in BASES or path.startswith(("/", "http")) or ".." in path:
        raise Track1Error("Unapproved public evidence endpoint")
    params = params or {}
    identity = {"source": source, "path": path, "params": params, "xml": xml}
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    directory = ROOT / "responses"
    directory.mkdir(parents=True, exist_ok=True)
    receipt_path = directory / f"{key}.json"
    raw = directory / f"{key}.{'xml' if xml else 'raw.json'}"
    if receipt_path.exists():
        receipt = load_jsonish(receipt_path)
        if receipt.get("ok") and raw.is_file() and sha256_file(raw) == receipt.get("sha256"):
            return receipt
    url = BASES[source] + "/" + path + (".fcgi" if source == "entrez" else "")
    receipt = {**identity, "retrieved_at": utc_now(), "url": url,
               "raw_path": str(raw.relative_to(PROJECT_ROOT)), "ok": False, "checked_sources": []}
    script = _skill_script(source)
    for attempt in range(3):
        try:
            if script:
                payload = {"params": params, "max_items": 10, "max_depth": 4, "timeout_sec": 60,
                           "save_raw": True, "raw_output_path": str(raw), "response_format": "xml" if xml else "json"}
                if source == "entrez":
                    payload["endpoint"] = path
                else:
                    payload.update({"base_url": BASES[source], "path": path, "headers": {"Accept": "application/json"}})
                if source == "reactome" and path == "data/database/version":
                    payload.update({"headers": {"Accept": "text/plain"}, "response_format": "text"})
                process = subprocess.run([sys.executable, str(script)], input=json.dumps(payload),
                                         text=True, capture_output=True, timeout=90)
                result = json.loads(process.stdout)
                receipt.update({"ok": bool(result.get("ok")), "client": "installed_database_skill",
                                "checked_sources": result.get("checked_sources", []), "sources": result.get("sources", []),
                                "error": result.get("error"), "client_sha256": sha256_file(script)})
                if not receipt["ok"]:
                    raise Track1Error("Public database request failed")
                if path in {"data/database/version", "status.json", "esearch"}:
                    # Service versions and successful searches identify what
                    # was checked; they are not biological evidence themselves.
                    receipt["checked_sources"] += [{**s, "kind": "metadata", "supports_claim": False}
                                                    for s in receipt.get("sources", [])]
                    receipt["sources"] = []
            else:
                # Fixed public queries only; no patient material or credentials
                # is placed in URLs, request bodies, or source receipts.
                response = requests.get(url, params=params, headers={"Accept": "application/xml" if xml else "application/json"}, timeout=60)
                if source == "fda" and response.status_code == 404:
                    content = b'{"results": [], "coverage": "checked_empty"}'
                else:
                    response.raise_for_status()
                    content = response.content
                temporary = raw.with_suffix(raw.suffix + ".part")
                temporary.write_bytes(content)
                temporary.replace(raw)
                receipt.update({"ok": True, "client": "portable_public_http", "status_code": response.status_code})
            receipt["sha256"] = sha256_file(raw)
            receipt["size"] = raw.stat().st_size
            break
        except (OSError, ValueError, subprocess.SubprocessError, requests.RequestException, Track1Error) as exc:
            receipt.update({"ok": False, "error_category": type(exc).__name__, "attempts": attempt + 1})
            if attempt < 2:
                time.sleep(2 ** attempt)
        finally:
            # Stay below unauthenticated NCBI rate limits and be courteous to
            # other public services even when responses come from cache.
            time.sleep(0.4)
    atomic_write_json(receipt_path, receipt, mode=0o644)
    return receipt


def payload(receipt: dict):
    if not receipt.get("ok"):
        return {} if not receipt.get("xml") else ""
    path = PROJECT_ROOT / receipt["raw_path"]
    return path.read_text() if receipt.get("xml") else json.loads(path.read_text())
