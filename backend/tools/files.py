import os
from pathlib import Path
from backend.config import PROJECT_ROOT, settings
from backend.tools.registry import registry, PermissionLevel, wrap_untrusted_data


def _resolve_safe_path(p: str) -> Path:
    base = Path(settings.security.safe_working_directory).resolve()
    target = (base / p).resolve() if not Path(p).is_absolute() else Path(p).resolve()
    # Check if target is inside base or workspace
    if not str(target).startswith(str(base)):
        raise PermissionError(f"Access denied: Path '{target}' is outside safe workspace '{base}'")
    return target


@registry.register(
    name="read_file",
    description="Read content from a file inside the project workspace.",
    parameters={"path": "string path to file", "max_chars": "optional integer limit (default 8000)"},
    permission_level=PermissionLevel.AUTO
)
def read_file(path: str, max_chars: int = 8000) -> str:
    target = _resolve_safe_path(path)
    if not target.exists() or not target.is_file():
        return f"Error: File not found at {path}"
    try:
        content = target.read_text(encoding="utf-8", errors="replace")
        if len(content) > max_chars:
            content = content[:max_chars] + f"\n... [Truncated. Showing first {max_chars} characters]"
        return wrap_untrusted_data(content)
    except Exception as e:
        return f"Error reading file: {e}"


@registry.register(
    name="list_directory",
    description="List files and folders in a specified project directory.",
    parameters={"path": "string path to directory (default '.')"},
    permission_level=PermissionLevel.AUTO
)
def list_directory(path: str = ".") -> str:
    try:
        target = _resolve_safe_path(path)
        if not target.exists() or not target.is_dir():
            return f"Error: Directory not found at {path}"
        
        entries = []
        for item in sorted(target.iterdir()):
            if item.name.startswith(".") and item.name not in [".env", ".gitignore"]:
                continue
            kind = "DIR" if item.is_dir() else "FILE"
            size = item.stat().st_size if item.is_file() else "-"
            entries.append(f"[{kind}] {item.name} ({size} bytes)")
        
        return "\n".join(entries) if entries else "Directory is empty."
    except Exception as e:
        return f"Error listing directory: {e}"


@registry.register(
    name="write_file",
    description="Write or overwrite text content to a file inside the project workspace.",
    parameters={"path": "string relative path", "content": "string text content to write"},
    permission_level=PermissionLevel.AUTO
)
def write_file(path: str, content: str) -> str:
    try:
        target = _resolve_safe_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"Successfully wrote {len(content)} characters to {target.name}"
    except Exception as e:
        return f"Error writing to file: {e}"


@registry.register(
    name="delete_file",
    description="Permanently delete a file from the project workspace. Dangerous: requires user confirmation.",
    parameters={"path": "string relative path to file"},
    permission_level=PermissionLevel.ASK_USER
)
def delete_file(path: str) -> str:
    try:
        target = _resolve_safe_path(path)
        if not target.exists():
            return f"File does not exist: {path}"
        if target.is_dir():
            return f"Cannot delete directory using delete_file: {path}"
        target.unlink()
        return f"Successfully deleted file: {path}"
    except Exception as e:
        return f"Error deleting file: {e}"
