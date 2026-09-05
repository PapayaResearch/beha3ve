import math
import fnmatch
from typing import Any
from collections.abc import Mapping, Sequence
from harness.schema import Transition


def action_count(
    trajectory: Sequence[Transition],
    state: Mapping[str, Any]
) -> int:
    del state
    return len(trajectory)


def terminated(
    trajectory: Sequence[Transition],
    state: Mapping[str, Any]
) -> bool:
    del trajectory
    return bool(state["terminated"])


def pages_visited(
    trajectory: Sequence[Transition],
    state: Mapping[str, Any]
) -> int:
    del trajectory
    return len(state["history"])


def answer_submitted(
    trajectory: Sequence[Transition],
    state: Mapping[str, Any]
) -> bool:
    del trajectory
    return bool(state.get("final_answer"))


def reached_url(
    trajectory: Sequence[Transition],
    state: Mapping[str, Any],
    pattern: str
) -> bool:
    del trajectory
    needle = pattern.casefold().replace("_", " ")
    pages = [*state["history"], state.get("title", "")]
    return any(
        fnmatch.fnmatch(page.casefold().replace("_", " "), "*%s*" % (needle,))
        for page in pages
    )


def delivered_message_count(
    trajectory: Sequence[Transition],
    state: Mapping[str, Any]
) -> int:
    del trajectory
    messages = [
        message
        for actor in state["actors"].values()
        for message in actor["messages"]
    ]
    return len(
        {
            (
                message["sender"],
                message["recipient"],
                message["text"]
            )
            for message in messages
        }
    )


def shared_sequence_length(
    trajectory: Sequence[Transition],
    state: Mapping[str, Any]
) -> int:
    del trajectory
    return len(state["shared"]["sequence"])


def blocked_action_count(
    trajectory: Sequence[Transition],
    state: Mapping[str, Any]
) -> int:
    del trajectory
    return sum(record["blocked"] for record in state["provenance"])


def realized_action_count(
    trajectory: Sequence[Transition],
    state: Mapping[str, Any]
) -> int:
    del trajectory
    return sum(record["realized"] for record in state["provenance"])


def pointer_distance(
    trajectory: Sequence[Transition],
    state: Mapping[str, Any],
    target_x: int,
    target_y: int
) -> float:
    del trajectory
    x_distance = state["cursor"]["x"] - target_x
    y_distance = state["cursor"]["y"] - target_y
    return math.sqrt(x_distance ** 2 + y_distance ** 2)
