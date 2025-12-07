#!/usr/bin/env python3
"""
YACC (Yet Another Claude Code) - Interactive CLI Application.

A Claude Code-like terminal interface for AI-assisted coding.
"""

import os
import sys
import argparse
import readline  # For input history
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.prompt import Prompt
from rich.live import Live
from rich.text import Text
from rich.panel import Panel

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    from src.agent import Agent, AgentConfig
    from src.cli.renderer import CLIRenderer, ThinkingSpinner, render_todos
except ImportError:
    from agent import Agent, AgentConfig
    from cli.renderer import CLIRenderer, ThinkingSpinner, render_todos


console = Console()


class YACCCLI:
    """Yet Another Claude Code CLI Application."""
    
    def __init__(
        self,
        workspace: Optional[str] = None,
        api_key: Optional[str] = None,
        model: str = "claude-sonnet-4-5-20250929",
        debug: bool = False,
    ):
        self.workspace = workspace or os.getcwd()
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.model = model
        self.debug = debug
        
        self.renderer = CLIRenderer()
        self.agent: Optional[Agent] = None
        self.history: list = []
    
    def initialize_agent(self):
        """Initialize the AI agent."""
        if not self.api_key:
            self.renderer.print_error("ANTHROPIC_API_KEY not set!")
            self.renderer.print_status(
                "Set it via: export ANTHROPIC_API_KEY='your-key'",
                "info"
            )
            return False
        
        try:
            config = AgentConfig(
                model=self.model,
                max_tokens=16384,
                api_key=self.api_key,
                workspace_path=self.workspace,
                enable_planning=True,
                enable_bash=True,
                enable_prompt_caching=True,
                debug=self.debug,
            )
            self.agent = Agent(config)
            return True
        except Exception as e:
            self.renderer.print_error(f"Failed to initialize agent: {e}")
            return False
    
    def process_message(self, message: str) -> bool:
        """
        Process a user message and display results in real-time.
        
        Returns:
            True if processing was successful, False otherwise
        """
        if not self.agent:
            self.renderer.print_error("Agent not initialized")
            return False
        
        self.renderer.print_user_input(message)
        
        current_todos = []
        turn_count = 0
        live = None
        
        try:
            # Stream events in real-time
            for event in self.agent.chat(message, max_turns=50):
                event_type = event.get("type")
                
                if event_type == "turn_start":
                    # Stop any existing spinner
                    if live:
                        live.stop()
                        live = None
                    
                    turn_count = event.get("turn", 0)
                    if turn_count > 1:
                        self.renderer.print_turn(turn_count)
                    
                    # Start thinking spinner for this turn
                    live = Live(
                        ThinkingSpinner("Thinking"),
                        console=self.renderer.console,
                        refresh_per_second=10,
                        transient=True
                    )
                    live.start()
                
                elif event_type == "assistant_message":
                    # Stop spinner before printing
                    if live:
                        live.stop()
                        live = None
                    
                    content = event.get("content", "")
                    tool_calls = event.get("tool_calls", [])
                    usage = event.get("usage", {})
                    
                    # Update token counts
                    self.renderer.update_tokens(
                        usage.get("input_tokens", 0),
                        usage.get("output_tokens", 0)
                    )
                    
                    # Print content if any (and not just tool calls)
                    if content and not tool_calls:
                        self.renderer.print_assistant(content)
                    elif content:
                        # Show brief thinking if there are tool calls
                        if len(content) < 200:
                            self.renderer.print_thinking(content)
                    
                    # Print tool calls
                    for tc in tool_calls:
                        self.renderer.print_tool_start(
                            tc.get("name", "unknown"),
                            tc.get("input", {})
                        )
                        
                        # Check if this is a todo update
                        if tc.get("name") == "write_todos":
                            todos = tc.get("input", {}).get("todos", [])
                            if todos:
                                current_todos = todos
                
                elif event_type == "tool_results":
                    # Stop spinner before printing results
                    if live:
                        live.stop()
                        live = None
                    
                    results = event.get("results", [])
                    for result in results:
                        content = result.get("content", "")
                        is_error = "Error" in content or "error" in content
                        self.renderer.print_tool_result(content, is_error)
                        
                        # If this was a todo update, show the todo panel
                        if current_todos:
                            self.renderer.console.print()
                            self.renderer.print_todos(current_todos)
                            current_todos = []  # Reset after displaying
                
                elif event_type == "complete":
                    if live:
                        live.stop()
                        live = None
                    self.renderer.print_completion(event.get("turn", turn_count))
                
                elif event_type == "error":
                    if live:
                        live.stop()
                        live = None
                    self.renderer.print_error(event.get("error", "Unknown error"))
                    return False
                
                elif event_type == "max_turns_reached":
                    if live:
                        live.stop()
                        live = None
                    self.renderer.print_status(
                        f"Reached maximum turns ({event.get('turn')})",
                        "warning"
                    )
            
            # Clean up spinner
            if live:
                live.stop()
            
            # Show final todos if any
            final_todos = self.agent.get_todos()
            if final_todos and final_todos != current_todos:
                self.renderer.console.print()
                self.renderer.print_todos(final_todos)
            
            return True
            
        except KeyboardInterrupt:
            if live:
                live.stop()
            self.renderer.console.print()
            self.renderer.print_status("Interrupted by user", "warning")
            return False
        except Exception as e:
            if live:
                live.stop()
            self.renderer.print_error(f"Error: {e}")
            if self.debug:
                import traceback
                traceback.print_exc()
            return False
    
    def run_interactive(self):
        """Run the interactive CLI loop."""
        self.renderer.print_welcome(self.workspace)
        
        if not self.initialize_agent():
            return 1
        
        self.renderer.print_status("Agent ready", "success")
        self.renderer.console.print()
        
        while True:
            try:
                # Get user input with styled prompt
                user_input = Prompt.ask(
                    "[bold cyan]>[/bold cyan]",
                    console=self.renderer.console
                ).strip()
                
                if not user_input:
                    continue
                
                # Handle special commands
                if user_input.lower() in ["exit", "quit", "q"]:
                    self.renderer.print_status("Goodbye! 👋", "info")
                    break
                
                if user_input.lower() == "clear":
                    self.renderer.clear()
                    self.renderer.print_welcome(self.workspace)
                    continue
                
                if user_input.lower() == "reset":
                    self.agent.reset()
                    self.renderer.print_status("Conversation reset", "success")
                    continue
                
                if user_input.lower() == "todos":
                    todos = self.agent.get_todos()
                    self.renderer.print_todos(todos)
                    continue
                
                if user_input.lower() == "help":
                    self._print_help()
                    continue
                
                # Process the message
                self.process_message(user_input)
                
            except KeyboardInterrupt:
                self.renderer.console.print()
                self.renderer.print_status("Use 'exit' to quit", "info")
            except EOFError:
                break
        
        return 0
    
    def run_once(self, message: str) -> int:
        """Run a single message and exit."""
        if not self.initialize_agent():
            return 1
        
        success = self.process_message(message)
        return 0 if success else 1
    
    def _print_help(self):
        """Print help information."""
        help_text = """
[bold cyan]Commands:[/bold cyan]
  [bold]exit, quit, q[/bold]  - Exit the CLI
  [bold]clear[/bold]          - Clear the screen
  [bold]reset[/bold]          - Reset conversation history
  [bold]todos[/bold]          - Show current todo list
  [bold]help[/bold]           - Show this help message

[bold cyan]Tips:[/bold cyan]
  • Be specific in your requests
  • The agent can read/write files, run commands
  • Use todos for complex multi-step tasks
  • Press Ctrl+C to interrupt long operations
"""
        self.renderer.console.print(Panel(
            help_text,
            title="Help",
            border_style="cyan"
        ))


def run_cli():
    """Entry point for the CLI."""
    parser = argparse.ArgumentParser(
        description="YACC - Yet Another Claude Code",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  yacc                          # Start interactive mode
  yacc "Create a hello.py"      # Run single command
  yacc -w /path/to/project      # Use specific workspace
  yacc --model claude-sonnet-4-5-20250929  # Use specific model
        """
    )
    
    parser.add_argument(
        "message",
        nargs="?",
        help="Message to send (starts interactive mode if not provided)"
    )
    parser.add_argument(
        "-w", "--workspace",
        default=os.getcwd(),
        help="Workspace directory (default: current directory)"
    )
    parser.add_argument(
        "-k", "--api-key",
        help="Anthropic API key (default: ANTHROPIC_API_KEY env var)"
    )
    parser.add_argument(
        "-m", "--model",
        default="claude-sonnet-4-5-20250929",
        help="Model to use (default: claude-sonnet-4-5-20250929)"
    )
    parser.add_argument(
        "-d", "--debug",
        action="store_true",
        help="Enable debug mode"
    )
    parser.add_argument(
        "-v", "--version",
        action="version",
        version="yacc 0.1.0"
    )
    
    args = parser.parse_args()
    
    cli = YACCCLI(
        workspace=args.workspace,
        api_key=args.api_key,
        model=args.model,
        debug=args.debug,
    )
    
    if args.message:
        return cli.run_once(args.message)
    else:
        return cli.run_interactive()


def main():
    """Main entry point."""
    sys.exit(run_cli())


if __name__ == "__main__":
    main()

