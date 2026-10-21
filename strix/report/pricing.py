"""LiteLLM model-name resolution for local cost estimates."""

from __future__ import annotations

from functools import lru_cache
from typing import Any, cast


# Pricing a model from these providers makes LiteLLM authenticate interactively
# (github_copilot starts a device-code login and polls GitHub until it succeeds),
# so a cost-map lookup must never resolve to them.
INTERACTIVE_AUTH_PROVIDERS = frozenset({"github_copilot"})


@lru_cache(maxsize=512)
def resolve_litellm_model(model: str) -> str | None:
    """Return a provider-qualified model name that LiteLLM can price."""
    try:
        import litellm

        normalized = model.strip()
        for prefix in ("litellm/", "any-llm/", "openai/"):
            if normalized.startswith(prefix):
                normalized = normalized.removeprefix(prefix)
                break
        if not normalized:
            return None

        model_cost = cast(
            "dict[str, dict[str, Any]]",
            getattr(litellm, "model_cost"),  # noqa: B009
        )
        resolved = _resolve_in_cost_map(normalized, model_cost)
    except Exception:  # noqa: BLE001
        return None
    if resolved is None or resolved.split("/", 1)[0] in INTERACTIVE_AUTH_PROVIDERS:
        return None
    return resolved


def _resolve_in_cost_map(normalized: str, model_cost: dict[str, dict[str, Any]]) -> str | None:
    bare_entry = model_cost.get(normalized)
    if "/" not in normalized and isinstance(bare_entry, dict):
        provider = bare_entry.get("litellm_provider")
        if isinstance(provider, str) and provider:
            return f"{provider}/{normalized}"
    if "/" in normalized and isinstance(bare_entry, dict):
        return normalized

    names = [normalized]
    if "/" in normalized:
        names.append(normalized.rsplit("/", 1)[-1])
    for name in names:
        matches = sorted(
            key
            for key in model_cost
            if key.endswith(f"/{name}") and key.split("/", 1)[0] not in INTERACTIVE_AUTH_PROVIDERS
        )
        if not matches:
            continue
        prices = {
            (
                model_cost[key].get("input_cost_per_token"),
                model_cost[key].get("output_cost_per_token"),
            )
            for key in matches
            if isinstance(model_cost.get(key), dict)
        }
        if len(matches) == 1 or len(prices) == 1:
            return matches[0]
    return None
