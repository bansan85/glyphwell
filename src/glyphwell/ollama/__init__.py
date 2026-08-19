"""Interface avec le serveur Ollama : client et rendu des prompts."""

from glyphwell.ollama.client import Completion, LlmClient, OllamaClient
from glyphwell.ollama.prompts import PromptContext, render, render_context

__all__ = [
    "Completion",
    "LlmClient",
    "OllamaClient",
    "PromptContext",
    "render",
    "render_context",
]
