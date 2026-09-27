"""Startup checks for legacy / unsafe AI configuration (run by `manage.py check` and runserver)."""

import os

from django.core.checks import Warning, register


@register()
def legacy_ai_settings(app_configs, **kwargs):
    warnings = []
    if os.getenv("ALLOW_EXTERNAL_AI", "").strip().lower() in ("true", "1", "yes"):
        warnings.append(Warning(
            "ALLOW_EXTERNAL_AI=True is set but not supported.",
            hint="This workbench is local-only; there is no external/cloud AI integration. "
                 "Remove ALLOW_EXTERNAL_AI from .env.",
            id="chat.W001",
        ))
    if os.getenv("OLLAMA_MODEL"):
        warnings.append(Warning(
            "OLLAMA_MODEL is set but no longer used.",
            hint="Models are configured in backend/chat/model_registry.py. "
                 "Run `manage.py check_local_models` to verify they are installed. "
                 "Remove OLLAMA_MODEL from .env.",
            id="chat.W002",
        ))
    return warnings
