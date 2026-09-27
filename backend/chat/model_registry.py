"""
Registry of local models served by the on-premise Ollama instance.

To add a model: pull it into Ollama (`ollama pull <name>`) and add one
LocalModel entry to MODEL_REGISTRY below. Nothing else needs to change.
"""

from dataclasses import dataclass, asdict

from django.conf import settings


@dataclass(frozen=True)
class LocalModel:
    id: str            # Stable identifier used by the API/frontend
    name: str          # Human-readable display name
    ollama_name: str   # Exact tag as known to Ollama
    capability: str    # reasoning | coding | vision
    modality: str      # text | multimodal
    description: str = ""

    @property
    def supports_images(self) -> bool:
        return self.modality == "multimodal"

    def to_dict(self) -> dict:
        data = asdict(self)
        data["supports_images"] = self.supports_images
        return data


MODEL_REGISTRY = {
    model.id: model
    for model in (
        LocalModel(
            id="qwen3",
            name="Qwen3:8b",
            ollama_name="qwen3:8b",
            capability="reasoning",
            modality="text",
            description="General reasoning, chat and structured text generation.",
        ),
        LocalModel(
            id="qwen-coder",
            name="Qwen2.5-Coder:7b",
            ollama_name="qwen2.5-coder:7b",
            capability="coding",
            modality="text",
            description="Code generation and code understanding.",
        ),
        LocalModel(
            id="qwen-vl",
            name="Qwen2.5-VL:7b",
            ollama_name="qwen2.5vl:7b",
            capability="vision",
            modality="multimodal",
            description="Image and document understanding.",
        ),
    )
}


class UnknownModelError(Exception):
    """Raised when a model id is not present in the registry."""


def get_default_model_id() -> str:
    return getattr(settings, "DEFAULT_CHAT_MODEL", "qwen3")


def get_model(model_id: str) -> LocalModel:
    """Look up a model by registry id ("qwen3") or Ollama tag ("qwen3:8b")."""
    if model_id in MODEL_REGISTRY:
        return MODEL_REGISTRY[model_id]
    for model in MODEL_REGISTRY.values():
        if model.ollama_name == model_id:
            return model
    raise UnknownModelError(model_id)


def list_models() -> list:
    return list(MODEL_REGISTRY.values())
