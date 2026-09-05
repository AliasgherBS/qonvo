"""Per-tenant provider resolution (DESIGN.md §4).

Reads the tenant's provider choice from ``tenant_config`` (the flat
``llm_provider``/``llm_model`` columns, or the nested ``providers`` JSON map),
falling back to the system defaults in :mod:`app.core.config`. Named presets
map a provider key to its base URL so tenants/ops only pick a name.
"""

from __future__ import annotations

from typing import Any, Protocol

from app.core.config import settings
from app.providers.openai_compat import OpenAICompatProvider

# Provider name → base URL. "custom" (or any unknown name) uses the caller's
# base_url verbatim / the system default.
PROVIDER_PRESETS: dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "groq": "https://api.groq.com/openai/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
}


class TenantConfigLike(Protocol):
    """Minimal shape of ``app.models.tenant.TenantConfig`` this module reads."""

    llm_provider: str | None
    llm_model: str | None
    providers: dict[str, Any]


def _capability_config(tenant_config: TenantConfigLike | None, capability: str) -> dict[str, Any]:
    if tenant_config is None:
        return {}
    providers = getattr(tenant_config, "providers", None) or {}
    value = providers.get(capability)
    return value if isinstance(value, dict) else {}


def _resolve_base_url(provider_name: str, override: str | None) -> str | None:
    if override:
        return override
    return PROVIDER_PRESETS.get(provider_name)


def resolve_llm_identity(tenant_config: TenantConfigLike | None = None) -> tuple[str, str]:
    """Return the ``(provider, model)`` an LLM call for this tenant will use.

    Split out from :func:`resolve_llm` so that pricing and logging name the same
    model that actually answered. Reading the flat columns separately drifts the
    moment a tenant is configured through the nested ``providers`` map.

    Lookup order per field: ``tenant_config.providers["llm"]`` entry, then the
    flat ``tenant_config.llm_provider``/``llm_model`` columns, then
    ``settings.llm_*``.
    """
    llm_cfg = _capability_config(tenant_config, "llm")
    provider_name = (
        llm_cfg.get("provider")
        or (tenant_config.llm_provider if tenant_config is not None else None)
        or settings.llm_provider
    )
    model = (
        llm_cfg.get("model")
        or (tenant_config.llm_model if tenant_config is not None else None)
        or settings.llm_model
    )
    return provider_name, model


def resolve_llm(tenant_config: TenantConfigLike | None = None) -> OpenAICompatProvider:
    """Build an LLM provider for a tenant, falling back to system defaults."""
    llm_cfg = _capability_config(tenant_config, "llm")
    provider_name, model = resolve_llm_identity(tenant_config)
    base_url = _resolve_base_url(provider_name, llm_cfg.get("base_url") or settings.llm_base_url)
    api_key = llm_cfg.get("api_key") or settings.llm_api_key

    return OpenAICompatProvider(
        base_url=base_url or PROVIDER_PRESETS["openai"],
        api_key=api_key,
        model=model,
    )


def resolve_embedding_identity(
    tenant_config: TenantConfigLike | None = None,
) -> tuple[str, str]:
    """The ``(provider, model)`` an embedding call for this tenant will use.

    Split out for the same reason as :func:`resolve_llm_identity`: pricing has
    to name the model that actually ran. Note there are no flat
    ``embedding_provider``/``embedding_model`` columns on tenant_config — the
    only per-tenant override is the nested ``providers`` map.
    """
    emb_cfg = _capability_config(tenant_config, "embedding")
    return (
        emb_cfg.get("provider") or settings.embedding_provider,
        emb_cfg.get("model") or settings.embedding_model,
    )


def resolve_embedding(tenant_config: TenantConfigLike | None = None) -> OpenAICompatProvider:
    """Build an embedding provider for a tenant, falling back to system defaults."""
    emb_cfg = _capability_config(tenant_config, "embedding")
    provider_name, model = resolve_embedding_identity(tenant_config)
    base_url = _resolve_base_url(
        provider_name, emb_cfg.get("base_url") or settings.embedding_base_url
    )
    api_key = emb_cfg.get("api_key") or settings.embedding_api_key

    return OpenAICompatProvider(
        base_url=base_url or PROVIDER_PRESETS["openai"],
        api_key=api_key,
        model=model,
    )


def resolve_stt(tenant_config: TenantConfigLike | None = None):
    """Build an STT provider, or None if no key is configured (voice disabled)."""
    from app.providers.audio import OpenAICompatSTT

    cfg = _capability_config(tenant_config, "stt")
    provider_name = cfg.get("provider") or settings.stt_provider
    api_key = cfg.get("api_key") or settings.stt_api_key
    if not api_key:
        return None
    model = cfg.get("model") or settings.stt_model
    base_url = _resolve_base_url(provider_name, cfg.get("base_url") or settings.stt_base_url)
    return OpenAICompatSTT(
        base_url=base_url or PROVIDER_PRESETS["groq"], api_key=api_key, model=model
    )


def resolve_tts(tenant_config: TenantConfigLike | None = None):
    """Build a TTS provider, or None if no key is configured (voice replies off)."""
    from app.providers.audio import OpenAICompatTTS

    cfg = _capability_config(tenant_config, "tts")
    provider_name = cfg.get("provider") or settings.tts_provider
    api_key = cfg.get("api_key") or settings.tts_api_key
    if not api_key:
        return None
    model = cfg.get("model") or settings.tts_model
    voice = cfg.get("voice") or settings.tts_voice
    base_url = _resolve_base_url(provider_name, cfg.get("base_url") or settings.tts_base_url)
    return OpenAICompatTTS(
        base_url=base_url or PROVIDER_PRESETS["openai"],
        api_key=api_key,
        model=model,
        voice=voice,
        response_format=settings.tts_format,
    )


def voice_reply_mode(tenant_config: TenantConfigLike | None = None) -> str:
    """"match" | "always" | "never" — per-tenant override, else system default."""
    cfg = _capability_config(tenant_config, "voice")
    return cfg.get("mode") or settings.voice_reply_mode


__all__ = [
    "PROVIDER_PRESETS",
    "resolve_embedding",
    "resolve_llm",
    "resolve_stt",
    "resolve_tts",
    "voice_reply_mode",
]
