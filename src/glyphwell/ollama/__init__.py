"""Interface with the Ollama server: client and prompt rendering."""

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
