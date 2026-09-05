import os
import pytest
from typing import Any
from urllib.parse import quote
from harness.environments.browser import BrowserEnvironment, PlaywrightBrowserBackend
from harness.schema import Action
from harness.html import prune_html


@pytest.mark.skipif(os.environ.get("BROWSER_TEST") != "1", reason="Opt-in real Chromium integration check")
def test_browser_tabs_scoped_elements_state_reader_and_stale_references() -> None:
    page_html = (
        "<title>Fixture</title><header><a href=\"#\">Unrelated menu</a></header>"
        "<main><h1>Product choices</h1><script>" + "unused;" * 4000 + "</script><button id=\"first\" onclick=\"this.style.display = `none`\">Hide first</button>"
        "<button onclick=\"document.body.dataset.clicked = `second`\">Choose second</button></main>"
    )
    url = "data:text/html," + quote(page_html)

    def read_state(page: Any) -> dict[str, Any]:
        return {"clicked": page.locator("body").get_attribute("data-clicked")}

    environment = BrowserEnvironment(
        PlaywrightBrowserBackend(observation_selector="main", state_reader=read_state, settle_ms=10)
    )
    try:
        observation, snapshot = environment.reset(options={"start_urls": [url, url]})
        assert len(observation.structured["tabs"]) == 2
        assert "heading \"Product choices\"" in observation.structured["accessibility"]["tree"]
        assert "button \"Choose second\"" in observation.structured["accessibility"]["tree"]
        pruned = prune_html(observation.structured["body"])
        assert "unused" not in pruned and "onclick" not in pruned
        assert "bid=\"1\"" in pruned and "Choose second" in pruned
        assert [element["name"] for element in observation.structured["accessibility"]["interactive_elements"]] == ["Hide first", "Choose second"]
        assert snapshot.state["task"] == {"clicked": None}
        environment.step(Action(kind="click", arguments={"target": "0"}))
        environment.step(Action(kind="click", arguments={"target": "0"}))
        assert environment.inspect()["task"]["clicked"] == "second"
        transition = environment.step(Action(kind="tab_focus", arguments={"index": 1}))
        assert transition.next_observation.structured["tabs"][1]["active"]
        assert environment.inspect()["task"]["clicked"] is None
        with pytest.raises(NotImplementedError):
            environment.restore(snapshot)
    finally:
        environment.close()
