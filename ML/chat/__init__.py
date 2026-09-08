"""Conversation and bounded action proposals; this package never controls hardware."""

from .provider import OpenAICompatibleProvider, ProviderError
from .service import ChatService

__all__ = ["ChatService", "OpenAICompatibleProvider", "ProviderError"]
