import json
import time
import base64
import importlib
import hydra
from typing import Any, Protocol, runtime_checkable
from collections.abc import Callable, Mapping
from pydantic import BaseModel, Field
from harness.interventions import CounterfactualRuntime, InterventionContext, InterventionHook
from harness.schema import Action, InterventionApplication, Observation


class AgentSpec(BaseModel):
    id: str
    instructions: str = ""
    system_prompt: str = ""
    tools: list[dict[str, Any]] = Field(default_factory=list)
    memory_policy: dict[str, Any] = Field(default_factory=dict)
    scaffold: dict[str, Any] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)


@runtime_checkable
class Agent(Protocol):
    def reset(self, seed: int | None = None) -> None:
        ...

    def act(self, observation: Observation) -> Action:
        ...


class LiteLLMAgent:
    def __init__(
        self,
        spec: AgentSpec,
        chat_model_args: dict[str, Any],
        send_seed: bool = False,
        json_mode: bool = True,
        modality: str | list[str] = "pruned_html",
        vision_detail: str = "auto",
        max_observation_chars: int = 8000,
        completion: Callable[..., Any] | None = None,
        structured_actions: bool = False
    ) -> None:
        self.spec = spec
        self.chat_model_args = dict(chat_model_args)
        self.model = self.chat_model_args["model"]
        self.send_seed = send_seed
        self.json_mode = json_mode
        self.modalities = [modality] if isinstance(modality, str) else list(modality)
        assert self.modalities and set(self.modalities) <= {"pruned_html", "accessibility_tree", "screenshot", "text"}
        self.vision = "screenshot" in self.modalities
        self.vision_detail = vision_detail
        self.max_observation_chars = max_observation_chars
        self.structured_actions = structured_actions
        self.seed = 0
        self.request_index = 0
        self.messages: list[dict[str, Any]] = []
        self.action_history: list[dict[str, Any]] = []
        self.completion = completion or importlib.import_module("litellm").completion

    def reset(self, seed: int | None = None) -> None:
        self.seed = seed or 0
        self.request_index = 0
        self.action_history = []
        self.messages = [
            {
                "role": "system",
                "content": self._system_prompt()
            }
        ]

    def act(self, observation: Observation) -> Action:
        user_message = {
            "role": "user",
            "content": self._observation_content(observation)
        }
        request_messages = [*self.messages, user_message]
        request_started = time.monotonic()
        request = {key: value for key, value in self.chat_model_args.items() if value is not None}
        request["messages"] = request_messages
        if self.send_seed:
            request["seed"] = self.seed + self.request_index
        if self.json_mode:
            request["response_format"] = self._response_format(observation)
        response = self.completion(**request)
        latency_seconds = time.monotonic() - request_started
        response_message = response.choices[0].message
        content = response_message.content
        assert isinstance(content, str)
        action = Action.model_validate(json.loads(content))
        allowed_action_kinds = {tool["kind"] for tool in self.spec.tools}
        assert not allowed_action_kinds or action.kind in allowed_action_kinds
        action.metadata.update(
            {
                "llm": {
                    "model": getattr(response, "model", self.model),
                    "response_id": getattr(response, "id", None),
                    "request_index": self.request_index,
                    "seed": request.get("seed"),
                    "latency_seconds": latency_seconds,
                    "messages": self._trace_messages(request_messages),
                    "observation_modalities": self.modalities,
                    "observation_text_limit": self.max_observation_chars,
                    "assistant_content": content,
                    "reasoning_content": getattr(response_message, "reasoning_content", None),
                    "thinking_blocks": self._portable(getattr(response_message, "thinking_blocks", None)),
                    "usage": self._portable(getattr(response, "usage", None))
                }
            }
        )
        self.action_history.append(
            {
                "step": observation.step,
                "kind": action.kind,
                "arguments": action.arguments,
                "text": action.text
            }
        )
        retain_turns = int(self.spec.memory_policy.get("retain_turns", 20))
        self.action_history = self.action_history[-retain_turns:]
        retain_observations = int(self.spec.memory_policy.get("retain_observations", 0))
        if retain_observations:
            self.messages.extend(
                [
                    {"role": "user", "content": self._observation_text(observation, include_history=False)},
                    {"role": "assistant", "content": content}
                ]
            )
            self.messages = [self.messages[0], *self.messages[1:][-2 * retain_observations:]]
        self.request_index += 1
        return action

    def _system_prompt(self) -> str:
        prompt_parts = [
            "You are an autonomous LLM agent acting in an interactive environment.",
            self.spec.system_prompt,
            "Task: %s" % (self.spec.instructions,),
            "Available actions:\n%s" % (self._action_catalog(),),
            (
                "Return exactly one JSON object with keys kind, arguments, and text. "
                "Use null for text when the action has no text. For browser actions using element IDs, "
                "copy the exact string shown after bid= into arguments.target. Do not add BID, punctuation, "
                "or CSS syntax. Do not return markdown."
            )
        ]
        return "\n\n".join(part for part in prompt_parts if part)

    def _response_format(self, observation: Observation) -> dict[str, Any]:
        if not self.structured_actions:
            return {"type": "json_object"}
        elements = observation.structured.get("accessibility", {}).get("interactive_elements", [])
        targets = [str(element["bid"]) for element in elements]
        argument_schemas = []
        for tool in self.spec.tools:
            properties = {}
            for name, example in tool.get("arguments", {}).items():
                if name == "target" and targets:
                    properties[name] = {"type": "string", "enum": targets}
                else:
                    kind = {bool: "boolean", int: "integer", float: "number", str: "string"}[type(example)]
                    properties[name] = {"type": kind}
            schema = {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}
            if schema not in argument_schemas:
                argument_schemas.append(schema)
        assert argument_schemas
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "action",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string", "enum": [tool["kind"] for tool in self.spec.tools]},
                        "arguments": {"anyOf": argument_schemas},
                        "text": {"type": ["string", "null"]}
                    },
                    "required": ["kind", "arguments", "text"],
                    "additionalProperties": False
                }
            }
        }

    def _observation_content(self, observation: Observation) -> str | list[dict[str, Any]]:
        observation_text = self._observation_text(observation)
        if not self.vision:
            return observation_text
        assert observation.visual is not None and observation.visual.data, "Screenshot modality requires a visual observation"
        encoded = base64.b64encode(observation.visual.data).decode("ascii")
        return [
            {
                "type": "text",
                "text": observation_text
            },
            {
                "type": "image_url",
                "image_url": {
                    "url": "data:%s;base64,%s" % (
                        observation.visual.media_type,
                        encoded
                    ),
                    "detail": self.vision_detail
                }
            }
        ]

    def _action_catalog(self) -> str:
        lines = []
        for tool in self.spec.tools:
            arguments = ", ".join(
                "%s=%s" % (name, value)
                for name, value in tool.get("arguments", {}).items()
            )
            signature = "%s(%s)" % (tool["kind"], arguments)
            lines.append("- %s: %s" % (signature, tool.get("description", "")))
        return "\n".join(lines) or "- No named actions were provided."

    def _observation_text(self, observation: Observation, include_history: bool = True) -> str:
        structured = observation.structured
        accessibility = structured.get("accessibility", {})
        elements = accessibility.get("interactive_elements", [])
        element_lines = []
        for element in elements:
            bid = element.get("bid") or element.get("ref")
            name = element.get("name") or "unnamed"
            value = element.get("value")
            value_text = " value=%s" % (json.dumps(value),) if value is not None else ""
            element_lines.append(
                "[bid=%s] %s %s%s" % (
                    bid,
                    element.get("role", element.get("tag", "element")),
                    json.dumps(name),
                    value_text
                )
            )
        sections = [
            "Current observation",
            "Step: %s" % (observation.step,),
            "URL: %s" % (structured.get("url", ""),),
            "Title: %s" % (structured.get("title", ""),)
        ]
        if "pruned_html" in self.modalities:
            from harness.html import prune_html
            assert "body" in structured, "Pruned HTML modality requires a browser HTML observation"
            sections.append("Pruned HTML:\n%s" % (prune_html(structured["body"]),))
        if "accessibility_tree" in self.modalities:
            assert "tree" in accessibility, "Accessibility tree modality requires an accessibility snapshot"
            sections.append("Accessibility tree:\n%s" % (accessibility["tree"],))
        if "text" in self.modalities:
            sections.append("Visible text:\n%s" % ((observation.text or "No visible text")[:self.max_observation_chars // 2],))
            context = {
                key: value for key, value in structured.items()
                if key not in {"url", "title", "body", "accessibility", "geometry", "action_error", "tabs"}
            }
            if context:
                sections.append("Environment context:\n%s" % (json.dumps(context, default=str)[:self.max_observation_chars // 6],))
        if set(self.modalities) & {"text", "accessibility_tree"}:
            sections.append("Interactive elements:\n%s" % (("\n".join(element_lines) or "None")[:self.max_observation_chars // 3],))
        if structured.get("tabs"):
            sections.insert(4, "Tabs: %s" % (json.dumps(structured["tabs"]),))
        action_error = structured.get("action_error")
        if action_error:
            sections.append("Previous action error: %s" % (action_error,))
        if include_history and self.action_history:
            history = [
                "%s. %s arguments=%s text=%s" % (
                    item["step"],
                    item["kind"],
                    json.dumps(item["arguments"], sort_keys=True),
                    json.dumps(item["text"])
                )
                for item in self.action_history
            ]
            sections.append("Recent actions:\n%s" % ("\n".join(history),))
        return "\n\n".join(sections)[:self.max_observation_chars]

    def _portable(self, value: Any) -> Any:
        if value is None:
            return None
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        if isinstance(value, Mapping):
            return dict(value)
        return value

    def _trace_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        traced_messages = []
        for message in messages:
            content = message["content"]
            if isinstance(content, list):
                content = [
                    item
                    if item["type"] == "text"
                    else {
                        "type": "image_url",
                        "image_url": {"artifact": "observation.visual"}
                    }
                    for item in content
                ]
            traced_messages.append(
                {
                    "role": message["role"],
                    "content": content
                }
            )
        return traced_messages


def build_agent(spec: AgentSpec) -> Agent:
    scaffold = dict(spec.scaffold)
    accepts_spec = scaffold.pop("accepts_spec", True)
    if accepts_spec:
        agent = hydra.utils.instantiate(
            scaffold,
            spec=spec,
            **spec.config
        )
    else:
        agent = hydra.utils.instantiate(scaffold, **spec.config)
    assert hasattr(agent, "reset")
    assert hasattr(agent, "act")
    return agent


def edit_agent_spec(
    spec: AgentSpec,
    runtime: CounterfactualRuntime,
    episode_id: str,
    task_id: str,
    seed: int | None = None,
    condition: Mapping[str, Any] | None = None
) -> tuple[AgentSpec, list[InterventionApplication]]:
    edited, applications = runtime.apply(
        hook=InterventionHook.AGENT_BUILD,
        value=spec,
        context=InterventionContext(
            episode_id=episode_id,
            step=0,
            environment="agent",
            agent=spec.id,
            task_id=task_id,
            seed=seed,
            metadata=dict(condition or {})
        )
    )
    return AgentSpec.model_validate(edited), applications
