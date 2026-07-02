"""Celery adapter for the :class:`WorkflowEngine` port (default scheduler)."""

from memcore.adapters.celery.workflow import CeleryWorkflowEngine

__all__ = ["CeleryWorkflowEngine"]
