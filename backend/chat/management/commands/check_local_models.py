from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from chat.model_manager import ensure_local_endpoint, _session, ModelManagerError
from chat.model_registry import list_models


class Command(BaseCommand):
    help = "Verify that every registered model is installed on the local Ollama server."

    def handle(self, *args, **options):
        try:
            ensure_local_endpoint(settings.OLLAMA_URL)
            tags = _session().get(f"{settings.OLLAMA_URL}/api/tags", timeout=10, allow_redirects=False).json()
        except ModelManagerError as exc:
            raise CommandError(f"Ollama endpoint refused: {exc}")
        except Exception as exc:
            raise CommandError(f"Cannot reach Ollama at {settings.OLLAMA_URL}: {exc.__class__.__name__}")
        installed = {m["name"] for m in tags.get("models", [])}
        missing = 0
        for model in list_models():
            ok = model.ollama_name in installed
            missing += not ok
            self.stdout.write(f"{'OK     ' if ok else 'MISSING'} {model.id:12} {model.ollama_name}")
        embedding = settings.EMBEDDING_MODEL
        installed_names = installed | {name.removesuffix(":latest") for name in installed}
        ok = embedding in installed_names
        missing += not ok
        self.stdout.write(f"{'OK     ' if ok else 'MISSING'} {'embedding':12} {embedding}")
        if missing:
            raise CommandError(f"{missing} registered model(s) missing. Install with: ollama pull <name>")
        self.stdout.write(self.style.SUCCESS(f"All {len(list_models())} registered models and the embedding model are installed."))
