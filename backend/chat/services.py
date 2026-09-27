from .model_manager import ModelManager


def ask_ollama(message: str, model_id: str = None, images=None) -> str:
    """
    Backward-compatible helper: sends a prompt to a registered local model via
    the ModelManager. Strictly uses the local on-premise Ollama instance without
    external AI fallback. `model_id` defaults to settings.DEFAULT_CHAT_MODEL.
    """
    return ModelManager().generate(model_id, message, images=images)["response"]
