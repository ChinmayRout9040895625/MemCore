"""SDK-side response models (thin wrappers over domain models)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from memcore.domain.models import ScoredMemory

_TERMINAL_STATES = frozenset({"succeeded", "failed"})


class Job(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    state: str

    @property
    def done(self) -> bool:
        return self.state in _TERMINAL_STATES


class RecallOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    results: list[ScoredMemory]
    context: str | None = None
    context_tokens: int | None = None
