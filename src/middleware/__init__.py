"""
Middleware components for the Claude Code-like agent.

Middleware handles:
- Context summarization when token limits are exceeded
- Prompt caching for Anthropic API
- Fixing dangling tool calls from interruptions
"""

from .base import BaseMiddleware, MiddlewareChain
from .summarization import SummarizationMiddleware
from .prompt_caching import AnthropicPromptCachingMiddleware
from .patch_tool_calls import PatchToolCallsMiddleware

__all__ = [
    "BaseMiddleware",
    "MiddlewareChain",
    "SummarizationMiddleware",
    "AnthropicPromptCachingMiddleware",
    "PatchToolCallsMiddleware",
]

