"""Synthetic requests only; transport spies never open a real network socket."""
import io
import json
import urllib.request
import urllib.response
from email.message import Message

import pytest

from mva_runner import local
from mva_track1.common import Track1Error


@pytest.fixture
def endpoint(monkeypatch):
    value = "http://127.0.0.1:18433"
    monkeypatch.setattr(local, "_endpoint", lambda: value)
    return value


def response(url, code=200, body=b"{}", location=None):
    headers = Message()
    if location:
        headers["Location"] = location
    result = urllib.response.addinfourl(io.BytesIO(body), headers, url, code)
    result.msg = "synthetic response"
    return result


def test_loopback_transport_ignores_environment_proxies(monkeypatch, endpoint):
    # No bypass entry is required, even when every proxy variable is inherited.
    for name in ("http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
        monkeypatch.setenv(name, "http://proxy.invalid:18888")
    monkeypatch.setenv("no_proxy", "")
    monkeypatch.setenv("NO_PROXY", "")
    seen = []

    def http_open(handler, request):
        seen.append(request)
        assert request.host == "127.0.0.1:18433"
        assert not request.has_proxy()
        return response(request.full_url)

    monkeypatch.setattr(urllib.request.HTTPHandler, "http_open", http_open)
    request = urllib.request.Request(endpoint + "/v1/chat/completions", data=b"synthetic",
                                     headers={"Authorization": "Bearer invented-test-value"})
    with local._open_local(request, timeout=3) as reply:
        assert reply.status == 200
    assert len(seen) == 1
    assert seen[0].data == b"synthetic"


@pytest.mark.parametrize("code", [301, 302, 303, 307, 308])
def test_redirects_never_forward_body_or_credentials(monkeypatch, endpoint, code):
    seen = []
    replies = []

    def http_open(handler, request):
        seen.append(request.full_url)
        reply = response(request.full_url, code, location="http://forbidden.invalid/synthetic-secret")
        replies.append(reply)
        return reply

    monkeypatch.setattr(urllib.request.HTTPHandler, "http_open", http_open)
    request = urllib.request.Request(endpoint + "/v1/chat/completions", data=b"synthetic",
                                     headers={"Authorization": "Bearer invented-test-value"})
    with pytest.raises(Track1Error, match="redirects are forbidden") as error:
        local._open_local(request, timeout=3)
    assert seen == [endpoint + "/v1/chat/completions"]
    assert replies[0].closed
    assert "synthetic-secret" not in str(error.value)


@pytest.mark.parametrize("url", [
    "http://remote.invalid/v1/chat/completions", "https://127.0.0.1:18433/health",
    "http://127.0.0.1:18434/health", "http://127.0.0.1:18433/health?secret=synthetic",
])
def test_unapproved_destination_is_rejected_before_transport(monkeypatch, endpoint, url):
    monkeypatch.setattr(urllib.request, "build_opener", lambda *args: pytest.fail("Transport was reached"))
    with pytest.raises(Track1Error, match="unapproved destination"):
        local._open_local(url, timeout=3)


def test_preproxied_request_is_rejected(monkeypatch, endpoint):
    request = urllib.request.Request(endpoint + "/health")
    request.set_proxy("proxy.invalid:18888", "http")
    monkeypatch.setattr(urllib.request, "build_opener", lambda *args: pytest.fail("Transport was reached"))
    with pytest.raises(Track1Error, match="cannot use a proxy"):
        local._open_local(request, timeout=3)


def test_health_requires_owned_process_and_uses_direct_transport(monkeypatch, endpoint):
    monkeypatch.setattr(local, "read_state", lambda path: {"process": {"pid": 123, "created": 1.0}})
    monkeypatch.setattr(local, "is_live", lambda identity: False)
    seen = []

    def open_local(request, *, timeout):
        seen.append((request, timeout))
        return response(request)

    monkeypatch.setattr(local, "_open_local", open_local)
    assert not local._healthy()
    assert not seen
    monkeypatch.setattr(local, "is_live", lambda identity: True)
    assert local._healthy()
    assert seen == [(endpoint + "/health", 3)]


def test_inference_uses_direct_transport_and_private_cache(monkeypatch, tmp_path, endpoint):
    manifest, token = tmp_path / "manifest.json", tmp_path / "token.txt"
    manifest.write_text("{}")
    token.write_text("invented-test-value")
    monkeypatch.setattr(local, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(local, "MANIFEST", manifest)
    monkeypatch.setattr(local, "TOKEN", token)
    original_load = local.load_jsonish
    cfg = {"output_tokens": 10, "temperature": 0, "top_p": 1, "top_k": 1, "presence_penalty": 0, "seed": 1}
    monkeypatch.setattr(local, "load_jsonish", lambda path: {"model": cfg} if path == local.EXECUTION else original_load(path))
    monkeypatch.setattr(local, "start", lambda: None)
    seen = []

    def open_local(request, *, timeout):
        seen.append(request)
        assert request.full_url == endpoint + "/v1/chat/completions"
        assert request.get_header("Authorization") == "Bearer invented-test-value"
        assert timeout == 600
        return response(request.full_url, body=json.dumps({"choices": [{"message": {"content": '{"healthy":true}'}}]}).encode())

    monkeypatch.setattr(local, "_open_local", open_local)
    schema = {"type": "object", "properties": {"healthy": {"type": "boolean"}}, "required": ["healthy"]}
    for _ in range(2):
        assert local.infer("synthetic system", "synthetic user", schema, "synthetic_transport") == {"healthy": True}
    assert len(seen) == 1
    cached = list((tmp_path / "work/private/inference").glob("*.json"))
    assert len(cached) == 1
    assert cached[0].stat().st_mode & 0o777 == 0o600
    assert "invented-test-value" not in cached[0].read_text()
