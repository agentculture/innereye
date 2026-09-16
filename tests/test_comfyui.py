"""t7: the ComfyUI adapter, against mocked transport (no live server needed)."""

from __future__ import annotations

import pytest

from innereye.backends import _http, comfyui
from innereye.backends.comfyui import ComfyUIBackend
from innereye.cli._errors import CliError
from innereye.jobs import (
    STATE_CANCELLED,
    STATE_COMPLETED,
    STATE_FAILED,
    STATE_IN_PROGRESS,
    STATE_PENDING,
    STATE_UNKNOWN,
)
from innereye.recipe import GraphMapping, Recipe

# Shapes below are copied from a LIVE ComfyUI 0.33.2 on 127.0.0.1:8188.
JOB_COMPLETED = {
    "id": "abc",
    "status": "completed",
    "outputs": {
        "2": {"images": [{"filename": "probe_00001_.png", "subfolder": "", "type": "output"}]}
    },
    "execution_status": {"status_str": "success", "completed": True, "messages": []},
}
MISSING_WEIGHTS = {
    "error": {
        "type": "prompt_outputs_failed_validation",
        "message": "Prompt outputs failed validation",
        "details": "",
    },
    "node_errors": {
        "10": {
            "class_type": "VAELoader",
            "errors": [
                {
                    "type": "value_not_in_list",
                    "message": "Value not in list",
                    "details": "vae_name: 'ae.safetensors' not in ['pixel_space']",
                    "extra_info": {"input_name": "vae_name", "received_value": "ae.safetensors"},
                }
            ],
        }
    },
}


class _Transport:
    """Records calls and replays canned responses keyed by URL substring."""

    def __init__(self, routes: dict[str, tuple[int, object]]) -> None:
        self.routes = routes
        self.calls: list[str] = []

    def _match(self, url: str):
        self.calls.append(url)
        # Longest fragment wins, so "/api/jobs/abc" is not shadowed by "/api/jobs".
        for fragment in sorted(self.routes, key=len, reverse=True):
            if fragment in url:
                return self.routes[fragment]
        return 404, {}

    def get_json(self, url, *, params=None, timeout=None):
        return self._match(url)

    def post_json(self, url, payload, *, timeout=None):
        return self._match(url)

    def get_bytes(self, url, *, params=None, timeout=None):
        code, body = self._match(url)
        return code, body if isinstance(body, bytes) else b""

    def post_multipart(
        self, url, *, fields=None, filename="", content=b"", file_field="image", timeout=None
    ):
        return self._match(url)


@pytest.fixture
def transport(monkeypatch):
    def install(routes):
        t = _Transport(routes)
        for name in ("get_json", "post_json", "get_bytes", "post_multipart"):
            monkeypatch.setattr(_http, name, getattr(t, name))
        return t

    return install


def test_embedding_is_not_declared() -> None:
    """Declaring it would be a lie the negotiation layer could not catch."""
    assert "embedding" not in comfyui.CAPABILITY.modalities
    assert "embedding_to_image" not in comfyui.CAPABILITY.tasks
    assert "text_to_video" in comfyui.CAPABILITY.tasks  # video is first-class


def test_default_endpoint_is_loopback() -> None:
    assert comfyui.DEFAULT_ENDPOINT == "http://127.0.0.1:8188"


def test_submit_returns_prompt_id(transport) -> None:
    transport({"/prompt": (200, {"prompt_id": "pid-1", "node_errors": {}})})
    assert ComfyUIBackend().submit({"1": {}}) == "pid-1"


def test_missing_weights_surfaces_the_servers_own_node_errors(transport) -> None:
    """No client-side /object_info pre-flight -- the server's error is better."""
    transport({"/prompt": (400, MISSING_WEIGHTS)})
    backend = ComfyUIBackend()
    with pytest.raises(CliError) as exc:
        backend.submit({"10": {}})
    assert exc.value.code == 1
    assert "failed validation" in exc.value.message
    assert "vae_name" in exc.value.remediation
    assert "ae.safetensors" in exc.value.remediation
    assert "pixel_space" in exc.value.remediation  # the valid list, verbatim


def test_no_object_info_preflight_happens(transport) -> None:
    t = transport({"/prompt": (200, {"prompt_id": "pid"})})
    ComfyUIBackend().submit({"1": {}})
    assert not any("object_info" in call for call in t.calls)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("pending", STATE_PENDING),
        ("in_progress", STATE_IN_PROGRESS),
        ("completed", STATE_COMPLETED),
        ("failed", STATE_FAILED),
        ("cancelled", STATE_CANCELLED),
    ],
)
def test_all_five_states_round_trip(transport, raw, expected) -> None:
    transport({"/api/jobs/abc": (200, {"id": "abc", "status": raw}), "/api/jobs": (200, {})})
    assert ComfyUIBackend().status("abc")["state"] == expected


def test_unknown_job_reports_its_own_state_not_a_crash(transport) -> None:
    """A restarted server invalidates prompt_ids; that must be reportable."""
    transport({"/api/jobs/gone": (404, {}), "/api/jobs": (200, {})})
    assert ComfyUIBackend().status("gone")["state"] == STATE_UNKNOWN


def test_history_fallback_when_jobs_api_is_absent(transport) -> None:
    t = transport(
        {
            "/api/jobs": (404, {}),
            "/history/abc": (
                200,
                {"abc": {"status": {"status_str": "success"}, "outputs": JOB_COMPLETED["outputs"]}},
            ),
        }
    )
    assert ComfyUIBackend().status("abc")["state"] == STATE_COMPLETED
    assert any("/history/" in call for call in t.calls)


def test_fetch_downloads_via_view_not_the_filesystem(transport) -> None:
    t = transport(
        {
            "/api/jobs/abc": (200, JOB_COMPLETED),
            "/api/jobs": (200, {}),
            "/view": (200, b"\x89PNG-bytes"),
        }
    )
    artifacts = ComfyUIBackend().fetch("abc", "2")
    assert artifacts == [("probe_00001_.png", b"\x89PNG-bytes")]
    assert any("/view" in call for call in t.calls)


def test_failed_job_carries_the_server_error_out(transport) -> None:
    transport(
        {
            "/api/jobs": (200, {}),
            "/api/jobs/bad": (
                200,
                {
                    "id": "bad",
                    "status": "failed",
                    "execution_status": {
                        "status_str": "error",
                        "messages": [["execution_error", {"exception_message": "OOM"}]],
                    },
                },
            ),
        }
    )
    backend = ComfyUIBackend()
    with pytest.raises(CliError) as exc:
        backend.fetch("bad", "2")
    assert exc.value.code == 2
    assert "OOM" in exc.value.remediation


def test_fetch_on_an_incomplete_job_is_a_user_error(transport) -> None:
    transport(
        {"/api/jobs": (200, {}), "/api/jobs/abc": (200, {"id": "abc", "status": "in_progress"})}
    )
    backend = ComfyUIBackend()
    with pytest.raises(CliError) as exc:
        backend.fetch("abc", "2")
    assert exc.value.code == 1
    assert "in_progress" in exc.value.message


def test_cancel_uses_the_jobs_api(transport) -> None:
    t = transport({"/api/jobs": (200, {}), "/cancel": (200, {})})
    ComfyUIBackend().cancel("abc")
    assert any(call.endswith("/api/jobs/abc/cancel") for call in t.calls)


def test_cancel_never_falls_back_to_global_interrupt(transport) -> None:
    """/interrupt stops whatever is running -- not necessarily the job asked about."""
    t = transport({"/api/jobs": (404, {})})
    backend = ComfyUIBackend()
    with pytest.raises(CliError) as exc:
        backend.cancel("abc")
    assert exc.value.code == 2
    assert "cannot be cancelled by id" in exc.value.message
    assert not any("/interrupt" in call for call in t.calls)


def test_video_to_video_is_not_declared() -> None:
    """Recipe has no video input modality, so advertising the task would fail late."""
    assert "video_to_video" not in comfyui.CAPABILITY.tasks


def test_image_uploads_get_unique_names(transport) -> None:
    """A fixed name + overwrite lets a later render replace a queued job's image."""
    t = transport({"/upload/image": (200, {"name": "server.png"})})
    graph = {"52": {"class_type": "LoadImage", "inputs": {"image": "x"}}}
    mapping = GraphMapping(fields={"inputs.image": "52.inputs.image"}, output_node="52")
    be = ComfyUIBackend()
    be.compile(Recipe(task="image_to_video", inputs={"image": b"a"}), graph, mapping)
    be.compile(Recipe(task="image_to_video", inputs={"image": b"b"}), graph, mapping)
    assert len(t.calls) == 2


def test_describe_graph_reads_effective_settings() -> None:
    """Provenance must describe the artifact, not just the command line."""
    g = {
        "12": {"class_type": "UNETLoader", "inputs": {"unet_name": "flux1-dev.safetensors"}},
        "17": {"class_type": "BasicScheduler", "inputs": {"steps": 20, "model": ["30", 0]}},
        "27": {"class_type": "EmptySD3LatentImage", "inputs": {"width": 1024, "height": 1024}},
    }
    d = comfyui.describe_graph(g)
    assert d["models"] == ["flux1-dev.safetensors"]
    assert d["sampling"]["steps"] == 20
    assert d["size"]["width"] == 1024
    assert comfyui.graph_digest(g) == comfyui.graph_digest(dict(g))


def test_image_input_is_uploaded_and_replaced_by_its_server_name(transport) -> None:
    """LoadImage takes a server-side filename, not bytes."""
    transport(
        {"/upload/image": (200, {"name": "innereye_image.png", "subfolder": "", "type": "input"})}
    )
    graph = {"52": {"class_type": "LoadImage", "inputs": {"image": "placeholder"}}}
    mapping = GraphMapping(fields={"inputs.image": "52.inputs.image"}, output_node="52")
    recipe = Recipe(task="image_to_video", inputs={"image": b"\x89PNG"})
    compiled = ComfyUIBackend().compile(recipe, graph, mapping)
    assert compiled["52"]["inputs"]["image"] == "innereye_image.png"


# Shape copied verbatim from a LIVE wan-text-to-video job on the GB10.
# SaveAnimatedWEBP puts the .webp under "images" and ALSO emits
# "animated": [true] -- a boolean flag. Treating that as media crashed the
# first real video fetch with AttributeError: 'bool' object has no attribute
# 'get'. This test is that bug.
VIDEO_COMPLETED = {
    "id": "vid",
    "status": "completed",
    "outputs": {
        "28": {
            "images": [
                {"filename": "wan_t2v_output_00001_.webp", "subfolder": "", "type": "output"}
            ],
            "animated": [True],
        }
    },
    "execution_status": {"status_str": "success", "completed": True, "messages": []},
}


def test_animated_flag_is_not_mistaken_for_media(transport) -> None:
    transport(
        {
            "/api/jobs/vid": (200, VIDEO_COMPLETED),
            "/api/jobs": (200, {}),
            "/view": (200, b"RIFF....WEBP"),
        }
    )
    artifacts = ComfyUIBackend().fetch("vid", "28")
    assert artifacts == [("wan_t2v_output_00001_.webp", b"RIFF....WEBP")]


def test_non_dict_media_entries_are_skipped(transport) -> None:
    payload = {
        "id": "x",
        "status": "completed",
        "outputs": {"1": {"images": [True, 7, {"filename": "ok.png"}]}},
    }
    transport({"/api/jobs/x": (200, payload), "/api/jobs": (200, {}), "/view": (200, b"px")})
    assert ComfyUIBackend().fetch("x", "1") == [("ok.png", b"px")]
