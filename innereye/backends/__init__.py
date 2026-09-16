"""Backend adapters: capability declaration, the adapter protocol, negotiation.

Every adapter **declares** which tasks and input modalities it supports. When a
recipe asks for something the selected backend cannot do, innereye **fails
honestly** — with a message naming a backend that could, or saying plainly that
none does.

The rule this module exists to enforce: **never silently downgrade.** Turning an
embedding input into "the closest text prompt" and generating anyway is the
worst available behaviour, because the caller cannot tell the difference from
the output.

The negotiation mechanism is built here **before** a second backend exists and
before any embedding support exists. One backend needs no negotiation, so it is
tempting to defer this — but retrofitting it later means rewriting every verb,
and the refusal path is precisely the behaviour that has to be correct on day
one.

Note what is deliberately absent: no model name, no graph filename, no default
resolution. Those resolve from the operator-supplied graph and mapping, never
from a constant in innereye.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from innereye.cli._errors import EXIT_USER_ERROR, CliError
from innereye.recipe import MODALITIES, TASKS, GraphMapping, Recipe


@dataclass(frozen=True)
class Capability:
    """What one adapter can actually do.

    Declared, not inferred. An adapter that lists a task it cannot perform is a
    bug the negotiation layer cannot catch — which is why declarations are
    validated against the known vocabularies at construction.
    """

    tasks: frozenset[str]
    modalities: frozenset[str]

    def __post_init__(self) -> None:
        for name, declared, known in (
            ("task", self.tasks, TASKS),
            ("modality", self.modalities, MODALITIES),
        ):
            unknown = sorted(declared - known)
            if unknown:
                raise CliError(
                    code=EXIT_USER_ERROR,
                    message=f"adapter declares unknown {name}(s): {', '.join(unknown)}",
                    remediation=f"valid {name}s: {', '.join(sorted(known))}",
                )

    def supports(self, recipe: Recipe) -> bool:
        return recipe.task in self.tasks and recipe.modalities() <= self.modalities


@runtime_checkable
class Backend(Protocol):
    """The contract every adapter implements.

    Methods take and return primitives so an adapter never has to import the
    job store: the store is the CLI's concern, the adapter's job is to talk to
    its backend.
    """

    name: str

    def capability(self) -> Capability:
        """Declare what this adapter supports."""
        ...

    def compile(
        self,
        recipe: Recipe,
        graph: Mapping[str, Any],
        mapping: GraphMapping,
    ) -> dict[str, Any]:
        """Turn a recipe into this backend's native submission payload."""
        ...

    def submit(self, payload: Mapping[str, Any]) -> str:
        """Enqueue the payload; return a backend job id."""
        ...

    def status(self, job_id: str) -> dict[str, Any]:
        """Return ``{"state": <str>, ...}`` for a previously submitted job."""
        ...

    def fetch(self, job_id: str, output_node: str) -> Sequence[tuple[str, bytes]]:
        """Return ``(filename, bytes)`` pairs for a completed job's artifacts."""
        ...

    def cancel(self, job_id: str) -> None:
        """Ask the backend to stop a queued or running job."""
        ...


# Capabilities of backends innereye knows about, whether or not they are
# installed here. This is what lets a refusal name an alternative instead of
# just saying no -- the point of negotiation is to be actionable.
KNOWN_CAPABILITIES: dict[str, Capability] = {}


def register_capability(name: str, capability: Capability) -> None:
    """Record a backend's declared capability for negotiation messages."""
    KNOWN_CAPABILITIES[name] = capability


def alternatives_for(recipe: Recipe, *, exclude: str = "") -> list[str]:
    """Names of known backends that could satisfy ``recipe``."""
    return sorted(
        name
        for name, capability in KNOWN_CAPABILITIES.items()
        if name != exclude and capability.supports(recipe)
    )


def negotiate(recipe: Recipe, backend: Backend) -> None:
    """Raise :class:`CliError` unless ``backend`` can actually serve ``recipe``.

    Returns ``None`` on success so callers read as a guard clause. The error
    distinguishes the two ways a backend can fall short -- an unsupported task
    versus an unsupported input modality -- because the remedies differ.
    """
    capability = backend.capability()

    missing_modalities = sorted(recipe.modalities() - capability.modalities)
    task_supported = recipe.task in capability.tasks

    if task_supported and not missing_modalities:
        return

    if missing_modalities:
        shortfall = f"input modality: {', '.join(missing_modalities)}"
    else:
        shortfall = f"task: {recipe.task}"

    others = alternatives_for(recipe, exclude=backend.name)
    if others:
        remediation = f"a backend that can: {', '.join(others)} -- select it with --backend"
    else:
        remediation = (
            "no registered backend declares support for this; "
            "innereye will not approximate it with a different input"
        )

    raise CliError(
        code=EXIT_USER_ERROR,
        message=f"backend {backend.name!r} does not support this recipe ({shortfall})",
        remediation=remediation,
    )
