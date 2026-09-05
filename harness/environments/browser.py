import importlib
import time
from copy import deepcopy
from typing import Any, Protocol, runtime_checkable
from collections.abc import Callable, Mapping
from tqdm import tqdm
from harness.interventions import CounterfactualRuntime
from harness.environments.base import (
    BackendHook,
    BackendHookPoint,
    BackendHookRegistry,
    BaseEnvironmentAdapter,
    EnvironmentCapability,
    RendererNeutralBackend
)
from harness.schema import Action, Event, Observation, Snapshot, Transition, VisualObservation


@runtime_checkable
class BrowserBackendProtocol(RendererNeutralBackend, Protocol):
    def register_response_interceptor(self, hook: BackendHook) -> None:
        ...

    def register_observation_editor(self, hook: BackendHook) -> None:
        ...


class MemoryBrowserBackend:
    capabilities = frozenset(
        {
            EnvironmentCapability.STRUCTURED_OBSERVATION,
            EnvironmentCapability.TEXT_OBSERVATION,
            EnvironmentCapability.VISUAL_OBSERVATION,
            EnvironmentCapability.RESPONSE_INTERCEPTION,
            EnvironmentCapability.OBSERVATION_INTERCEPTION,
            EnvironmentCapability.STATE_INSPECTION,
            EnvironmentCapability.SNAPSHOT_RESTORE,
            EnvironmentCapability.BROWSER_ACTION,
            EnvironmentCapability.NAVIGATION_RESPONSE,
            EnvironmentCapability.HTML_OBSERVATION,
            EnvironmentCapability.ACCESSIBILITY_OBSERVATION,
            EnvironmentCapability.GEOMETRY_OBSERVATION
        }
    )

    def __init__(
        self,
        pages: Mapping[str, Mapping[str, Any]] | None = None,
        initial_url: str = "about:blank",
        viewport: Mapping[str, int] | None = None
    ) -> None:
        self._pages = deepcopy(dict(pages or {}))
        self._initial_url = initial_url
        self._viewport = dict(viewport or {"width": 1280, "height": 720})
        self._step = 0
        self._state: dict[str, Any] = {}
        self._observation: Observation | None = None
        self._hooks = BackendHookRegistry()

    def reset(
        self,
        seed: int | None = None,
        options: Mapping[str, Any] | None = None
    ) -> tuple[Observation, Snapshot]:
        reset_options = dict(options or {})
        self._pages = deepcopy(reset_options.get("pages", self._pages))
        initial_url = reset_options.get("url", self._initial_url)
        state = {
            "url": initial_url,
            "history": [initial_url],
            "inputs": {},
            "last_action": None,
            "last_tool_result": None,
            "terminated": False,
            "truncated": False
        }
        self._state = self._hooks.apply_hooks(
            point=BackendHookPoint.RESET,
            value=state,
            step=0,
            metadata={"seed": seed}
        )
        self._step = 0
        self._observation = self._load_current_response()
        return self._observation, self.snapshot()

    def step(self, action: Action) -> Transition:
        action_step = self._step
        before_snapshot = self.snapshot()
        if action.kind == "navigate":
            self._state["url"] = action.arguments["url"]
            self._state["history"].append(action.arguments["url"])
        elif action.kind == "type":
            self._state["inputs"][action.arguments["target"]] = action.text or action.arguments.get("text", "")
        elif action.kind == "click":
            self._state["last_clicked"] = action.arguments["target"]
        elif action.kind == "tool":
            self._state["last_tool_result"] = self._hooks.apply_hooks(
                point=BackendHookPoint.TOOL_RESULT,
                value=action.arguments["result"],
                step=action_step,
                metadata={"tool": action.arguments.get("tool", "")}
            )
        elif action.kind == "finish":
            self._state["terminated"] = True
        self._state["last_action"] = action.model_dump(mode="python")
        self._state = self._hooks.apply_hooks(
            point=BackendHookPoint.STATE,
            value=self._state,
            step=action_step,
            metadata={"action_kind": action.kind}
        )
        self._step += 1
        self._observation = self._load_current_response()
        event = Event(
            sequence=action_step,
            step=action_step,
            kind=action.kind,
            actor_id="agent",
            payload=action.model_dump(mode="python"),
            metadata={"url": self._state["url"]}
        )
        self._observation = self._observation.model_copy(update={"events": [event]})
        after_snapshot = self.snapshot()
        return Transition(
            step=action_step,
            observation=before_snapshot.observation,
            action=action,
            next_observation=self._observation,
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
            reward=None,
            terminated=self._state["terminated"],
            truncated=self._state["truncated"],
            info={"backend": "browser", "url": self._state["url"]},
            interventions=[]
        )

    def inspect(self) -> Mapping[str, Any]:
        return deepcopy(self._state)

    def snapshot(self) -> Snapshot:
        return Snapshot(
            step=self._step,
            state=deepcopy(self._state),
            observation=deepcopy(self._observation),
            metadata={"backend": "browser", "viewport": deepcopy(self._viewport)}
        )

    def restore(self, snapshot: Snapshot) -> Observation:
        self._step = snapshot.step
        self._state = deepcopy(snapshot.state)
        self._viewport = deepcopy(snapshot.metadata.get("viewport", self._viewport))
        self._observation = deepcopy(snapshot.observation)
        return self._observation

    def register_hook(self, point: BackendHookPoint, hook: BackendHook) -> None:
        self._hooks.register_hook(point, hook)

    def register_response_interceptor(self, hook: BackendHook) -> None:
        self.register_hook(BackendHookPoint.NAVIGATION_RESPONSE, hook)

    def register_observation_editor(self, hook: BackendHook) -> None:
        self.register_hook(BackendHookPoint.OBSERVATION, hook)

    def close(self) -> None:
        return None

    def _load_current_response(self) -> Observation:
        url = self._state["url"]
        response = deepcopy(
            self._pages.get(
                url,
                {
                    "url": url,
                    "status": 200 if url == "about:blank" else 404,
                    "headers": {"content-type": "text/html"},
                    "body": "",
                    "text": "",
                    "screenshot": b"",
                    "accessibility": {},
                    "geometry": {},
                    "metadata": {}
                }
            )
        )
        response.setdefault("url", url)
        response.setdefault("status", 200)
        response.setdefault("headers", {"content-type": "text/html"})
        response.setdefault("body", "")
        response.setdefault("text", response["body"])
        response.setdefault("screenshot", b"")
        response.setdefault("accessibility", {})
        response.setdefault("geometry", {})
        response.setdefault("metadata", {})
        response = self._hooks.apply_hooks(
            point=BackendHookPoint.NAVIGATION_RESPONSE,
            value=response,
            step=self._step,
            metadata={"url": url}
        )
        return self._render(response)

    def _render(self, response: Mapping[str, Any]) -> Observation:
        visual = VisualObservation(
            data=response["screenshot"],
            media_type=response.get("media_type", "image/png"),
            width=self._viewport["width"],
            height=self._viewport["height"],
            metadata={"url": response["url"]}
        )
        observation = Observation(
            step=self._step,
            text=response["text"],
            structured={
                "url": response["url"],
                "status": response["status"],
                "headers": deepcopy(response["headers"]),
                "body": response["body"],
                "accessibility": deepcopy(response["accessibility"]),
                "geometry": deepcopy(response["geometry"]),
                "inputs": deepcopy(self._state["inputs"]),
                "tool_result": deepcopy(self._state["last_tool_result"])
            },
            visual=visual,
            events=[],
            metadata={"backend": "browser", **deepcopy(response["metadata"])}
        )
        return self._hooks.apply_hooks(
            point=BackendHookPoint.OBSERVATION,
            value=observation,
            step=self._step,
            metadata={"url": response["url"]}
        )


class PlaywrightBrowserBackend:
    capabilities = frozenset(
        {
            EnvironmentCapability.STRUCTURED_OBSERVATION,
            EnvironmentCapability.TEXT_OBSERVATION,
            EnvironmentCapability.VISUAL_OBSERVATION,
            EnvironmentCapability.RESPONSE_INTERCEPTION,
            EnvironmentCapability.OBSERVATION_INTERCEPTION,
            EnvironmentCapability.STATE_INSPECTION,
            EnvironmentCapability.BROWSER_ACTION,
            EnvironmentCapability.NAVIGATION_RESPONSE,
            EnvironmentCapability.HTML_OBSERVATION,
            EnvironmentCapability.ACCESSIBILITY_OBSERVATION,
            EnvironmentCapability.GEOMETRY_OBSERVATION
        }
    )

    def __init__(
        self,
        headless: bool = True,
        viewport: Mapping[str, int] | None = None,
        timeout_ms: int = 20000,
        settle_ms: int = 700,
        max_text_chars: int = 12000,
        max_interactive_elements: int = 100,
        setup: Callable[..., None] | None = None,
        state_reader: Callable[..., Mapping[str, Any]] | None = None,
        response_transform: Callable[..., Mapping[str, Any]] | None = None,
        observation_selector: str = "body"
    ) -> None:
        self._headless = headless
        self._viewport = dict(viewport or {"width": 1440, "height": 900})
        self._timeout_ms = timeout_ms
        self._settle_ms = settle_ms
        self._max_text_chars = max_text_chars
        self._max_interactive_elements = max_interactive_elements
        self._setup = setup
        self._state_reader = state_reader
        self._response_transform = response_transform
        self._observation_selector = observation_selector
        self._hooks = BackendHookRegistry()
        self._step = 0
        self._state: dict[str, Any] = {}
        self._observation: Observation | None = None
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None

    def reset(
        self,
        seed: int | None = None,
        options: Mapping[str, Any] | None = None
    ) -> tuple[Observation, Snapshot]:
        reset_options = dict(options or {})
        self.close()
        sync_api = importlib.import_module("playwright.sync_api")
        self._playwright = sync_api.sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self._headless)
        self._context = self._browser.new_context(
            viewport=self._viewport,
            locale=reset_options.get("locale", "en-US"),
            storage_state=reset_options.get("storage_state"),
            service_workers="block"
        )
        self._context.set_default_timeout(self._timeout_ms)
        self._context.route("**/*", self._intercept_route)
        self._page = self._context.new_page()
        start_urls = reset_options.get("start_urls") or [reset_options["url"]]
        initial_url = start_urls[0]
        self._step = 0
        self._state = self._hooks.apply_hooks(
            point=BackendHookPoint.RESET,
            value={
                "url": initial_url,
                "title": "",
                "history": [],
                "last_action": None,
                "last_action_error": None,
                "final_answer": None,
                "terminated": False,
                "truncated": False
            },
            step=0,
            metadata={"seed": seed}
        )
        if self._setup is not None:
            self._setup(self._context, reset_options, seed)
        for index, url in enumerate(tqdm(start_urls, desc="Opening tabs", disable=len(start_urls) == 1)):
            page = self._page if index == 0 else self._context.new_page()
            page.goto(
                url,
                wait_until=reset_options.get("wait_until", "domcontentloaded"),
                timeout=reset_options.get("timeout_ms", self._timeout_ms)
            )
        self._page.bring_to_front()
        self._settle()
        self._record_page_state()
        self._observation = self._observe_page()
        return self._observation, self.snapshot()

    def step(self, action: Action) -> Transition:
        action_step = self._step
        before_snapshot = self.snapshot()
        action_error = self._execute_action(action)
        self._state["last_action"] = action.model_dump(mode="python")
        self._state["last_action_error"] = action_error
        self._state = self._hooks.apply_hooks(
            point=BackendHookPoint.STATE,
            value=self._state,
            step=action_step,
            metadata={"action_kind": action.kind}
        )
        self._step += 1
        self._record_page_state()
        self._observation = self._observe_page(action_error=action_error)
        event = Event(
            sequence=action_step,
            step=action_step,
            kind=action.kind,
            actor_id=action.metadata.get("actor_id", "agent"),
            payload=action.model_dump(mode="python"),
            metadata={"url": self._state["url"], "error": action_error}
        )
        self._observation = self._observation.model_copy(update={"events": [event]})
        after_snapshot = self.snapshot()
        return Transition(
            step=action_step,
            observation=before_snapshot.observation,
            action=action,
            next_observation=self._observation,
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
            reward=None,
            terminated=self._state["terminated"],
            truncated=self._state["truncated"],
            info={
                "backend": "playwright",
                "url": self._state["url"],
                "title": self._state["title"],
                "action_error": action_error
            },
            interventions=[]
        )

    def inspect(self) -> Mapping[str, Any]:
        return deepcopy(self._state)

    def snapshot(self) -> Snapshot:
        return Snapshot(
            step=self._step,
            state=deepcopy(self._state),
            observation=deepcopy(self._observation),
            metadata={"backend": "playwright", "viewport": deepcopy(self._viewport), "restorable": False}
        )

    def restore(self, snapshot: Snapshot) -> Observation:
        raise NotImplementedError("Playwright snapshots are records; restoring requires application and browser state.")

    def register_hook(self, point: BackendHookPoint, hook: BackendHook) -> None:
        self._hooks.register_hook(point, hook)

    def register_response_interceptor(self, hook: BackendHook) -> None:
        self.register_hook(BackendHookPoint.NAVIGATION_RESPONSE, hook)

    def register_observation_editor(self, hook: BackendHook) -> None:
        self.register_hook(BackendHookPoint.OBSERVATION, hook)

    def close(self) -> None:
        if self._context is not None:
            self._context.close()
        if self._browser is not None:
            self._browser.close()
        if self._playwright is not None:
            self._playwright.stop()
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None

    def _intercept_route(self, route: Any, request: Any) -> None:
        if not request.is_navigation_request() or request.resource_type != "document":
            route.continue_()
            return
        response = route.fetch()
        content_type = response.headers.get("content-type", "")
        if "text/html" not in content_type:
            route.fulfill(response=response)
            return
        response_value = {
            "url": request.url,
            "status": response.status,
            "headers": dict(response.headers),
            "body": response.text(),
            "metadata": {}
        }
        if self._response_transform is not None:
            response_value = dict(self._response_transform(response_value))
        transformed = self._hooks.apply_hooks(
            point=BackendHookPoint.NAVIGATION_RESPONSE,
            value=response_value,
            step=self._step,
            metadata={"url": request.url}
        )
        route.fulfill(
            status=transformed["status"],
            headers={
                key: value for key, value in transformed["headers"].items()
                if key.lower() not in {"content-length", "content-encoding", "transfer-encoding"}
            },
            body=transformed["body"]
        )

    def _execute_action(self, action: Action) -> str | None:
        assert self._page is not None
        sync_api = importlib.import_module("playwright.sync_api")
        try:
            if action.kind == "click":
                self._locator(action.arguments["target"]).click()
            elif action.kind == "type":
                text = action.text or action.arguments.get("text", "")
                self._locator(action.arguments["target"]).fill(text)
            elif action.kind == "press":
                self._locator(action.arguments["target"]).press(action.arguments["key"])
            elif action.kind == "select":
                self._locator(action.arguments["target"]).select_option(action.arguments["value"])
            elif action.kind == "scroll":
                self._page.mouse.wheel(
                    int(action.arguments.get("delta_x", 0)),
                    int(action.arguments.get("delta_y", 650))
                )
            elif action.kind == "back":
                self._page.go_back(wait_until="domcontentloaded")
            elif action.kind == "forward":
                self._page.go_forward(wait_until="domcontentloaded")
            elif action.kind == "tab_focus":
                index = int(action.arguments["index"])
                assert 0 <= index < len(self._context.pages)
                self._page = self._context.pages[index]
                self._page.bring_to_front()
            elif action.kind == "keyboard_press":
                self._page.keyboard.press(action.arguments["key"])
            elif action.kind == "navigate":
                self._page.goto(action.arguments["url"], wait_until="domcontentloaded")
            elif action.kind == "wait":
                self._page.wait_for_timeout(int(action.arguments.get("milliseconds", 1000)))
            elif action.kind == "finish":
                self._state["final_answer"] = action.text or action.arguments.get("answer")
                self._state["terminated"] = True
            else:
                raise ValueError("Unknown browser action %s" % (action.kind,))
            if action.kind != "finish":
                self._settle()
            return None
        except sync_api.Error as error:
            return str(error)

    def _locator(self, target: str) -> Any:
        assert self._page is not None
        bid = target.removeprefix("BID:").removeprefix("BID")
        if bid.isdigit():
            return self._page.locator("[data-harness-bid=\"%s\"]" % (bid,)).first
        if target.startswith("e") and target[1:].isdigit():
            return self._page.locator("[data-harness-ref=\"%s\"]" % (target,)).first
        return self._page.locator(target).first

    def _settle(self) -> None:
        assert self._page is not None
        self._page.wait_for_timeout(self._settle_ms)

    def _record_page_state(self) -> None:
        assert self._page is not None
        url = self._page.url
        self._state["url"] = url
        self._state["title"] = self._page.title()
        if not self._state["history"] or self._state["history"][-1] != url:
            self._state["history"].append(url)
        if self._state_reader is not None:
            self._state["task"] = dict(self._state_reader(self._page))

    def _observe_page(self, action_error: str | None = None) -> Observation:
        assert self._page is not None
        elements = self._interactive_elements()
        region = self._page.locator(self._observation_selector)
        text = region.inner_text()[:self._max_text_chars]
        if action_error:
            text = "%s\n\nPrevious action error: %s" % (text, action_error)
        body = region.evaluate(
            """element => {
              const copy = element.cloneNode(true);
              const originals = [element, ...element.querySelectorAll("*")];
              const copies = [copy, ...copy.querySelectorAll("*")];
              originals.forEach((node, index) => {
                const target = copies[index];
                const style = getComputedStyle(node);
                if (style.display === "none" || style.visibility === "hidden") target.setAttribute("hidden", "");
                if (node instanceof HTMLInputElement) {
                  target.setAttribute("value", node.value);
                  target.toggleAttribute("checked", node.checked);
                } else if (node instanceof HTMLTextAreaElement) target.textContent = node.value;
                else if (node instanceof HTMLOptionElement) target.toggleAttribute("selected", node.selected);
              });
              return copy.outerHTML;
            }"""
        )
        screenshot = self._page.screenshot(type="png", full_page=False)
        geometry = {
            element["bid"]: element["geometry"]
            for element in elements
            if element["geometry"] is not None
        }
        observation = Observation(
            step=self._step,
            text=text,
            structured={
                "url": self._page.url,
                "title": self._page.title(),
                "body": body,
                "accessibility": {"tree": region.aria_snapshot(), "interactive_elements": elements},
                "geometry": geometry,
                "action_error": action_error,
                "tabs": [
                    {"index": index, "url": page.url, "active": page == self._page}
                    for index, page in enumerate(self._context.pages)
                ]
            },
            visual=VisualObservation(
                data=screenshot,
                media_type="image/png",
                width=self._viewport["width"],
                height=self._viewport["height"],
                metadata={"url": self._page.url, "title": self._page.title()}
            ),
            events=[],
            metadata={"backend": "playwright", "captured_at": time.time()}
        )
        return self._hooks.apply_hooks(
            point=BackendHookPoint.OBSERVATION,
            value=observation,
            step=self._step,
            metadata={"url": self._page.url}
        )

    def _interactive_elements(self) -> list[dict[str, Any]]:
        assert self._page is not None
        return self._page.evaluate(
            """
            ([limit, regionSelector]) => {
              const selector = "a,button,input,textarea,select,[role=button],[role=link],[contenteditable=true]";
              document.querySelectorAll("[data-harness-bid],[data-harness-ref]").forEach((element) => {
                element.removeAttribute("data-harness-bid");
                element.removeAttribute("data-harness-ref");
              });
              return [...document.querySelector(regionSelector).querySelectorAll(selector)].filter((element) => {
                const style = getComputedStyle(element);
                const rect = element.getBoundingClientRect();
                return style.visibility !== "hidden" && style.display !== "none" && rect.width > 0 && rect.height > 0 &&
                  rect.bottom > 0 && rect.right > 0 && rect.top < window.innerHeight && rect.left < window.innerWidth;
              }).slice(0, limit).map((element, index) => {
                const bid = `${index}`;
                element.setAttribute("data-harness-bid", bid);
                element.setAttribute("data-harness-ref", `e${index}`);
                const rect = element.getBoundingClientRect();
                const name = element.getAttribute("aria-label") || element.innerText || element.value || element.title || element.placeholder || "";
                return {
                  bid,
                  tag: element.tagName.toLowerCase(),
                  role: element.getAttribute("role") || element.tagName.toLowerCase(),
                  name: name.trim().replace(/\\s+/g, " ").slice(0, 180),
                  type: element.getAttribute("type"),
                  value: element.value || null,
                  geometry: {x: rect.x, y: rect.y, width: rect.width, height: rect.height}
                };
              });
            }
            """,
            [self._max_interactive_elements, self._observation_selector]
        )


class BrowserEnvironment(BaseEnvironmentAdapter):
    def __init__(
        self,
        backend: BrowserBackendProtocol | None = None,
        runtime: CounterfactualRuntime | None = None,
        episode_id: str = "",
        task_id: str = "",
        agent: str = "agent",
        condition: Mapping[str, Any] | None = None
    ) -> None:
        browser_backend = backend or MemoryBrowserBackend()
        super().__init__(
            backend=browser_backend,
            runtime=runtime,
            environment="browser",
            episode_id=episode_id,
            task_id=task_id,
            agent=agent,
            condition=condition
        )
