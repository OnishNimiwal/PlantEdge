"""Keep the knowledge store in step with deleted documents (also on queryset/cascade deletes)."""

import logging

from django.db.models.signals import post_delete
from django.dispatch import receiver

from documents.models import Document

from . import store

logger = logging.getLogger(__name__)


@receiver(post_delete, sender=Document)
def _remove_from_index(sender, instance, **kwargs):
    if not (store.store_dir() / "edge_config.json").exists():
        return
    try:
        store.delete_document(instance.pk)
    except store.StoreError as exc:
        # e.g. a management command while the server holds the store; `index_documents --prune` cleans up
        logger.warning("Could not remove doc_id=%s from the knowledge store: %s", instance.pk, exc)
