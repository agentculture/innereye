#!/usr/bin/env bash
# innereye.sh — drive the innereye CLI (the /innereye skill).
#
# innereye is the AgentCulture mesh's visual output surface: it renders and
# previews images and videos from text or image inputs, compiling a portable
# (task, inputs, params) recipe into an operator-supplied backend graph.
#
# This wrapper is the agent-facing operator for the CLI: it resolves the binary
# portably and forwards every verb verbatim. It adds no behaviour of its own --
# the CLI owns the contract, and `innereye learn` / `innereye explain <path>`
# are authoritative wherever this wrapper and the tool disagree.
#
# Origin: authored and maintained in agentculture/innereye alongside the CLI it
# drives. guildmaster pulls this skill from here and broadcasts it to the rest
# of the mesh, so it is written to run anywhere -- portable bash, no
# innereye-checkout assumptions.
#
# Artifacts are written relative to the current directory (see --out), so run
# from wherever you want the results to land.

set -euo pipefail

# ── resolve the innereye CLI (mesh-first, then local-dev fallback) ──────────
INNEREYE=()
resolve_innereye() {
    if command -v innereye >/dev/null 2>&1; then
        INNEREYE=(innereye)          # installed tool — the normal mesh case
        return 0
    fi
    # Local development inside the innereye checkout itself.
    if [ -f pyproject.toml ] && grep -q '^name = "innereye"' pyproject.toml 2>/dev/null \
       && command -v uv >/dev/null 2>&1; then
        INNEREYE=(uv run innereye)
        return 0
    fi
    return 1
}

if ! resolve_innereye; then
    cat >&2 <<'HINT'
error: innereye is not installed
hint: uv tool install innereye   (or: pip install --user innereye)
      innereye also needs a generation backend it can reach -- by default a
      ComfyUI server on http://127.0.0.1:8188. It does not install one.
HINT
    exit 2
fi

if [ "$#" -eq 0 ]; then
    # No verb: print the self-teaching prompt rather than a bare usage error.
    exec "${INNEREYE[@]}" learn
fi

exec "${INNEREYE[@]}" "$@"
