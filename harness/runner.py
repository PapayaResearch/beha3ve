from typing import Any, Protocol, runtime_checkable
from collections.abc import Mapping
from pydantic import BaseModel, ConfigDict, Field
from tqdm import tqdm
from harness.agents import Agent
from harness.evaluators import EvaluationResult, OutcomeEvaluator
from harness.schema import Action, Observation, Snapshot, Transition


@runtime_checkable
class Environment(Protocol):
    def reset(
        self,
        seed: int | None = None,
        options: Mapping[str, Any] | None = None
    ) -> tuple[Observation, Snapshot]:
        ...

    def step(self, action: Action) -> Transition:
        ...

    def inspect(self) -> Mapping[str, Any]:
        ...

    def observe(self, actor_id: str = "agent") -> Observation:
        ...

    def observe_for_actor(self, actor_id: str) -> Observation:
        ...

    def snapshot(self) -> Snapshot:
        ...

    def restore(self, snapshot: Snapshot) -> Observation:
        ...

    def close(self) -> None:
        ...


class EpisodeResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    episode_id: str
    seed: int
    initial_snapshot: Snapshot
    final_snapshot: Snapshot
    trajectory: list[Transition]
    evaluation: EvaluationResult
    metadata: dict[str, Any] = Field(default_factory=dict)


class EpisodeRunner:
    def __init__(
        self,
        environment: Environment,
        agent: Agent,
        evaluator: OutcomeEvaluator,
        max_steps: int = 50,
        progress: bool = True
    ) -> None:
        self.environment = environment
        self.agent = agent
        self.evaluator = evaluator
        self.max_steps = max_steps
        self.progress = progress
        assert self.max_steps > 0

    def run(
        self,
        episode_id: str,
        seed: int = 0,
        options: Mapping[str, Any] | None = None
    ) -> EpisodeResult:
        self.agent.reset(seed=seed)
        observation, initial_snapshot = self.environment.reset(
            seed=seed,
            options=options
        )
        trajectory = []
        for index in tqdm(
            range(self.max_steps),
            desc="episode %s" % (episode_id,),
            disable=not self.progress
        ):
            action = self.agent.act(observation)
            transition = self.environment.step(action)
            if index == self.max_steps - 1 and not (transition.terminated or transition.truncated):
                transition = transition.model_copy(
                    update={"truncated": True, "info": {**transition.info, "stop_reason": "max_steps"}}
                )
            trajectory.append(transition)
            observation = transition.next_observation
            if transition.terminated or transition.truncated:
                break
        final_snapshot = self.environment.snapshot()
        evaluation = self.evaluator.evaluate(
            trajectory=trajectory,
            state=self.environment.inspect()
        )
        return EpisodeResult(
            episode_id=episode_id,
            seed=seed,
            initial_snapshot=initial_snapshot,
            final_snapshot=final_snapshot,
            trajectory=trajectory,
            evaluation=evaluation,
            metadata={
                "max_steps": self.max_steps,
                "terminated": trajectory[-1].terminated,
                "truncated": trajectory[-1].truncated
            }
        )


class Turn(BaseModel):
    actor_id: str
    participant_id: str


class ScheduledEpisodeRunner:
    def __init__(
        self,
        environment: Environment,
        participants: Mapping[str, Agent],
        turns: list[Turn | Mapping[str, str]],
        evaluator: OutcomeEvaluator,
        progress: bool = True
    ) -> None:
        self.environment = environment
        self.participants = dict(participants)
        self.turns = [
            turn if isinstance(turn, Turn) else Turn.model_validate(turn)
            for turn in turns
        ]
        self.evaluator = evaluator
        self.progress = progress
        assert all(
            turn.participant_id in self.participants
            for turn in self.turns
        )

    def run(
        self,
        episode_id: str,
        seed: int = 0,
        options: Mapping[str, Any] | None = None
    ) -> EpisodeResult:
        assert self.turns
        for participant in self.participants.values():
            participant.reset(seed=seed)
        _, initial_snapshot = self.environment.reset(seed=seed, options=options)
        trajectory = []
        for turn in tqdm(
            self.turns,
            desc="episode %s" % (episode_id,),
            disable=not self.progress
        ):
            observation = self.environment.observe_for_actor(turn.actor_id)
            participant = self.participants[turn.participant_id]
            participant_action = participant.act(observation)
            action = participant_action.model_copy(
                update={
                    "metadata": {
                        **participant_action.metadata,
                        "actor_id": turn.actor_id
                    }
                }
            )
            transition = self.environment.step(action)
            trajectory.append(transition)
            if transition.terminated or transition.truncated:
                break
        final_snapshot = self.environment.snapshot()
        evaluation = self.evaluator.evaluate(
            trajectory=trajectory,
            state=self.environment.inspect()
        )
        return EpisodeResult(
            episode_id=episode_id,
            seed=seed,
            initial_snapshot=initial_snapshot,
            final_snapshot=final_snapshot,
            trajectory=trajectory,
            evaluation=evaluation,
            metadata={"turn_count": len(self.turns)}
        )
