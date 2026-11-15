"""Registry for separately installed lender, insurer and credit-bureau adapters."""
import importlib
import re
from typing import Any, Callable

import config

_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{1,50}$")
_providers: dict[str, Any] = {}


def register(provider: Any) -> None:
    name = getattr(provider, "name", "")
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise ValueError("A financial provider needs a lower-case name with letters, numbers or dashes.")
    if name in _providers:
        raise ValueError(f"Financial provider already registered: {name}")
    _providers[name] = provider


def load_configured() -> None:
    """Each configured module exports register(registry) and installs its provider adapters."""
    for module_name in config.FINANCIAL_PROVIDER_MODULES:
        module = importlib.import_module(module_name)
        setup: Callable = getattr(module, "register", None)
        if not callable(setup):
            raise RuntimeError(f"Financial provider module {module_name!r} has no register(registry) function.")
        setup(register)


def capabilities() -> list[dict]:
    return [{"id": name, "capabilities": sorted(
        capability for capability in ("credit_check", "loan_offers", "loan_apply", "insurance_quotes", "insurance_purchase")
        if callable(getattr(provider, capability, None)))} for name, provider in sorted(_providers.items())]


def get(name: str, capability: str) -> Any:
    provider = _providers.get(name)
    if provider is None or not callable(getattr(provider, capability, None)):
        return None
    return provider
