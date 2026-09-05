import json
import struct
from typing import Any
from collections.abc import Callable, Mapping, Sequence
from urllib.request import Request, urlopen
from harness.environments.driver import Frame
from harness.schema import Action


class OSWorldClient:
    def __init__(self, endpoint: str, timeout: float = 60.0) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.timeout = timeout

    def execute(self, command: Sequence[str]) -> Mapping[str, Any]:
        request = Request(
            "%s/execute" % (self.endpoint,),
            data=json.dumps({"command": list(command), "shell": False}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urlopen(request, timeout=self.timeout) as response:
            result = json.load(response)
        assert result["returncode"] == 0, result["error"]
        return result

    def screenshot(self) -> bytes:
        with urlopen("%s/screenshot" % (self.endpoint,), timeout=self.timeout) as response:
            return response.read()


class OSWorldServerDriver:
    def __init__(
        self,
        endpoint: str,
        setup: Callable[[OSWorldClient, Mapping[str, Any]], None],
        state_reader: Callable[[OSWorldClient, Mapping[str, Any]], Mapping[str, Any]],
        max_steps: int,
        settle_seconds: float = 0.7
    ) -> None:
        self.client = OSWorldClient(endpoint)
        self.setup = setup
        self.state_reader = state_reader
        self.max_steps = max_steps
        self.settle_seconds = settle_seconds
        self.options: dict[str, Any] = {}
        self.steps = 0

    def reset(self, seed: int | None, options: Mapping[str, Any]) -> Frame:
        self.options = dict(options)
        self.steps = 0
        self.setup(self.client, self.options)
        return self._frame()

    def step(self, action: Action) -> Frame:
        code = desktop_action(action)
        self.client.execute(["python", "-c", "import pyautogui, time; %s; time.sleep(%s)" % (code, self.settle_seconds)])
        self.steps += 1
        return self._frame(
            terminated=action.kind in {"DONE", "FAIL"},
            truncated=self.steps >= self.max_steps and action.kind not in {"DONE", "FAIL"}
        )

    def close(self) -> None:
        # This connection borrows an existing desktop; its owner manages the VM.
        return None

    def _frame(self, terminated: bool = False, truncated: bool = False) -> Frame:
        state = dict(self.state_reader(self.client, self.options))
        screenshot = self.client.screenshot()
        assert screenshot.startswith(b"\x89PNG\r\n\x1a\n")
        width, height = struct.unpack(">II", screenshot[16:24])
        return Frame(
            screenshot=screenshot,
            width=width,
            height=height,
            state=state,
            terminated=terminated,
            truncated=truncated
        )


def desktop_action(action: Action) -> str:
    arguments = action.arguments
    if action.kind in {"CLICK", "DOUBLE_CLICK", "RIGHT_CLICK"}:
        method = {"CLICK": "click", "DOUBLE_CLICK": "doubleClick", "RIGHT_CLICK": "rightClick"}[action.kind]
        return "pyautogui.%s(%s, %s)" % (method, int(arguments["x"]), int(arguments["y"]))
    if action.kind == "TYPING":
        return "pyautogui.write(%s, interval=0.03)" % (json.dumps(action.text),)
    if action.kind == "PRESS":
        return "pyautogui.press(%s)" % (json.dumps(arguments["key"]),)
    if action.kind == "HOTKEY":
        keys = ", ".join(json.dumps(key) for key in arguments["keys"].split("+"))
        return "pyautogui.hotkey(%s)" % (keys,)
    if action.kind == "SCROLL":
        return "pyautogui.scroll(%s)" % (int(arguments["dy"]),)
    assert action.kind in {"WAIT", "DONE", "FAIL"}, "Unsupported action: %s" % (action.kind,)
    return "time.sleep(0.5)"
