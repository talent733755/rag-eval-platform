"""Extract retrieval evidence from persisted traces under the adapter-v2 contract.

The adapter-v1 protocol stores trace stages as free-form ``dict[str, dict]``. To
compute retrieval metrics the platform needs a *stable* convention for where the
ordered list of retrieved chunk ids lives. The adapter-v2 contract (see
``docs/contracts/adapter-v1.md``) formalizes it:

* a retrieval-bearing stage names its ranked chunk ids under the ``ids`` key;
* ``retrieve`` / ``rerank`` are the canonical stage names;
* the *last* matching stage wins, because it reflects the final ordering handed
  to the generator.

This module only reads already-persisted, already-redacted trace stages, so it
never touches private content and stays provider-neutral.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from uuid import UUID

DEFAULT_RETRIEVAL_STAGES: tuple[str, ...] = ("retrieve", "rerank")


def _stage_ids(stage: dict[str, object]) -> list[str]:
    payload = stage.get("payload")
    if not isinstance(payload, dict):
        return []
    raw_ids = payload.get("ids")
    if not isinstance(raw_ids, list):
        return []
    return [str(item) for item in raw_ids if isinstance(item, str) and item]


def extract_retrieved_chunk_ids(
    stages: Sequence[dict[str, object]],
    *,
    stage_names: Iterable[str] = DEFAULT_RETRIEVAL_STAGES,
) -> list[str]:
    """Return the ordered retrieved chunk ids from the last matching stage.

    Returns an empty list when no structured retrieval stage is present, which
    the metric layer reports as ``retrieval_evidence_unavailable`` rather than
    fabricating a value.
    """

    wanted = {name for name in stage_names}
    selected: list[str] = []
    for stage in stages:
        if not isinstance(stage, dict):
            continue
        name = stage.get("name")
        if name not in wanted:
            continue
        ids = _stage_ids(stage)
        if ids:
            selected = ids
    return selected


def extract_retrieved_chunk_ids_from_envelope(
    stages: dict[str, object] | None,
    *,
    stage_names: Iterable[str] = DEFAULT_RETRIEVAL_STAGES,
) -> list[str]:
    """Extract retrieved ids from the raw adapter ``TraceEnvelope.stages`` dict.

    The wire protocol stores stages as ``{name: payload}``; this normalizes it to
    the persisted list-of-stage-records shape before extraction.
    """

    if not stages:
        return []
    normalized = [{"name": name, "payload": payload} for name, payload in stages.items()]
    return extract_retrieved_chunk_ids(normalized, stage_names=stage_names)


def resolve_relevant_chunk_ids(evidence_chunk_ids: Sequence[UUID | str]) -> list[str]:
    """Normalize gold evidence chunk identifiers to comparable string ids."""

    return [str(chunk_id) for chunk_id in evidence_chunk_ids if str(chunk_id)]
