"""t8: the render verb -- dry-run default, graph pair required, demo seam."""

from __future__ import annotations

import json

import pytest

from innereye.backends import _http
from innereye.cli import main
from innereye.cli._commands import render as render_cmd

GRAPH = {
    "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "x"}},
    "25": {"class_type": "RandomNoise", "inputs": {"noise_seed": 1}},
    "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "o"}},
}
MAPPING = {
    "output_node": "9",
    "fields": {"inputs.prompt": "6.inputs.text", "params.seed": "25.inputs.noise_seed"},
}


@pytest.fixture
def pair(tmp_path):
    g = tmp_path / "flux.api.json"
    g.write_text(json.dumps(GRAPH))
    (tmp_path / "flux.api.json.mapping.json").write_text(json.dumps(MAPPING))
    return g


def test_missing_graph_names_how_to_get_one(capsys) -> None:
    """Never a silent fallback to a bundled or downloaded default."""
    rc = main(["render", "--prompt", "a cat"])
    assert rc == 1
    err = capsys.readouterr().err
    assert err.startswith("error:")
    assert "--graph is required" in err
    assert "Save (API Format)" in err
    assert "--demo" in err


def test_graph_without_mapping_is_refused(tmp_path, capsys) -> None:
    g = tmp_path / "lonely.api.json"
    g.write_text(json.dumps(GRAPH))
    rc = main(["render", "--prompt", "a cat", "--graph", str(g)])
    assert rc == 1
    assert "no graph mapping found" in capsys.readouterr().err


def test_dry_run_is_the_default_and_submits_nothing(pair, capsys, monkeypatch) -> None:
    def _boom(*a, **k):
        raise AssertionError("dry run must not touch the network")

    monkeypatch.setattr(_http, "post_json", _boom)
    monkeypatch.setattr(_http, "get_json", _boom)

    rc = main(["render", "--prompt", "a snow leopard", "--graph", str(pair)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "dry run" in out
    assert "comfyui at http://127.0.0.1:8188" in out
    assert "--apply" in out


def test_dry_run_json_carries_recipe_and_backend(pair, capsys) -> None:
    rc = main(["render", "--prompt", "a cat", "--graph", str(pair), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True
    assert payload["backend"] == "comfyui"
    assert payload["output_node"] == "9"
    assert payload["recipe"]["inputs"]["prompt"] == "a cat"
    assert isinstance(payload["recipe"]["params"]["seed"], int)


def test_seed_is_chosen_even_when_not_given(pair, capsys) -> None:
    main(["render", "--prompt", "a", "--graph", str(pair), "--json"])
    first = json.loads(capsys.readouterr().out)["recipe"]["params"]["seed"]
    main(["render", "--prompt", "a", "--graph", str(pair), "--json"])
    second = json.loads(capsys.readouterr().out)["recipe"]["params"]["seed"]
    assert first != second  # innereye picks; never a backend default


def test_capability_mismatch_is_a_user_error_naming_the_shortfall(pair, capsys) -> None:
    rc = main(["render", "--graph", str(pair), "--task", "embedding_to_image", "--prompt", "x"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "does not support this recipe" in err
    assert "embedding_to_image" in err


def test_demo_writes_a_graph_and_a_mapping(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(_http, "get_bytes", lambda url, **k: (200, json.dumps(GRAPH).encode()))
    rc = main(["render", "--demo", "flux-text-to-image", "--into", str(tmp_path), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["task"] == "text_to_image"
    assert "tier 1" in payload["weights_required"]
    mapping = json.loads((tmp_path / "flux-text-to-image.api.json.mapping.json").read_text())
    assert mapping["output_node"] == "9"
    # one field, two node paths -- flux reads the resolution twice
    assert mapping["fields"]["params.width"] == ["27.inputs.width", "30.inputs.width"]


def test_unknown_demo_name_lists_the_real_ones(capsys) -> None:
    rc = main(["render", "--demo", "nope"])
    assert rc == 1
    assert "flux-text-to-image" in capsys.readouterr().err


def test_demo_refuses_to_clobber(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(_http, "get_bytes", lambda url, **k: (200, json.dumps(GRAPH).encode()))
    main(["render", "--demo", "flux-text-to-image", "--into", str(tmp_path)])
    capsys.readouterr()
    rc = main(["render", "--demo", "flux-text-to-image", "--into", str(tmp_path)])
    assert rc == 1
    assert "refusing to overwrite" in capsys.readouterr().err


def test_demo_catalog_node_ids_differ_between_graphs() -> None:
    """The reason a mapping ships with each download rather than one global default."""
    flux = render_cmd.DEMO_GRAPHS["flux-text-to-image"]["mapping"]
    wan = render_cmd.DEMO_GRAPHS["wan-text-to-video"]["mapping"]
    assert flux["output_node"] != wan["output_node"]
    assert flux["fields"]["params.seed"] != wan["fields"]["params.seed"]


def test_dry_run_compiles_so_a_bad_mapping_fails_before_spending(tmp_path, capsys) -> None:
    """A pre-spend check that does not compile is not a check."""
    g = tmp_path / "g.api.json"
    g.write_text(json.dumps(GRAPH))
    (tmp_path / "g.api.json.mapping.json").write_text(
        json.dumps(
            {
                "output_node": "404",  # names a node the graph does not have
                "fields": {
                    "inputs.prompt": "6.inputs.text",
                    "params.seed": "25.inputs.noise_seed",
                },
            }
        )
    )
    rc = main(["render", "--prompt", "x", "--graph", str(g)])
    assert rc == 1
    assert "404" in capsys.readouterr().err


def test_dry_run_reports_the_effective_settings(pair, capsys) -> None:
    rc = main(["render", "--prompt", "a", "--graph", str(pair), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["graph_digest"]
    assert "sampling" in payload["resolved"]


def test_demo_download_is_pinned_to_an_immutable_commit() -> None:
    """A moving branch means upstream can change what runs on the operator's GPU."""
    assert "refs/heads/main" not in render_cmd._PLAYBOOK_BASE
    assert len(render_cmd._PLAYBOOK_COMMIT) == 40
