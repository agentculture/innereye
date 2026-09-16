"""t1: the portable recipe and its compile path."""

from __future__ import annotations

import pytest

from innereye.cli._errors import CliError
from innereye.recipe import GraphMapping, Recipe, compile_recipe

# Two graphs that place the SAME recipe fields on DIFFERENT node ids -- the
# reason a mapping is part of the contract rather than an inference.
FLUX_GRAPH = {
    "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "placeholder", "clip": ["11", 0]}},
    "25": {"class_type": "RandomNoise", "inputs": {"noise_seed": 42}},
    "27": {"class_type": "EmptySD3LatentImage", "inputs": {"width": 1024, "height": 1024}},
    "17": {"class_type": "BasicScheduler", "inputs": {"steps": 20, "denoise": 1.0}},
    "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "flux_output"}},
}
FLUX_MAP = GraphMapping(
    fields={
        "inputs.prompt": "6.inputs.text",
        "params.seed": "25.inputs.noise_seed",
        "params.width": "27.inputs.width",
        "params.height": "27.inputs.height",
        "params.steps": "17.inputs.steps",
    },
    output_node="9",
)

HIDREAM_GRAPH = {
    "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "placeholder"}},
    "8": {"class_type": "RandomNoise", "inputs": {"noise_seed": 1}},
    "12": {"class_type": "SaveImage", "inputs": {"filename_prefix": "hidream_output"}},
}
HIDREAM_MAP = GraphMapping(
    fields={"inputs.prompt": "3.inputs.text", "params.seed": "8.inputs.noise_seed"},
    output_node="12",
)


def test_recipe_rejects_unknown_task() -> None:
    with pytest.raises(CliError) as exc:
        Recipe(task="text_to_hologram")
    assert "unknown task" in exc.value.message
    assert exc.value.remediation


def test_recipe_rejects_unknown_input() -> None:
    with pytest.raises(CliError):
        Recipe(task="text_to_image", inputs={"vibes": "cosy"})


def test_video_is_not_a_special_case() -> None:
    """length and fps are ordinary params sharing one compile path."""
    graph = {
        "40": {"class_type": "EmptyHunyuanLatentVideo", "inputs": {"length": 81}},
        "28": {"class_type": "SaveAnimatedWEBP", "inputs": {"fps": 16}},
    }
    mapping = GraphMapping(
        fields={"params.length": "40.inputs.length", "params.fps": "28.inputs.fps"},
        output_node="28",
    )
    recipe = Recipe(task="text_to_video", params={"length": 49, "fps": 24})
    compiled = compile_recipe(recipe, graph, mapping)
    assert compiled["40"]["inputs"]["length"] == 49
    assert compiled["28"]["inputs"]["fps"] == 24
    assert recipe.is_video


def test_same_recipe_lands_on_different_node_ids() -> None:
    """The acceptance criterion: one recipe, two graphs, different nodes."""
    recipe = Recipe(task="text_to_image", inputs={"prompt": "a snow leopard"}, params={"seed": 7})
    flux = compile_recipe(recipe, FLUX_GRAPH, FLUX_MAP)
    hidream = compile_recipe(recipe, HIDREAM_GRAPH, HIDREAM_MAP)
    assert flux["6"]["inputs"]["text"] == "a snow leopard"
    assert flux["25"]["inputs"]["noise_seed"] == 7
    assert hidream["3"]["inputs"]["text"] == "a snow leopard"
    assert hidream["8"]["inputs"]["noise_seed"] == 7


def test_compile_does_not_mutate_the_operator_graph() -> None:
    recipe = Recipe(task="text_to_image", inputs={"prompt": "new"}, params={"seed": 5})
    compile_recipe(recipe, FLUX_GRAPH, FLUX_MAP)
    assert FLUX_GRAPH["6"]["inputs"]["text"] == "placeholder"
    assert FLUX_GRAPH["25"]["inputs"]["noise_seed"] == 42


def test_unmapped_field_is_refused_not_dropped() -> None:
    """Silently dropping a field would generate something other than what was asked."""
    recipe = Recipe(task="text_to_image", inputs={"prompt": "x"}, params={"sampler": "euler"})
    with pytest.raises(CliError) as exc:
        compile_recipe(recipe, FLUX_GRAPH, FLUX_MAP)
    assert "params.sampler" in exc.value.message
    assert exc.value.code == 1


def test_mapping_naming_an_absent_node_is_refused() -> None:
    mapping = GraphMapping(fields={"inputs.prompt": "999.inputs.text"}, output_node="9")
    with pytest.raises(CliError) as exc:
        compile_recipe(Recipe(task="text_to_image", inputs={"prompt": "x"}), FLUX_GRAPH, mapping)
    assert "999" in exc.value.message


def test_absent_output_node_is_refused() -> None:
    mapping = GraphMapping(fields={"inputs.prompt": "6.inputs.text"}, output_node="404")
    with pytest.raises(CliError) as exc:
        compile_recipe(Recipe(task="text_to_image", inputs={"prompt": "x"}), FLUX_GRAPH, mapping)
    assert "404" in exc.value.message
