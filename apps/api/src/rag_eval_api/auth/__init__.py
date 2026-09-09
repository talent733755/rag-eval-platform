"""Authentication and authorization boundaries."""

from rag_eval_api.auth.context import RequestActor, get_current_actor

__all__ = ["RequestActor", "get_current_actor"]
