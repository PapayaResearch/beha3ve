from typing import Any
from collections.abc import Mapping
from harness.interventions import InterventionContext, InterventionResult


def inject_html_banner(
    value: Mapping[str, Any],
    context: InterventionContext,
    html: str
) -> InterventionResult:
    body = value["body"]
    marker = "</body>"
    edited_body = body.replace(marker, "%s%s" % (html, marker), 1)
    if edited_body == body:
        edited_body = "%s%s" % (html, body)
    return InterventionResult(
        value={**value, "body": edited_body},
        changed_fields=["body"],
        metadata={"url": context.metadata.get("url"), "operation": "inject_html_banner"}
    )
