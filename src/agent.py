"""
Main Agent class for the Claude Code-like agent.
Pure Python implementation without LangChain.
"""

import os
import json
from typing import Dict, List, Any, Optional, Generator
from dataclasses import dataclass, field

import anthropic

# Support both relative and absolute imports
try:
    from .tools.definitions import get_tools_for_api, DEFAULT_TOOLS
    from .tools.executor import ToolExecutor
    from .prompts.system import build_system_prompt
    from .middleware.base import AgentState, MiddlewareChain
    from .middleware.summarization import SummarizationMiddleware
    from .middleware.prompt_caching import AnthropicPromptCachingMiddleware
    from .middleware.patch_tool_calls import PatchToolCallsMiddleware
except ImportError:
    from src.tools.definitions import get_tools_for_api, DEFAULT_TOOLS
    from src.tools.executor import ToolExecutor
    from src.prompts.system import build_system_prompt
    from src.middleware.base import AgentState, MiddlewareChain
    from src.middleware.summarization import SummarizationMiddleware
    from src.middleware.prompt_caching import AnthropicPromptCachingMiddleware
    from src.middleware.patch_tool_calls import PatchToolCallsMiddleware


@dataclass 
class AgentConfig:
    """Configuration for the agent."""
    model: str = "claude-sonnet-4-5-20250929"
    max_tokens: int = 16384
    api_key: Optional[str] = None
    workspace_path: str = "/tmp/workspace"
    
    # Feature toggles
    enable_planning: bool = True
    enable_bash: bool = True
    enable_prompt_caching: bool = True
    enable_summarization: bool = True
    
    # Custom settings
    custom_system_prompt: Optional[str] = None
    enabled_tools: Optional[List[str]] = None
    
    # Debug
    debug: bool = False


class Agent:
    """
    A Claude Code-like agent implementation.
    
    Features:
    - Tool execution (filesystem, bash, planning)
    - Automatic context summarization
    - Prompt caching for efficiency
    - Tool call patching for reliability
    """
    
    def __init__(self, config: Optional[AgentConfig] = None):
        """
        Initialize the agent.
        
        Args:
            config: Agent configuration
        """
        self.config = config or AgentConfig()
        
        # Initialize Anthropic client
        api_key = self.config.api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY is required")
        
        self.client = anthropic.Anthropic(api_key=api_key)
        
        # Initialize tool executor
        self.executor = ToolExecutor(
            workspace_path=self.config.workspace_path,
            use_virtual_fs=False
        )
        
        # Build system prompt
        self.system_prompt = build_system_prompt(
            custom_instructions=self.config.custom_system_prompt,
            workspace_path=self.config.workspace_path,
        )
        
        # Get tool definitions
        tool_names = self.config.enabled_tools or DEFAULT_TOOLS
        if not self.config.enable_planning:
            tool_names = [t for t in tool_names if t != "write_todos"]
        if not self.config.enable_bash:
            tool_names = [t for t in tool_names if t != "bash"]
        
        self.tools = get_tools_for_api(tool_names)
        
        # Initialize middleware
        self.middleware = MiddlewareChain()
        
        if self.config.enable_prompt_caching:
            self.middleware.add(AnthropicPromptCachingMiddleware())
        
        if self.config.enable_summarization:
            self.middleware.add(SummarizationMiddleware())
        
        self.middleware.add(PatchToolCallsMiddleware())
        
        # Conversation state
        self.state = AgentState(
            system_prompt=self.system_prompt,
            tools=self.tools
        )
    
    def _log(self, message: str):
        """Debug logging."""
        if self.config.debug:
            print(f"[DEBUG] {message}")
    
    def _call_api(self) -> Dict[str, Any]:
        """
        Make an API call to Claude.
        
        Returns:
            API response dictionary
        """
        # Apply pre-processing middleware
        self.state = self.middleware.pre_process(self.state)
        
        # Build request
        request_params = {
            "model": self.config.model,
            "max_tokens": self.config.max_tokens,
            "messages": self.state.messages,
        }
        
        # Add system prompt (with caching if enabled)
        if self.config.enable_prompt_caching:
            request_params["system"] = [{
                "type": "text",
                "text": self.state.system_prompt,
                "cache_control": {"type": "ephemeral"}
            }]
        else:
            request_params["system"] = self.state.system_prompt
        
        # Add tools
        if self.state.tools:
            request_params["tools"] = self.state.tools
        
        self._log(f"API call with {len(self.state.messages)} messages")
        
        # Make API call
        response = self.client.messages.create(**request_params)
        
        # Convert to dict for middleware processing
        response_dict = {
            "id": response.id,
            "type": response.type,
            "role": response.role,
            "content": [block.model_dump() for block in response.content],
            "model": response.model,
            "stop_reason": response.stop_reason,
            "stop_sequence": response.stop_sequence,
            "usage": {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            }
        }
        
        # Apply post-processing middleware
        self.state, response_dict = self.middleware.post_process(self.state, response_dict)
        
        return response_dict
    
    def _extract_tool_calls(self, content: List[Dict]) -> List[Dict[str, Any]]:
        """Extract tool calls from response content."""
        tool_calls = []
        for block in content:
            if block.get("type") == "tool_use":
                tool_calls.append({
                    "id": block.get("id"),
                    "name": block.get("name"),
                    "input": block.get("input", {})
                })
        return tool_calls
    
    def _extract_text(self, content: List[Dict]) -> str:
        """Extract text from response content."""
        texts = []
        for block in content:
            if block.get("type") == "text":
                texts.append(block.get("text", ""))
        return "\n".join(texts)
    
    def _execute_tools(self, tool_calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Execute tool calls and return results.
        
        Args:
            tool_calls: List of tool calls to execute
            
        Returns:
            List of tool result blocks
        """
        results = []
        
        for tool_call in tool_calls:
            tool_id = tool_call["id"]
            tool_name = tool_call["name"]
            tool_input = tool_call["input"]
            
            self._log(f"Executing tool: {tool_name}")
            
            # Execute the tool
            result = self.executor.execute(tool_name, tool_input)
            
            self._log(f"Tool result: {result[:100]}...")
            
            results.append({
                "type": "tool_result",
                "tool_use_id": tool_id,
                "content": result
            })
        
        return results
    
    def chat(self, message: str, max_turns: int = 50) -> Generator[Dict[str, Any], None, None]:
        """
        Send a message and get responses.
        
        This is a generator that yields events as the agent processes.
        
        Args:
            message: User message
            max_turns: Maximum number of API turns
            
        Yields:
            Event dictionaries with type and data
        """
        # Add user message
        self.state.messages.append({
            "role": "user",
            "content": message
        })
        
        yield {"type": "user_message", "content": message}
        
        turn = 0
        while turn < max_turns:
            turn += 1
            self.state.turn_count += 1
            
            yield {"type": "turn_start", "turn": turn}
            
            # Call API
            try:
                response = self._call_api()
            except Exception as e:
                yield {"type": "error", "error": str(e)}
                break
            
            # Add assistant response to history
            self.state.messages.append({
                "role": "assistant",
                "content": response["content"]
            })
            
            # Extract text and tool calls
            text = self._extract_text(response["content"])
            tool_calls = self._extract_tool_calls(response["content"])
            
            # Yield assistant response
            yield {
                "type": "assistant_message",
                "content": text,
                "tool_calls": tool_calls,
                "usage": response.get("usage", {}),
                "stop_reason": response.get("stop_reason")
            }
            
            # Check if we're done
            if response.get("stop_reason") == "end_turn":
                yield {"type": "complete", "turn": turn}
                break
            
            # Execute tool calls
            if tool_calls:
                tool_results = self._execute_tools(tool_calls)
                
                # Add tool results to history
                self.state.messages.append({
                    "role": "user",
                    "content": tool_results
                })
                
                yield {
                    "type": "tool_results",
                    "results": tool_results
                }
        else:
            yield {"type": "max_turns_reached", "turn": turn}
    
    def run(self, message: str, max_turns: int = 50) -> str:
        """
        Send a message and get the final response.
        
        This is a blocking call that processes all events and returns
        the final text response.
        
        Args:
            message: User message
            max_turns: Maximum number of API turns
            
        Returns:
            Final text response from the agent
        """
        final_text = ""
        
        for event in self.chat(message, max_turns):
            if event["type"] == "assistant_message":
                if event.get("content"):
                    final_text = event["content"]
        
        return final_text
    
    def get_todos(self) -> List[Dict[str, Any]]:
        """Get current todo list."""
        return self.executor.todos
    
    def reset(self):
        """Reset conversation state."""
        self.state = AgentState(
            system_prompt=self.system_prompt,
            tools=self.tools
        )
        self.executor.todos = []
        self.executor.files_read = set()

