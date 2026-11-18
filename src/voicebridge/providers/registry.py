from __future__ import annotations

from collections.abc import Callable
from importlib import import_module, metadata
from typing import Any

from voicebridge.providers.base import ASRProvider, ProviderUnavailable

_BUILTINS: dict[str, tuple[str, str]] = {
    "mock": ("voicebridge.providers.mock", "MockProvider"),
    "aliyun": ("voicebridge.providers.aliyun", "AliyunParaformerProvider"),
    "deepgram": ("voicebridge.providers.deepgram", "DeepgramProvider"),
    "command": ("voicebridge.providers.command", "CommandProvider"),
}


def available_providers() -> dict[str, str]:
    providers = {
        name: f"built-in ({module}.{class_name})"
        for name, (module, class_name) in _BUILTINS.items()
    }
    try:
        entries = metadata.entry_points(group="voicebridge.providers")
    except TypeError:  # pragma: no cover - older Python importlib API
        entries = metadata.entry_points().get("voicebridge.providers", [])
    for entry in entries:
        providers.setdefault(entry.name, f"plugin ({entry.value})")
    return providers


def _load_builtin(name: str) -> Callable[[], ASRProvider] | None:
    target = _BUILTINS.get(name)
    if target is None:
        return None
    module_name, class_name = target
    module = import_module(module_name)
    provider_class: Any = getattr(module, class_name)
    return provider_class


def _load_plugin(name: str) -> Callable[[], ASRProvider] | None:
    try:
        entries = metadata.entry_points(group="voicebridge.providers")
    except TypeError:  # pragma: no cover - older Python importlib API
        entries = metadata.entry_points().get("voicebridge.providers", [])
    for entry in entries:
        if entry.name == name:
            return entry.load()
    return None


def create_provider(name: str) -> ASRProvider:
    normalized = name.strip().lower()
    factory = _load_builtin(normalized) or _load_plugin(normalized)
    if factory is None:
        raise ProviderUnavailable(
            f"unknown ASR provider '{name}'; available: {', '.join(sorted(available_providers()))}"
        )
    provider = factory()
    if not isinstance(provider, ASRProvider):
        raise ProviderUnavailable(
            f"provider plugin '{name}' did not return an ASRProvider instance"
        )
    return provider
