import re
from bs4 import BeautifulSoup, Comment


# Adapted from BrowserGym's utils/obs.py, revision 9e779f087de9a65668b6974d11f9ce9816026e96.
# Copyright 2024 ServiceNow; Apache-2.0. See docs/licenses/browsergym-Apache-2.0.txt.
# Local changes: strip presentation attributes, retain action IDs and form state,
# remove hidden markup, and preserve whitespace inside preformatted content.
def prune_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for comment in soup.find_all(string=lambda value: isinstance(value, Comment)):
        comment.extract()
    keep = {
        "bid", "role", "href", "alt", "title", "type", "name", "value", "placeholder",
        "checked", "selected", "disabled", "readonly", "required", "multiple", "for",
        "colspan", "rowspan", "open"
    }
    for tag in reversed(soup.find_all()):
        hidden_style = re.search(r"(?:display\s*:\s*none|visibility\s*:\s*hidden)", tag.get("style", ""), re.I)
        if tag.name in {"script", "style", "link", "meta", "noscript", "template"} or tag.has_attr("hidden") or hidden_style:
            tag.decompose()
            continue
        if tag.has_attr("data-harness-bid"):
            tag["bid"] = tag["data-harness-bid"]
        tag.attrs = {key: value for key, value in tag.attrs.items() if key in keep or key.startswith("aria-")}
        if tag.name in {"html", "body"} or (tag.name in {"div", "span", "i"} and not tag.attrs):
            tag.unwrap()
    for node in list(soup.find_all(string=True)):
        if not node.find_parent(["pre", "code", "textarea"]):
            node.replace_with(re.sub(r"\s+", " ", str(node)))
    return str(soup).strip()
