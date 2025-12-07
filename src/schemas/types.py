"""
Type definitions for the Claude Code-like agent.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Union, Literal
from enum import Enum


class MessageRole(str, Enum):
    """Message roles in the conversation."""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class TodoStatus(str, Enum):
    """Status of a todo item."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class StopReason(str, Enum):
    """Reasons why the model stopped generating."""
    END_TURN = "end_turn"
    TOOL_USE = "tool_use"
    MAX_TOKENS = "max_tokens"
    STOP_SEQUENCE = "stop_sequence"


@dataclass
class TextBlock:
    """A text content block."""
    type: Literal["text"] = "text"
    text: str = ""


@dataclass
class ToolUseBlock:
    """A tool use content block."""
    type: Literal["tool_use"] = "tool_use"
    id: str = ""
    name: str = ""
    input: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResultBlock:
    """A tool result content block."""
    type: Literal["tool_result"] = "tool_result"
    tool_use_id: str = ""
    content: Union[str, List[Dict[str, Any]]] = ""
    is_error: bool = False


ContentBlock = Union[TextBlock, ToolUseBlock, ToolResultBlock, Dict[str, Any]]


@dataclass
class Message:
    """
    A message in the conversation.
    
    Attributes:
        role: The role of the message sender (user, assistant)
        content: The content of the message (string or list of blocks)
    """
    role: str
    content: Union[str, List[ContentBlock]]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert message to dictionary for API."""
        content = self.content
        if isinstance(content, list):
            content = [
                block.to_dict() if hasattr(block, 'to_dict') else block
                for block in content
            ]
        return {
            "role": self.role,
            "content": content
        }


@dataclass
class ToolCall:
    """
    Represents a tool call made by the assistant.
    
    Attributes:
        id: Unique identifier for this tool call
        name: Name of the tool being called
        input: Input parameters for the tool
    """
    id: str
    name: str
    input: Dict[str, Any]
    
    @classmethod
    def from_block(cls, block: Dict[str, Any]) -> "ToolCall":
        """Create a ToolCall from a tool_use block."""
        return cls(
            id=block.get("id", ""),
            name=block.get("name", ""),
            input=block.get("input", {})
        )


@dataclass
class ToolResult:
    """
    Result of executing a tool.
    
    Attributes:
        tool_use_id: ID of the tool call this is a result for
        content: The result content (string or structured)
        is_error: Whether this result represents an error
    """
    tool_use_id: str
    content: Union[str, List[Dict[str, Any]]]
    is_error: bool = False
    
    def to_block(self) -> Dict[str, Any]:
        """Convert to a tool_result block for the API."""
        return {
            "type": "tool_result",
            "tool_use_id": self.tool_use_id,
            "content": self.content,
            "is_error": self.is_error
        }


@dataclass
class ConversationHistory:
    """
    Manages conversation history with utilities for common operations.
    """
    messages: List[Message] = field(default_factory=list)
    
    def add_user_message(self, content: Union[str, List[ContentBlock]]) -> None:
        """Add a user message to the history."""
        self.messages.append(Message(role="user", content=content))
    
    def add_assistant_message(self, content: Union[str, List[ContentBlock]]) -> None:
        """Add an assistant message to the history."""
        self.messages.append(Message(role="assistant", content=content))
    
    def add_tool_results(self, results: List[ToolResult]) -> None:
        """Add tool results as a user message."""
        blocks = [result.to_block() for result in results]
        self.messages.append(Message(role="user", content=blocks))
    
    def get_messages_for_api(self) -> List[Dict[str, Any]]:
        """Get messages formatted for the API."""
        return [msg.to_dict() for msg in self.messages]
    
    def get_last_assistant_message(self) -> Optional[Message]:
        """Get the most recent assistant message."""
        for msg in reversed(self.messages):
            if msg.role == "assistant":
                return msg
        return None
    
    def get_pending_tool_calls(self) -> List[ToolCall]:
        """Get tool calls from the last assistant message that haven't been resolved."""
        last_msg = self.get_last_assistant_message()
        if not last_msg or not isinstance(last_msg.content, list):
            return []
        
        tool_calls = []
        for block in last_msg.content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                tool_calls.append(ToolCall.from_block(block))
        
        return tool_calls


@dataclass
class TodoItem:
    """
    A single todo item.
    """
    id: str
    content: str
    status: TodoStatus = TodoStatus.PENDING
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "status": self.status.value
        }


@dataclass
class AgentConfig:
    """
    Configuration for the agent.
    
    Attributes:
        model: The Claude model to use
        max_tokens: Maximum tokens for responses
        system_prompt: Custom system prompt
        tools: List of enabled tools
        workspace_path: Path to the workspace directory
        enable_planning: Whether to enable todo/planning tools
        enable_subagents: Whether to enable subagent delegation
        token_threshold: Token count that triggers summarization
    """
    model: str = "claude-sonnet-4-20250514"
    max_tokens: int = 8192
    system_prompt: Optional[str] = None
    tools: Optional[List[str]] = None
    workspace_path: Optional[str] = None
    
    # Feature flags
    enable_planning: bool = True
    enable_subagents: bool = True
    enable_bash: bool = True
    
    # Context management
    token_threshold: int = 170_000
    target_tokens_after_summarization: int = 100_000
    
    # Prompt caching
    enable_prompt_caching: bool = True
    
    # Error handling
    max_retries: int = 3
    retry_delay: float = 1.0


@dataclass
class AgentResponse:
    """
    Response from the agent.
    
    Attributes:
        content: Text content of the response
        tool_calls: Any tool calls made
        stop_reason: Why the model stopped generating
        usage: Token usage information
    """
    content: str
    tool_calls: List[ToolCall] = field(default_factory=list)
    stop_reason: StopReason = StopReason.END_TURN
    usage: Dict[str, int] = field(default_factory=dict)
    
    @classmethod
    def from_api_response(cls, response: Dict[str, Any]) -> "AgentResponse":
        """Create an AgentResponse from the API response."""
        content_blocks = response.get("content", [])
        
        text_parts = []
        tool_calls = []
        
        for block in content_blocks:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
                elif block.get("type") == "tool_use":
                    tool_calls.append(ToolCall.from_block(block))
        
        return cls(
            content="\n".join(text_parts),
            tool_calls=tool_calls,
            stop_reason=StopReason(response.get("stop_reason", "end_turn")),
            usage=response.get("usage", {})
        )

