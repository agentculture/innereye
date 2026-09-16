"""t2: stdlib HTTP transport, scheme guard, and the no-traceback contract."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from innereye.backends import _http
from innereye.cli._errors import CliError


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:  # keep test output clean
        pass

    def do_GET(self) -> None:
        if self.path.startswith("/bytes"):
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.end_headers()
            self.wfile.write(b"\x89PNG-not-really")
            return
        if self.path.startswith("/bad"):
            self.send_response(400)
            self.end_headers()
            self.wfile.write(json.dumps({"error": "nope"}).encode())
            return
        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps({"path": self.path}).encode())

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        self.send_response(200)
        self.end_headers()
        ctype = self.headers.get("Content-Type", "")
        if ctype.startswith("multipart/form-data"):
            self.wfile.write(json.dumps({"name": "probe.png", "len": len(body)}).encode())
        else:
            self.wfile.write(body)


@pytest.fixture()
def server():
    """Port 0 lets the OS choose -- safe under pytest -n auto."""
    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()


def test_get_json(server: str) -> None:
    status, payload = _http.get_json(f"{server}/hello", params={"a": "b"})
    assert status == 200
    assert payload["path"] == "/hello?a=b"


def test_post_json_round_trips(server: str) -> None:
    status, payload = _http.post_json(f"{server}/prompt", {"prompt": {"9": {}}})
    assert status == 200
    assert payload == {"prompt": {"9": {}}}


def test_http_error_body_is_returned_not_raised(server: str) -> None:
    """Backends express useful failures as 4xx bodies; the caller needs them."""
    status, payload = _http.get_json(f"{server}/bad")
    assert status == 400
    assert payload["error"] == "nope"


def test_get_bytes_returns_raw_body(server: str) -> None:
    status, body = _http.get_bytes(f"{server}/bytes")
    assert status == 200
    assert isinstance(body, bytes)
    assert body.startswith(b"\x89PNG")


def test_post_multipart(server: str) -> None:
    status, payload = _http.post_multipart(
        f"{server}/upload/image",
        filename="probe.png",
        content=b"12345",
        fields={"overwrite": "true"},
    )
    assert status == 200
    assert payload["name"] == "probe.png"


def test_non_http_scheme_is_refused(tmp_path) -> None:
    """The narrow, justified alternative to a blanket bandit B310 suppression."""
    target = tmp_path / "secret.txt"
    target.write_text("do not read me")
    with pytest.raises(CliError) as exc:
        _http.get_json(target.as_uri())
    assert "non-HTTP scheme" in exc.value.message


def test_unreachable_backend_is_an_environment_error() -> None:
    with pytest.raises(CliError) as exc:
        _http.get_json("http://127.0.0.1:1/nothing", timeout=2.0)
    assert exc.value.code == 2
    assert "cannot reach backend" in exc.value.message
    assert "curl -I" in exc.value.remediation


def test_non_json_body_is_an_environment_error(server: str) -> None:
    with pytest.raises(CliError) as exc:
        _http.get_json(f"{server}/bytes")
    assert exc.value.code == 2


def test_timeout_is_an_environment_error(monkeypatch) -> None:
    def _boom(*args, **kwargs):
        raise TimeoutError()

    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    with pytest.raises(CliError) as exc:
        _http.get_json("http://127.0.0.1:8188/x", timeout=0.5)
    assert exc.value.code == 2
    assert "timed out" in exc.value.message
