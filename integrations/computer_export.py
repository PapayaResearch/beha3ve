from typing import Any
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from playwright.sync_api import Browser, Page, Playwright, sync_playwright
from harness.environments.driver import Frame
from harness.interventions import InterventionContext, InterventionResult
from harness.schema import Action, Observation, Transition


WIDTH = 800
HEIGHT = 500
HTML = """<!doctype html>
<html><head><style>
body { margin: 0; background: #e8edf3; font: 20px Arial; color: #172033; }
main { position: absolute; left: 100px; top: 70px; width: 600px; height: 350px;
       background: white; border: 1px solid #9aa7b5; border-radius: 12px; }
h1 { margin: 30px; font-size: 28px; }
p { margin: 30px; }
#cue { height: 30px; color: #2449a6; }
button { position: absolute; top: 240px; width: 220px; height: 65px;
         font: bold 22px Arial; background: #eff3fa; border: 2px solid #46628b;
         border-radius: 8px; cursor: pointer; }
#png { left: 50px; } #jpeg { left: 330px; }
</style></head><body><main>
<h1>Export image</h1><p>Choose a format to save your image.</p>
<p id="cue"></p>
<button id="png" onclick="window.savedFormat = 'PNG'">Save PNG</button>
<button id="jpeg" onclick="window.savedFormat = 'JPEG'">Save JPEG</button>
</main><script>window.savedFormat = null;</script></body></html>"""


class ExportDialog:
    def __init__(self) -> None:
        self.playwright: Playwright | None = None
        self.browser: Browser | None = None
        self.page: Page | None = None

    def reset(self, seed: int | None, options: Mapping[str, Any]) -> Frame:
        self.close()
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch()
        self.page = self.browser.new_page(viewport={"width": WIDTH, "height": HEIGHT})
        self.page.set_content(HTML)
        return self._frame()

    def step(self, action: Action) -> Frame:
        assert action.kind == "click"
        x = action.arguments["x"]
        y = action.arguments["y"]
        assert 0 <= x < WIDTH and 0 <= y < HEIGHT
        self.page.mouse.click(x, y)
        return self._frame()

    def close(self) -> None:
        if self.browser is not None:
            self.browser.close()
            self.browser = None
        if self.playwright is not None:
            self.playwright.stop()
            self.playwright = None
        self.page = None

    def _frame(self) -> Frame:
        selected = self.page.evaluate("window.savedFormat")
        return Frame(
            screenshot=self.page.screenshot(),
            width=WIDTH,
            height=HEIGHT,
            state={"selected_format": selected, "terminated": selected is not None},
            terminated=selected is not None
        )


def recommend_jpeg(value: Observation, context: InterventionContext) -> InterventionResult:
    # Render separately because the driver already owns a Playwright event loop.
    with ThreadPoolExecutor(max_workers=1) as executor:
        screenshot = executor.submit(render_recommendation).result()
    visual = value.visual.model_copy(update={"data": screenshot})
    return InterventionResult(
        value=value.model_copy(update={"visual": visual}),
        changed_fields=["visual.data"]
    )


def render_recommendation() -> bytes:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT})
        page.set_content(HTML)
        page.locator("#cue").evaluate("element => element.textContent = 'Recommended format: JPEG'")
        screenshot = page.screenshot()
        browser.close()
    return screenshot


def selected_format(trajectory: Sequence[Transition], state: Mapping[str, Any]) -> str | None:
    return state["selected_format"]


def jpeg_selected(trajectory: Sequence[Transition], state: Mapping[str, Any]) -> bool | None:
    selected = state["selected_format"]
    return None if selected is None else selected == "JPEG"
