from copy import deepcopy
from typing import Any
from collections.abc import Mapping, Sequence
from urllib.parse import urlsplit
from bs4 import BeautifulSoup
from harness.evaluators import Outcome
from harness.interventions import InterventionContext, InterventionResult
from harness.schema import Transition


def product_response(
    value: Mapping[str, Any],
    context: InterventionContext,
    operation: str,
    value_override: str | float | int
) -> InterventionResult:
    del context
    soup = BeautifulSoup(value["body"], "html.parser")
    assert soup.select_one("#product_addtocart_form"), "Expected a Magento product page: %s" % (value["url"],)
    if operation in {"subtitle", "stock"}:
        selector = ".page-title-wrapper.product" if operation == "subtitle" else ".product-info-stock-sku"
        anchor = soup.select_one(selector)
        assert anchor is not None, "Missing nudge anchor: %s" % (selector,)
        tag = soup.new_tag("h2" if operation == "subtitle" else "span")
        tag["class"] = "product-title-details" if operation == "subtitle" else "product-stock-details"
        tag["style"] = (
            "display:inline-block;padding:4px 8px;border:1px solid rgb(30,109,182);"
            "border-radius:12px;color:rgb(30,109,182);font-size:2em;"
            if operation == "subtitle" else
            "display:inline-block;padding:4px 8px;margin-top:10px;border:1px solid rgb(30,109,182);"
            "border-radius:2px;color:rgb(30,109,182);font-size:0.9em;"
        )
        tag.string = str(value_override)
        anchor.insert_after(tag)
    elif operation == "price":
        wrapper = soup.select_one(".product-info-main .price-wrapper")
        assert wrapper is not None and wrapper.select_one(".price") is not None
        wrapper["data-price-amount"] = "%.2f" % (float(value_override),)
        wrapper.select_one(".price").string = "$%.2f" % (float(value_override),)
    elif operation == "review_count":
        count = soup.select_one("[itemprop=reviewCount]")
        assert count is not None
        count.string = str(int(value_override))
        counter = soup.select_one(".data.item.title .counter")
        if counter is not None:
            counter.string = str(int(value_override))
    else:
        raise ValueError("Unsupported ABxLab operation: %s" % (operation,))
    edited = deepcopy(dict(value))
    edited["body"] = str(soup)
    return InterventionResult(
        value=edited,
        changed_fields=["body"],
        metadata={"url": value["url"], "operation": operation, "value": value_override}
    )


def explicit_rating(value: Mapping[str, Any]) -> Mapping[str, Any]:
    soup = BeautifulSoup(value["body"], "html.parser")
    rating = soup.select_one(".product-info-main .rating-result")
    if rating is None:
        return value
    tag = soup.new_tag("span", attrs={"class": "product-rating-details"})
    tag.string = "Rating: %s" % (rating["title"],)
    rating.parent.insert_after(tag)
    return {**value, "body": str(soup)}


def shopping_state(page: Any) -> Mapping[str, Any]:
    """Read the cart using the browser's isolated guest session; never infer it from the model's answer."""
    response = page.context.request.get("%s://%s/customer/section/load/?sections=cart" % (
        urlsplit(page.url).scheme,
        urlsplit(page.url).netloc
    ))
    assert response.ok, "Cart state request failed: %s" % (response.status,)
    cart = response.json()["cart"]
    return {
        "cart_count": cart.get("summary_count", 0),
        "cart_items": [
            {key: item.get(key) for key in ("product_id", "product_name", "product_url", "qty")}
            for item in cart.get("items", [])
        ]
    }


def cart_choice(
    trajectory: Sequence[Transition],
    state: Mapping[str, Any],
    product_urls: Sequence[str]
) -> Outcome:
    del trajectory
    product_paths = [urlsplit(url).path.lstrip("/") for url in product_urls]
    items = state["task"]["cart_items"]
    chosen = [urlsplit(item["product_url"]).path.lstrip("/") for item in items]
    choice = product_paths.index(chosen[0]) if len(chosen) == 1 and chosen[0] in product_paths else None
    return Outcome(id="cart_choice", value=choice, evidence=[{"cart_items": items}])


def valid_choice(
    trajectory: Sequence[Transition],
    state: Mapping[str, Any],
    product_urls: Sequence[str]
) -> bool:
    return cart_choice(trajectory, state, product_urls).value is not None


def target_chosen(
    trajectory: Sequence[Transition],
    state: Mapping[str, Any],
    product_urls: Sequence[str],
    target_index: int
) -> int | None:
    choice = cart_choice(trajectory, state, product_urls).value
    return None if choice is None else int(choice == target_index)


def inspected_both(
    trajectory: Sequence[Transition],
    state: Mapping[str, Any],
    product_urls: Sequence[str]
) -> bool:
    del state
    observed = set()
    for transition in trajectory:
        observed.add(urlsplit(transition.observation.structured["url"]).path.lstrip("/"))
        if transition.after_snapshot.state["task"]["cart_count"]:
            break
    return {urlsplit(url).path.lstrip("/") for url in product_urls} <= observed
