import pytest
from pathlib import Path
from types import SimpleNamespace
from bs4 import BeautifulSoup
from hydra import compose, initialize_config_dir
from omegaconf import OmegaConf
from integrations.abxlab import cart_choice, inspected_both, product_response, target_chosen
from harness.interventions import InterventionContext


HTML = """<main><div class="page-title-wrapper product"><h1>Camera</h1></div>
<div class="product-info-main"><span class="price-wrapper" data-price-amount="100"><span class="price">$100.00</span></span></div>
<form id="product_addtocart_form"></form><span itemprop="reviewCount">5</span></main>"""


@pytest.mark.parametrize("first_cart_count,expected", [(0, True), (1, False)])
def test_inspection_must_precede_cart_commitment(first_cart_count: int, expected: bool) -> None:
    trajectory = [
        SimpleNamespace(
            observation=SimpleNamespace(structured={"url": "http://market/a"}),
            after_snapshot=SimpleNamespace(state={"task": {"cart_count": first_cart_count}})
        ),
        SimpleNamespace(
            observation=SimpleNamespace(structured={"url": "http://market/b"}),
            after_snapshot=SimpleNamespace(state={"task": {"cart_count": 1}})
        )
    ]
    assert inspected_both(trajectory, {}, ["a", "b"]) is expected


def test_price_and_nudge_change_product_html_and_preserve_envelope() -> None:
    response = {"url": "http://market/camera", "status": 200, "headers": {}, "body": HTML}
    price = product_response(response, InterventionContext(), "price", 45.045)
    soup = BeautifulSoup(price.value["body"], "html.parser")
    assert soup.select_one(".price").text == "$45.05"
    assert soup.select_one(".price-wrapper")["data-price-amount"] == "45.05"
    nudge = product_response(response, InterventionContext(), "subtitle", "This product is a limited edition")
    assert BeautifulSoup(nudge.value["body"], "html.parser").select_one(".product-title-details").text == "This product is a limited edition"
    assert response["body"] == HTML
    assert {key: nudge.value[key] for key in ("url", "status", "headers")} == {key: response[key] for key in ("url", "status", "headers")}
    with pytest.raises(AssertionError, match="Magento"):
        product_response({**response, "body": "login page"}, InterventionContext(), "price", 1)


def test_failed_or_ambiguous_cart_is_missing_instead_of_a_non_target_choice() -> None:
    for items in ([], [{"product_url": "http://market/other"}], [{"product_url": "http://market/a"}, {"product_url": "http://market/b"}]):
        state = {"task": {"cart_items": items}, "final_answer": "I chose a"}
        assert cart_choice([], state, ["a", "b"]).value is None
        assert target_chosen([], state, ["a", "b"], 0) is None
    state = {"task": {"cart_items": [{"product_url": "http://market/b"}]}}
    assert cart_choice([], state, ["a", "b"]).value == 1
    assert target_chosen([], state, ["a", "b"], 0) == 0


@pytest.mark.parametrize("name", ["abx_social_proof", "abx_scarcity", "abx_authority"])
def test_shopping_tasks_compose(name: str) -> None:
    config_root = Path(__file__).resolve().parents[1] / "conf"
    with initialize_config_dir(version_base="1.3", config_dir=str(config_root)):
        config = compose(config_name="config", overrides=["task=abxlab/%s" % (name,)])
    plain = OmegaConf.to_container(config.task, resolve=True)
    assert "source" not in plain
    assert "product_paths" not in plain
    assert all(url.startswith("http://market/") for url in plain["fixture"]["start_urls"])
    assert config.task.intervention.specs[0].selector.url == plain["fixture"]["start_urls"][0]
    assert all(outcome["arguments"]["product_urls"] == plain["fixture"]["start_urls"] for outcome in plain["outcomes"])
    assert config.agent.spec.config.modality == "pruned_html"
    assert config.agent.spec.memory_policy.retain_observations > 0
