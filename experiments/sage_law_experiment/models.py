"""Model-name normalization for experiment plans and providers."""

from __future__ import annotations

MODEL_ALIASES = {
    "minimax-m2.7-highspeed": "MiniMax-M2.7-highspeed",
    "minimax m2.7 highspeed": "MiniMax-M2.7-highspeed",
    "minimax-m3": "MiniMax-M3",
    "minimax m3": "MiniMax-M3",
    "m3": "MiniMax-M3",
    "deepseek v4 flash": "deepseek-v4-flash",
    "deepseek-v4-flash": "deepseek-v4-flash",
    "deepseek v4 pro": "deepseek-v4-pro",
    "deepseek-v4-pro": "deepseek-v4-pro",
}


def canonical_model_name(model: str) -> str:
    key = model.strip().lower()
    return MODEL_ALIASES.get(key, model.strip())


def canonical_model_names(models: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(canonical_model_name(model) for model in models)
