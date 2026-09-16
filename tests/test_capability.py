"""t3: capability declaration and honest refusal."""

from __future__ import annotations

import pytest

from innereye import backends
from innereye.backends import Capability, negotiate, register_capability
from innereye.cli._errors import CliError
from innereye.recipe import Recipe


class _Fake:
    def __init__(self, name: str, capability: Capability) -> None:
        self.name = name
        self._capability = capability

    def capability(self) -> Capability:
        return self._capability


IMAGE_ONLY = Capability(tasks=frozenset({"text_to_image"}), modalities=frozenset({"text"}))


@pytest.fixture(autouse=True)
def _clean_registry():
    saved = dict(backends.KNOWN_CAPABILITIES)
    backends.KNOWN_CAPABILITIES.clear()
    yield
    backends.KNOWN_CAPABILITIES.clear()
    backends.KNOWN_CAPABILITIES.update(saved)


def test_capability_rejects_an_unknown_task_declaration() -> None:
    with pytest.raises(CliError):
        Capability(tasks=frozenset({"text_to_smell"}), modalities=frozenset({"text"}))


def test_supported_recipe_passes_negotiation() -> None:
    negotiate(Recipe(task="text_to_image", inputs={"prompt": "x"}), _Fake("comfyui", IMAGE_ONLY))


def test_embedding_input_is_refused_never_downgraded() -> None:
    """The load-bearing refusal: no silent fallback to 'the closest text prompt'."""
    recipe = Recipe(task="embedding_to_image", inputs={"embedding": [0.1, 0.2]})
    with pytest.raises(CliError) as exc:
        negotiate(recipe, _Fake("comfyui", IMAGE_ONLY))
    assert exc.value.code == 1
    assert "embedding" in exc.value.message
    assert "will not approximate" in exc.value.remediation


def test_refusal_names_a_backend_that_could() -> None:
    register_capability(
        "future-backend",
        Capability(tasks=frozenset({"text_to_video"}), modalities=frozenset({"text"})),
    )
    with pytest.raises(CliError) as exc:
        negotiate(
            Recipe(task="text_to_video", inputs={"prompt": "x"}), _Fake("comfyui", IMAGE_ONLY)
        )
    assert "future-backend" in exc.value.remediation


def test_unsupported_task_reports_the_task_not_the_modality() -> None:
    with pytest.raises(CliError) as exc:
        negotiate(
            Recipe(task="text_to_video", inputs={"prompt": "x"}), _Fake("comfyui", IMAGE_ONLY)
        )
    assert "task: text_to_video" in exc.value.message
