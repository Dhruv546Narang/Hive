"""
Hive CLI Tools
Tools that the LLM agent can invoke: read/write files, run commands,
search code, list directories.
"""

import os
import subprocess
import glob
from typing import Any

# ── Tool definitions (Ollama / OpenAI function-calling schema) ───────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the full contents of a file. Use this to understand existing code before making changes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative or absolute file path"}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create a new file or overwrite an existing file with the given content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to write to"},
                    "content": {"type": "string", "description": "Full file content to write"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Replace a specific substring in a file. Use this for targeted edits instead of rewriting the whole file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to edit"},
                    "old_text": {"type": "string", "description": "Exact text to find and replace"},
                    "new_text": {"type": "string", "description": "Replacement text"},
                },
                "required": ["path", "old_text", "new_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Execute a shell command and return its stdout and stderr. Use for running scripts, installing packages, git operations, etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to execute"},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "List files and subdirectories in a directory. Returns names with [DIR] or [FILE] prefix and file sizes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path (default: current directory)"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": "Search for a text pattern across files in a directory. Returns matching file paths and line numbers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Text or regex pattern to search for"},
                    "path": {"type": "string", "description": "Directory to search in (default: current directory)"},
                    "file_pattern": {"type": "string", "description": "Glob pattern to filter files, e.g. '*.py' (default: all files)"},
                },
                "required": ["query"],
            },
        },
    },
]


# ── Tool executors ───────────────────────────────────────────────────────

def _resolve_path(path: str, cwd: str) -> str:
    """Resolve a relative path against the working directory."""
    if os.path.isabs(path):
        return path
    return os.path.normpath(os.path.join(cwd, path))


def read_file(args: dict, cwd: str) -> str:
    path = _resolve_path(args["path"], cwd)
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        lines = content.count("\n") + 1
        return f"[{lines} lines]\n{content}"
    except FileNotFoundError:
        return f"Error: File not found: {path}"
    except Exception as e:
        return f"Error reading file: {e}"


def write_file(args: dict, cwd: str) -> str:
    path = _resolve_path(args["path"], cwd)
    content = args.get("content", "")
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        lines = content.count("\n") + 1
        return f"Wrote {lines} lines to {path}"
    except Exception as e:
        return f"Error writing file: {e}"


def edit_file(args: dict, cwd: str) -> str:
    path = _resolve_path(args["path"], cwd)
    old_text = args.get("old_text", "")
    new_text = args.get("new_text", "")
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        if old_text not in content:
            return f"Error: Could not find the specified text in {path}"
        count = content.count(old_text)
        content = content.replace(old_text, new_text, 1)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Edited {path} (replaced 1 of {count} occurrence(s))"
    except FileNotFoundError:
        return f"Error: File not found: {path}"
    except Exception as e:
        return f"Error editing file: {e}"


def run_command(args: dict, cwd: str) -> str:
    command = args.get("command", "")
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = ""
        if result.stdout:
            output += result.stdout
        if result.stderr:
            output += ("\n" if output else "") + result.stderr
        if not output:
            output = "(no output)"
        exit_info = f"[exit code: {result.returncode}]"
        # Truncate very long output
        if len(output) > 8000:
            output = output[:4000] + "\n... (truncated) ...\n" + output[-4000:]
        return f"{exit_info}\n{output}"
    except subprocess.TimeoutExpired:
        return "Error: Command timed out after 30 seconds"
    except Exception as e:
        return f"Error running command: {e}"


def list_directory(args: dict, cwd: str) -> str:
    path = _resolve_path(args.get("path", "."), cwd)
    try:
        entries = []
        for name in sorted(os.listdir(path)):
            full = os.path.join(path, name)
            if os.path.isdir(full):
                count = sum(1 for _ in os.scandir(full))
                entries.append(f"  [DIR]  {name}/  ({count} items)")
            else:
                size = os.path.getsize(full)
                if size < 1024:
                    sz = f"{size} B"
                elif size < 1024 * 1024:
                    sz = f"{size / 1024:.1f} KB"
                else:
                    sz = f"{size / (1024*1024):.1f} MB"
                entries.append(f"  [FILE] {name}  ({sz})")
        if not entries:
            return f"{path}: (empty directory)"
        return f"{path}:\n" + "\n".join(entries)
    except FileNotFoundError:
        return f"Error: Directory not found: {path}"
    except Exception as e:
        return f"Error listing directory: {e}"


def search_files(args: dict, cwd: str) -> str:
    query = args.get("query", "")
    path = _resolve_path(args.get("path", "."), cwd)
    file_pattern = args.get("file_pattern", "*")

    matches = []
    try:
        for root, dirs, files in os.walk(path):
            # Skip common noise directories
            dirs[:] = [d for d in dirs if d not in {
                ".git", "node_modules", "__pycache__", ".venv", "venv",
                ".next", "dist", "build", ".egg-info",
            }]
            for fname in files:
                if file_pattern != "*" and not glob.fnmatch.fnmatch(fname, file_pattern):
                    continue
                fpath = os.path.join(root, fname)
                try:
                    with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                        for i, line in enumerate(f, 1):
                            if query in line:
                                rel = os.path.relpath(fpath, cwd)
                                matches.append(f"  {rel}:{i}: {line.rstrip()}")
                                if len(matches) >= 50:
                                    matches.append("  ... (50 match limit reached)")
                                    return "\n".join(matches)
                except (PermissionError, OSError):
                    continue
    except Exception as e:
        return f"Error searching: {e}"

    if not matches:
        return f"No matches found for '{query}'"
    return "\n".join(matches)


# ── Dispatcher ───────────────────────────────────────────────────────────

EXECUTORS = {
    "read_file": read_file,
    "write_file": write_file,
    "edit_file": edit_file,
    "run_command": run_command,
    "list_directory": list_directory,
    "search_files": search_files,
}


def execute_tool(name: str, arguments: dict, cwd: str) -> str:
    """Execute a tool by name and return the result string."""
    executor = EXECUTORS.get(name)
    if not executor:
        return f"Error: Unknown tool '{name}'"
    return executor(arguments, cwd)
