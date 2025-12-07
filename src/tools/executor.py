"""
Tool execution implementations.
"""

import os
import re
import glob as glob_module
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field


@dataclass
class ToolExecutor:
    """
    Executes tools and manages tool state.
    """
    workspace_path: str = "/workspace"
    files_read: set = field(default_factory=set)
    todos: List[Dict[str, Any]] = field(default_factory=list)
    
    # Virtual filesystem for testing (in-memory)
    use_virtual_fs: bool = False
    virtual_fs: Dict[str, str] = field(default_factory=dict)
    
    def __post_init__(self):
        # Ensure workspace exists
        if not self.use_virtual_fs:
            os.makedirs(self.workspace_path, exist_ok=True)
    
    def execute(self, tool_name: str, tool_input: Dict[str, Any]) -> str:
        """
        Execute a tool and return the result.
        
        Args:
            tool_name: Name of the tool to execute
            tool_input: Input parameters for the tool
            
        Returns:
            String result of the tool execution
        """
        handlers: Dict[str, Callable] = {
            "write_todos": self._handle_write_todos,
            "ls": self._handle_ls,
            "read_file": self._handle_read_file,
            "write_file": self._handle_write_file,
            "edit_file": self._handle_edit_file,
            "glob": self._handle_glob,
            "grep": self._handle_grep,
            "bash": self._handle_bash,
        }
        
        handler = handlers.get(tool_name)
        if not handler:
            return f"Error: Unknown tool '{tool_name}'"
        
        try:
            return handler(tool_input)
        except Exception as e:
            return f"Error executing {tool_name}: {str(e)}"
    
    def _handle_write_todos(self, input: Dict[str, Any]) -> str:
        """Handle write_todos tool."""
        todos = input.get("todos", [])
        merge = input.get("merge", True)
        
        if merge and self.todos:
            # Merge by ID
            todo_map = {t["id"]: t for t in self.todos}
            for todo in todos:
                todo_map[todo["id"]] = todo
            self.todos = list(todo_map.values())
        else:
            self.todos = todos
        
        # Format output
        lines = ["📋 Todo List Updated:"]
        for todo in self.todos:
            status_icon = {
                "pending": "⬜",
                "in_progress": "🔄",
                "completed": "✅"
            }.get(todo.get("status", "pending"), "⬜")
            lines.append(f"  {status_icon} [{todo.get('id', '?')}] {todo.get('content', '')}")
        
        return "\n".join(lines)
    
    def _resolve_path(self, path: str) -> str:
        """Resolve a path relative to workspace."""
        if not path.startswith("/"):
            path = "/" + path
        
        # For real filesystem
        if not self.use_virtual_fs:
            # If path starts with actual workspace path, use as-is
            if path.startswith(self.workspace_path):
                return path
            # If path starts with /workspace, replace with actual workspace path
            if path.startswith("/workspace"):
                return os.path.join(self.workspace_path, path[10:].lstrip("/"))
            # Otherwise, treat as relative to workspace
            return os.path.join(self.workspace_path, path.lstrip("/"))
        
        return path
    
    def _handle_ls(self, input: Dict[str, Any]) -> str:
        """Handle ls tool."""
        path = input.get("path", "/")
        resolved = self._resolve_path(path)
        
        if self.use_virtual_fs:
            # List from virtual fs
            files = []
            dirs = set()
            prefix = path.rstrip("/") + "/"
            for p in self.virtual_fs.keys():
                if p.startswith(prefix):
                    relative = p[len(prefix):]
                    if "/" in relative:
                        dirs.add(relative.split("/")[0] + "/")
                    else:
                        files.append(relative)
            items = sorted(dirs) + sorted(files)
            if not items:
                return f"Directory {path} is empty or does not exist"
            return "\n".join(items)
        else:
            # Real filesystem
            if not os.path.exists(resolved):
                return f"Directory does not exist: {path}"
            
            if not os.path.isdir(resolved):
                return f"Not a directory: {path}"
            
            items = []
            for item in sorted(os.listdir(resolved)):
                full_path = os.path.join(resolved, item)
                if os.path.isdir(full_path):
                    items.append(f"{item}/")
                else:
                    items.append(item)
            
            if not items:
                return f"Directory {path} is empty"
            
            return "\n".join(items)
    
    def _handle_read_file(self, input: Dict[str, Any]) -> str:
        """Handle read_file tool."""
        file_path = input.get("file_path", "")
        offset = input.get("offset", 0)
        limit = input.get("limit", 500)
        
        resolved = self._resolve_path(file_path)
        
        if self.use_virtual_fs:
            if file_path not in self.virtual_fs:
                return f"File not found: {file_path}"
            content = self.virtual_fs[file_path]
        else:
            if not os.path.exists(resolved):
                return f"File not found: {file_path}"
            
            with open(resolved, "r", encoding="utf-8") as f:
                content = f.read()
        
        # Track that we've read this file
        self.files_read.add(file_path)
        
        # Apply pagination
        lines = content.split("\n")
        selected = lines[offset:offset + limit]
        
        # Format with line numbers
        result_lines = []
        for i, line in enumerate(selected, start=offset + 1):
            # Truncate long lines
            if len(line) > 2000:
                line = line[:2000] + "... (truncated)"
            result_lines.append(f"{i:6}|{line}")
        
        return "\n".join(result_lines)
    
    def _handle_write_file(self, input: Dict[str, Any]) -> str:
        """Handle write_file tool."""
        file_path = input.get("file_path", "")
        content = input.get("content", "")
        
        resolved = self._resolve_path(file_path)
        
        if self.use_virtual_fs:
            self.virtual_fs[file_path] = content
        else:
            # Create parent directories
            os.makedirs(os.path.dirname(resolved), exist_ok=True)
            
            with open(resolved, "w", encoding="utf-8") as f:
                f.write(content)
        
        lines = content.count("\n") + 1
        return f"✅ Successfully wrote {lines} lines to {file_path}"
    
    def _handle_edit_file(self, input: Dict[str, Any]) -> str:
        """Handle edit_file tool."""
        file_path = input.get("file_path", "")
        old_string = input.get("old_string", "")
        new_string = input.get("new_string", "")
        replace_all = input.get("replace_all", False)
        
        # Check if file was read
        if file_path not in self.files_read:
            return f"Error: You must read the file before editing it. Use read_file first."
        
        resolved = self._resolve_path(file_path)
        
        if self.use_virtual_fs:
            if file_path not in self.virtual_fs:
                return f"File not found: {file_path}"
            content = self.virtual_fs[file_path]
        else:
            if not os.path.exists(resolved):
                return f"File not found: {file_path}"
            
            with open(resolved, "r", encoding="utf-8") as f:
                content = f.read()
        
        # Check for match
        count = content.count(old_string)
        if count == 0:
            return f"Error: old_string not found in file"
        
        if count > 1 and not replace_all:
            return f"Error: old_string appears {count} times. Use replace_all=true or provide more context."
        
        # Perform replacement
        if replace_all:
            new_content = content.replace(old_string, new_string)
        else:
            new_content = content.replace(old_string, new_string, 1)
        
        # Write back
        if self.use_virtual_fs:
            self.virtual_fs[file_path] = new_content
        else:
            with open(resolved, "w", encoding="utf-8") as f:
                f.write(new_content)
        
        replaced = count if replace_all else 1
        return f"✅ Successfully replaced {replaced} occurrence(s) in {file_path}"
    
    def _handle_glob(self, input: Dict[str, Any]) -> str:
        """Handle glob tool."""
        pattern = input.get("pattern", "")
        base_path = input.get("path", "/")
        
        resolved = self._resolve_path(base_path)
        
        if self.use_virtual_fs:
            # Simple glob matching for virtual fs
            matches = []
            for p in self.virtual_fs.keys():
                if p.startswith(base_path):
                    # Very basic pattern matching
                    if pattern.endswith("*"):
                        if p.endswith(pattern[:-1].split("*")[-1]):
                            matches.append(p)
                    elif pattern in p:
                        matches.append(p)
            return "\n".join(sorted(matches)) if matches else "No files found matching pattern"
        else:
            # Real glob
            if not pattern.startswith("/") and not pattern.startswith("*"):
                full_pattern = os.path.join(resolved, "**", pattern)
            else:
                full_pattern = os.path.join(resolved, pattern.lstrip("/"))
            
            matches = glob_module.glob(full_pattern, recursive=True)
            
            # Convert back to workspace-relative paths
            result = []
            for m in matches:
                if m.startswith(self.workspace_path):
                    rel = m[len(self.workspace_path):]
                    result.append("/workspace" + rel)
                else:
                    result.append(m)
            
            return "\n".join(sorted(result)) if result else "No files found matching pattern"
    
    def _handle_grep(self, input: Dict[str, Any]) -> str:
        """Handle grep tool."""
        pattern = input.get("pattern", "")
        path = input.get("path") or "/"
        glob_pattern = input.get("glob")
        output_mode = input.get("output_mode", "files_with_matches")
        
        resolved = self._resolve_path(path)
        
        if self.use_virtual_fs:
            results = []
            for p, content in self.virtual_fs.items():
                if glob_pattern and not p.endswith(glob_pattern.replace("*", "")):
                    continue
                if pattern in content:
                    if output_mode == "files_with_matches":
                        results.append(p)
                    elif output_mode == "content":
                        for i, line in enumerate(content.split("\n"), 1):
                            if pattern in line:
                                results.append(f"{p}:{i}:{line}")
                    elif output_mode == "count":
                        count = content.count(pattern)
                        results.append(f"{p}:{count}")
            return "\n".join(results) if results else "No matches found"
        else:
            # Use subprocess grep for real filesystem
            cmd = ["grep", "-r"]
            
            if output_mode == "files_with_matches":
                cmd.append("-l")
            elif output_mode == "count":
                cmd.append("-c")
            else:
                cmd.append("-n")
            
            if glob_pattern:
                cmd.extend(["--include", glob_pattern])
            
            cmd.extend([pattern, resolved])
            
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                output = result.stdout.strip()
                
                # Convert paths
                if output:
                    lines = []
                    for line in output.split("\n"):
                        if self.workspace_path in line:
                            line = line.replace(self.workspace_path, "/workspace")
                        lines.append(line)
                    return "\n".join(lines)
                return "No matches found"
            except subprocess.TimeoutExpired:
                return "Error: grep timed out"
            except Exception as e:
                return f"Error: {str(e)}"
    
    def _handle_bash(self, input: Dict[str, Any]) -> str:
        """Handle bash tool."""
        command = input.get("command", "")
        timeout = input.get("timeout", 30)
        working_dir = input.get("working_directory")
        
        if self.use_virtual_fs:
            return "Error: bash not available in virtual filesystem mode"
        
        cwd = self._resolve_path(working_dir) if working_dir else self.workspace_path
        
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd
            )
            
            output = ""
            if result.stdout:
                output += result.stdout
            if result.stderr:
                if output:
                    output += "\n"
                output += f"[stderr]\n{result.stderr}"
            
            if result.returncode != 0:
                output += f"\n[Exit code: {result.returncode}]"
            
            return output.strip() if output else "(no output)"
        
        except subprocess.TimeoutExpired:
            return f"Error: Command timed out after {timeout} seconds"
        except Exception as e:
            return f"Error: {str(e)}"

