"""Pinned, authenticated, on-device inference; never a hosted fallback.

Only the public model and runtime are downloaded. All inference requests use
loopback. Structured outputs are validated and saved alongside their supplied
evidence in the private tree, making automated reviews auditable locally.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import subprocess
import tarfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import jsonschema

from mva_track1.common import PROJECT_ROOT, Track1Error, atomic_write_json, atomic_write_text, ensure_private_dir, load_jsonish, sha256_file, utc_now
from mva_track1.resources import _download
from .storage import EXECUTION, require_space
from .supervisor import STATE_DIR, is_live, process_identity, read_state

ROOT = PROJECT_ROOT / "resources/public/models"
MANIFEST = ROOT / "install_manifest.json"
TOKEN = PROJECT_ROOT / "config/model_token.local.txt"
PROCESS = STATE_DIR / "model_process.json"


class InterpretationError(Track1Error):
    """An automated interpretation failed its structural or evidence gate."""


def _runtime() -> Path:
    cfg = load_jsonish(EXECUTION)["model"]
    directory = PROJECT_ROOT / ".tools" / f"llama-{cfg['runtime_release']}"
    matches = list(directory.rglob("llama-server")) if directory.exists() else []
    if len(matches) != 1:
        raise Track1Error("Pinned local inference executable is absent or ambiguous")
    return matches[0]


def _runtime_env() -> dict:
    env = os.environ.copy()
    binary = _runtime()
    env["LD_LIBRARY_PATH"] = str(binary.parent) + (":" + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else "")
    return env


def prepare() -> None:
    """Verify the small GPU runtime first, then fetch the single model file."""
    cfg = load_jsonish(EXECUTION)["model"]
    tools_root = PROJECT_ROOT / ".tools"
    tools_root.mkdir(exist_ok=True)
    archive = tools_root / cfg["runtime_archive"]
    directory = tools_root / f"llama-{cfg['runtime_release']}"
    url = f"https://github.com/ggml-org/llama.cpp/releases/download/{cfg['runtime_release']}/{cfg['runtime_archive']}"
    require_space(22_000_000_000)
    if not archive.exists():
        _download(url, archive)
    if sha256_file(archive) != cfg["runtime_sha256"]:
        raise Track1Error("Runtime archive checksum mismatch")
    if not directory.exists():
        directory.mkdir()
        with tarfile.open(archive) as source:
            source.extractall(directory, filter="data")
    binary = _runtime()
    devices = subprocess.run([str(binary), "--list-devices"], env=_runtime_env(),
                             text=True, capture_output=True, timeout=90)
    if devices.returncode or "NVIDIA" not in devices.stdout + devices.stderr:
        atomic_write_text(STATE_DIR / "model_runtime_diagnostic.txt", devices.stdout + devices.stderr)
        raise Track1Error("Pinned Vulkan runtime did not detect the NVIDIA GPU")
    from huggingface_hub import HfApi
    ROOT.mkdir(parents=True, exist_ok=True)
    lock = ROOT / "source_lock.json"
    if lock.exists():
        source = load_jsonish(lock)
    else:
        info = HfApi(token=False).model_info(cfg["repository"], files_metadata=True)
        item = next(s for s in info.siblings if s.rfilename == cfg["filename"])
        source = {"repository": cfg["repository"], "revision": info.sha,
                  "filename": item.rfilename, "size": item.size, "sha256": item.lfs.sha256}
        atomic_write_json(lock, source, mode=0o644)
    model = ROOT / source["filename"]
    if not model.exists():
        _download(f"https://huggingface.co/{source['repository']}/resolve/{source['revision']}/{source['filename']}", model)
    if model.stat().st_size != source["size"] or sha256_file(model) != source["sha256"]:
        raise Track1Error("Local model size/checksum mismatch")
    atomic_write_json(MANIFEST, {"model": source, "runtime": {
        "release": cfg["runtime_release"], "archive_sha256": cfg["runtime_sha256"],
        "binary_sha256": sha256_file(binary), "backend": "Vulkan", "gpu_detected": True},
        "created_at": utc_now()}, mode=0o644)
    start()
    answer = infer("Return the requested JSON object. /no_think", "Return healthy=true.",
                   {"type":"object", "properties":{"healthy":{"type":"boolean"}},
                    "required":["healthy"], "additionalProperties":False}, "synthetic_runtime")
    if answer.get("healthy") is not True:
        raise InterpretationError("Local inference synthetic smoke test failed")
    atomic_write_json(STATE_DIR / "model_smoke.json", {"passed": True, "checked_at": utc_now()})


def _endpoint() -> str:
    cfg = load_jsonish(EXECUTION)["model"]
    if cfg["host"] != "127.0.0.1" or not 1024 <= int(cfg["port"]) <= 65535:
        raise Track1Error("Private inference must use a local unprivileged loopback port")
    return f"http://127.0.0.1:{int(cfg['port'])}"


def _healthy() -> bool:
    try:
        # Do not send credentials to a server unless it is the process we own.
        if not is_live(read_state(PROCESS).get("process")):
            return False
        with urllib.request.urlopen(_endpoint() + "/health", timeout=3) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def start() -> None:
    if _healthy():
        return
    if is_live(read_state(PROCESS).get("process")):
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            if _healthy():
                return
            time.sleep(2)
        raise Track1Error("Owned inference process did not become healthy")
    cfg = load_jsonish(EXECUTION)["model"]
    _endpoint()
    manifest = load_jsonish(MANIFEST)
    model = ROOT / manifest["model"]["filename"]
    if model.stat().st_size != manifest["model"]["size"]:
        raise Track1Error("Local model size changed")
    if not TOKEN.exists():
        atomic_write_text(TOKEN, secrets.token_urlsafe(32) + "\n")
    ensure_private_dir(STATE_DIR)
    ensure_private_dir(PROJECT_ROOT / "logs")
    command = [str(_runtime()), "--model", str(model), "--alias", "mva-local",
               "--host", "127.0.0.1", "--port", str(cfg["port"]),
               "--api-key-file", str(TOKEN), "--ctx-size", str(cfg["context_tokens"]),
               "--parallel", "1", "--threads", "16", "--n-gpu-layers", "99",
               "--jinja", "--no-webui", "--log-disable"]
    with (PROJECT_ROOT / "logs/local_model.log").open("a") as log:
        process = subprocess.Popen(command, env=_runtime_env(), cwd=PROJECT_ROOT,
                                   stdout=log, stderr=log, start_new_session=True)
    atomic_write_json(PROCESS, {"process": process_identity(process.pid), "started_at": utc_now()})
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        if _healthy():
            return
        if process.poll() is not None:
            raise Track1Error("Local inference exited during startup; inspect local runtime log")
        time.sleep(2)
    raise Track1Error("Local inference startup timed out")


def infer(system: str, user: str, schema: dict, purpose: str) -> dict:
    """Cache the exact request and validated response in the private tree."""
    cfg = load_jsonish(EXECUTION)["model"]
    payload = {"model":"mva-local", "messages":[{"role":"system","content":system},
               {"role":"user","content":user}], "max_tokens":cfg["output_tokens"],
               "temperature":cfg["temperature"], "top_p":cfg["top_p"], "top_k":cfg["top_k"],
               "presence_penalty":cfg["presence_penalty"], "seed":cfg["seed"],
               "response_format":{"type":"json_schema","json_schema":{"name":"evidence","strict":True,"schema":schema}},
               "chat_template_kwargs":{"enable_thinking":False}}
    key = hashlib.sha256((json.dumps(payload,sort_keys=True) + sha256_file(MANIFEST)).encode()).hexdigest()
    cache = ensure_private_dir(PROJECT_ROOT / "work/private/inference") / f"{key}.json"
    if cache.exists():
        result = load_jsonish(cache)["answer"]
        jsonschema.validate(result, schema)
        return result
    start()
    # Read credentials only into a local request header; never print or persist it.
    request = urllib.request.Request(_endpoint() + "/v1/chat/completions",
        data=json.dumps(payload).encode(), headers={"Content-Type":"application/json",
        "Authorization":"Bearer " + TOKEN.read_text().strip()})
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            reply = json.load(response)
        text = reply["choices"][0]["message"]["content"]
        if "</think>" in text:
            text = text.split("</think>",1)[1].strip()
        answer = json.loads(text)
        jsonschema.validate(answer, schema)
    except (ValueError, KeyError, jsonschema.ValidationError) as exc:
        raise InterpretationError("Local output failed schema validation") from exc
    atomic_write_json(cache, {"purpose":purpose,"request":payload,"answer":answer,
                             "model_manifest_sha256":sha256_file(MANIFEST),
                             "usage":reply.get("usage",{}),"created_at":utc_now()})
    return answer
