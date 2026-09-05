from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class HarnessModel(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)


class Event(HarnessModel):
    sequence: int
    step: int
    kind: str
    actor_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class VisualObservation(HarnessModel):
    data: bytes
    media_type: str = "image/png"
    width: int | None = None
    height: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Observation(HarnessModel):
    step: int
    text: str | None = None
    structured: dict[str, Any] = Field(default_factory=dict)
    visual: VisualObservation | None = None
    events: list[Event] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Action(HarnessModel):
    kind: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    text: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Snapshot(HarnessModel):
    step: int
    state: dict[str, Any]
    observation: Observation | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class InterventionApplication(HarnessModel):
    intervention_id: str
    factor: str
    level: str
    scope: str
    target: str
    modality: str
    hook: str
    order: int
    function: str
    seed: int | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    selector: dict[str, Any] = Field(default_factory=dict)
    changed_fields: list[str] = Field(default_factory=list)
    before_hash: str
    after_hash: str
    held_fixed_hash: str | None = None
    expected_relation: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PolicyDecision(HarnessModel):
    allowed: bool
    rule_id: str
    reason: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class Transition(HarnessModel):
    step: int
    observation: Observation | None
    action: Action
    next_observation: Observation
    before_snapshot: Snapshot
    after_snapshot: Snapshot
    reward: float | None = None
    terminated: bool = False
    truncated: bool = False
    info: dict[str, Any] = Field(default_factory=dict)
    interventions: list[InterventionApplication] = Field(default_factory=list)
