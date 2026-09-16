"""Stdlib-only HTTP transport for backend adapters.

The runtime package has **no third-party dependencies** and this module is the
main place that rule gets tested: a ComfyUI adapter speaks HTTP + JSON, which
``urllib`` and ``json`` cover — including the multipart upload, which is
hand-rolled below rather than pulling in a library for one request.

Two contracts worth knowing before you edit:

* **Scheme guard.** ``urlopen`` accepts ``file://`` and other schemes, which is
  what bandit's B310 warns about. B310 is *not* in this repo's bandit skips, so
  rather than blanket-suppressing it, :func:`_guarded_open` validates the scheme
  and the suppression is narrow and justified at the single call site.
* **Bytes never reach the output layer.** :func:`get_bytes` returns bytes to its
  caller, which writes a file. ``innereye.cli._output`` is text/JSON only, and
  routing an artifact through it would violate the stdout/stderr contract.
"""

from __future__ import annotations

import json
import mimetypes
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any, Mapping

from innereye.cli._errors import EXIT_ENV_ERROR, EXIT_USER_ERROR, CliError

_ALLOWED_SCHEMES = frozenset({"http", "https"})

DEFAULT_TIMEOUT = 30.0


def _guarded_open(request: urllib.request.Request, timeout: float) -> Any:
    """Open ``request`` after proving its scheme is HTTP(S).

    The explicit check is what makes the ``nosec`` below narrow and honest:
    every other scheme urlopen would accept is rejected before we get here.
    """
    scheme = urllib.parse.urlsplit(request.full_url).scheme.lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"refusing non-HTTP scheme {scheme or '(none)'!r} in backend endpoint",
            remediation="backend endpoints must be http:// or https://",
        )
    return urllib.request.urlopen(request, timeout=timeout)  # nosec B310 - scheme checked above


def _dispatch(
    request: urllib.request.Request,
    *,
    timeout: float,
    endpoint: str,
) -> tuple[int, bytes]:
    """Perform ``request``, mapping every transport failure onto :class:`CliError`.

    An HTTP error response is *returned*, not raised: backends express useful
    failures (a graph naming absent weights, an invalid status filter) as 4xx
    bodies, and the caller needs that body to build a remediation.
    """
    try:
        with _guarded_open(request, timeout) as response:
            return int(response.status), response.read()
    except urllib.error.HTTPError as exc:  # a real response, just not a 2xx
        return int(exc.code), exc.read()
    except urllib.error.URLError as exc:
        raise CliError(
            code=EXIT_ENV_ERROR,
            message=f"cannot reach backend at {endpoint}: {exc.reason}",
            remediation=(
                "start the backend and confirm the endpoint, e.g. " "curl -I http://127.0.0.1:8188"
            ),
        ) from exc
    except TimeoutError as exc:
        raise CliError(
            code=EXIT_ENV_ERROR,
            message=f"backend at {endpoint} timed out after {timeout:g}s",
            remediation="raise the timeout, or check whether the backend is overloaded",
        ) from exc


def _decode_json(body: bytes, *, endpoint: str) -> Any:
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CliError(
            code=EXIT_ENV_ERROR,
            message=f"backend at {endpoint} returned a non-JSON body",
            remediation="confirm the endpoint points at the backend's API, not a web UI",
        ) from exc


def get_json(
    url: str,
    *,
    params: Mapping[str, Any] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> tuple[int, Any]:
    """GET ``url`` and decode a JSON body. Returns ``(status, payload)``."""
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, method="GET")
    status, body = _dispatch(request, timeout=timeout, endpoint=url)
    return status, _decode_json(body, endpoint=url)


def post_json(
    url: str,
    payload: Mapping[str, Any],
    *,
    timeout: float = DEFAULT_TIMEOUT,
) -> tuple[int, Any]:
    """POST ``payload`` as JSON and decode a JSON body. Returns ``(status, payload)``."""
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    status, body = _dispatch(request, timeout=timeout, endpoint=url)
    return status, _decode_json(body, endpoint=url)


def get_bytes(
    url: str,
    *,
    params: Mapping[str, Any] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> tuple[int, bytes]:
    """GET ``url`` and return the raw body.

    Artifact bytes come back here and are written to disk by the caller — they
    never pass through the CLI output layer.
    """
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, method="GET")
    return _dispatch(request, timeout=timeout, endpoint=url)


def post_multipart(
    url: str,
    *,
    fields: Mapping[str, str] | None = None,
    filename: str,
    content: bytes,
    file_field: str = "image",
    timeout: float = DEFAULT_TIMEOUT,
) -> tuple[int, Any]:
    """POST one file as ``multipart/form-data`` and decode a JSON body.

    Hand-rolled on purpose: this is the single multipart request innereye
    makes, and adding a dependency for it would end the no-dependency rule for
    the whole package.
    """
    boundary = f"----innereye{uuid.uuid4().hex}"
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"

    parts: list[bytes] = []
    for name, value in (fields or {}).items():
        parts.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{value}\r\n".encode("utf-8")
        )
    parts.append(
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n".encode("utf-8")
    )
    parts.append(content)
    parts.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
    data = b"".join(parts)

    request = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(data)),
        },
    )
    status, body = _dispatch(request, timeout=timeout, endpoint=url)
    return status, _decode_json(body, endpoint=url)
