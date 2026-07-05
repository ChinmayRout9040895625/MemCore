"""Evaluation datasets — deterministic, token-overlap engineered.

The synthetic dataset is hand-written so that each query shares distinctive
tokens with exactly its target record and only generic tokens with
distractors. That makes it meaningful under the deterministic hashing
embedder (token-based) as well as real embedding models.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvalRecord(_Base):
    key: str
    content: str
    age_days: float = Field(default=0.0, ge=0.0)
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    reinforce_count: int = Field(default=0, ge=0)
    tags: list[str] = Field(default_factory=list)


class EvalCase(_Base):
    query: str
    relevant_keys: list[str]


class EvalDataset(_Base):
    name: str
    records: list[EvalRecord]
    cases: list[EvalCase]


def synthetic_dataset() -> EvalDataset:
    """12 semantic facts, 8 queries with known targets, 4 pure distractors."""
    records = [
        EvalRecord(key="editor-pref",
                   content="Chinmay prefers dark mode themes in the vim editor."),
        EvalRecord(key="editor-font",
                   content="The vim editor font is set to fira code."),
        EvalRecord(key="dog-name",
                   content="Chinmay's dog is named Bruno and likes long walks."),
        EvalRecord(key="dog-vet",
                   content="Bruno the dog visits the vet clinic every march."),
        EvalRecord(key="city-home",
                   content="Chinmay lives in Pune near the river."),
        EvalRecord(key="city-work",
                   content="The office is in Mumbai near the harbour."),
        EvalRecord(key="lang-pref",
                   content="Chinmay writes most backend services in Python."),
        EvalRecord(key="lang-legacy",
                   content="An old billing service is written in Java."),
        EvalRecord(key="coffee",
                   content="Chinmay drinks black coffee without sugar every morning."),
        EvalRecord(key="pantry",
                   content="The office pantry stocks green tea and sugar."),
        EvalRecord(key="meeting",
                   content="The weekly team meeting happens on tuesday morning."),
        EvalRecord(key="hobby",
                   content="Chinmay plays chess online on weekend mornings."),
    ]
    cases = [
        EvalCase(query="which editor theme does chinmay prefer",
                 relevant_keys=["editor-pref"]),
        EvalCase(query="what font is the vim editor set to",
                 relevant_keys=["editor-font"]),
        EvalCase(query="what is the name of chinmay's dog",
                 relevant_keys=["dog-name"]),
        EvalCase(query="where does chinmay live",
                 relevant_keys=["city-home"]),
        EvalCase(query="which language does chinmay write backend services in",
                 relevant_keys=["lang-pref"]),
        EvalCase(query="how does chinmay drink his coffee",
                 relevant_keys=["coffee"]),
        EvalCase(query="when does the weekly team meeting happen",
                 relevant_keys=["meeting"]),
        EvalCase(query="what does chinmay play on weekend mornings",
                 relevant_keys=["hobby"]),
    ]
    return EvalDataset(name="synthetic-v1", records=records, cases=cases)
