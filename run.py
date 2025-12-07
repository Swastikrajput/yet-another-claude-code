#!/usr/bin/env python3
"""
Test script for yet-another-claude-code agent.
Requests the agent to create a 2048 game.
"""

import os
import sys

# Add project root to path for proper package imports
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

from src.agent import Agent, AgentConfig


def print_divider(char="─", length=60):
    print(char * length)


def print_header(title: str):
    print()
    print_divider("═")
    print(f"  {title}")
    print_divider("═")
    print()


def format_tool_call(tool_call: dict) -> str:
    """Format a tool call for display."""
    name = tool_call.get("name", "unknown")
    input_data = tool_call.get("input", {})
    
    # Truncate long inputs
    input_str = str(input_data)
    if len(input_str) > 100:
        input_str = input_str[:100] + "..."
    
    return f"🔧 {name}({input_str})"


def main():
    print_header("🎮 Yet Another Claude Code - 2048 Game Test")
    
    # API Key
    api_key = os.getenv("ANTHROPIC_API_KEY")
    
    # Create workspace directory
    workspace = os.path.join(os.path.dirname(__file__), "workspace")
    os.makedirs(workspace, exist_ok=True)
    
    print(f"📁 Workspace: {workspace}")
    print()
    
    # Initialize agent
    config = AgentConfig(
        model="claude-sonnet-4-5-20250929",
        max_tokens=16384,
        api_key=api_key,
        workspace_path=workspace,
        enable_planning=True,
        enable_bash=True,
        enable_prompt_caching=True,
        debug=False,
    )
    
    agent = Agent(config)
    
    print("✅ Agent initialized")
    print_divider()
    
    # The task
    task = """
웹에서 2024 할 수 있는거 만들어줘 
"""
    
    print(f"\n📝 Task:\n{task}\n")
    print_divider()
    
    # Run agent
    turn_count = 0
    
    for event in agent.chat(task, max_turns=30):
        event_type = event.get("type")
        
        if event_type == "turn_start":
            turn_count = event.get("turn", 0)
            print(f"\n🔄 Turn {turn_count}")
            print_divider("─", 40)
        
        elif event_type == "assistant_message":
            content = event.get("content", "")
            tool_calls = event.get("tool_calls", [])
            usage = event.get("usage", {})
            stop_reason = event.get("stop_reason", "")
            
            # Show text content
            if content:
                # Truncate very long content for display
                if len(content) > 500:
                    print(f"💬 {content[:500]}...")
                else:
                    print(f"💬 {content}")
            
            # Show tool calls
            for tc in tool_calls:
                print(format_tool_call(tc))
            
            # Show usage
            input_tokens = usage.get("input_tokens", 0)
            output_tokens = usage.get("output_tokens", 0)
            print(f"   📊 Tokens: {input_tokens} in / {output_tokens} out | Stop: {stop_reason}")
        
        elif event_type == "tool_results":
            results = event.get("results", [])
            for result in results:
                content = result.get("content", "")
                # Truncate long results
                if len(content) > 200:
                    content = content[:200] + "..."
                print(f"   ✅ Result: {content}")
        
        elif event_type == "complete":
            print_divider()
            print(f"\n✨ Completed in {event.get('turn', 0)} turns!")
        
        elif event_type == "error":
            print(f"\n❌ Error: {event.get('error')}")
        
        elif event_type == "max_turns_reached":
            print(f"\n⚠️ Max turns ({event.get('turn')}) reached")
    
    # Show final todos
    todos = agent.get_todos()
    if todos:
        print("\n📋 Final Todo List:")
        for todo in todos:
            status_icon = {
                "pending": "⬜",
                "in_progress": "🔄",
                "completed": "✅"
            }.get(todo.get("status", "pending"), "⬜")
            print(f"  {status_icon} {todo.get('content', '')}")
    
    # Check if file was created
    game_file = os.path.join(workspace, "game_2048.py")
    if os.path.exists(game_file):
        print(f"\n✅ Game file created: {game_file}")
        print("\n🎮 To play the game, run:")
        print(f"   python {game_file}")
    else:
        print("\n⚠️ Game file was not created")
    
    print_divider("═")


if __name__ == "__main__":
    main()

