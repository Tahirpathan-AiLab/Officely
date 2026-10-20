import subprocess
from backend.config import PROJECT_ROOT
from backend.tools.registry import registry, PermissionLevel, wrap_untrusted_data


def _run_git_command(args: list) -> str:
    try:
        res = subprocess.run(
            ["git"] + args,
            cwd=str(PROJECT_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=20
        )
        if res.returncode == 0:
            return res.stdout.strip() or "Success (no output)"
        return f"Git error (exit {res.returncode}): {res.stderr.strip()}"
    except Exception as e:
        return f"Execution error: {e}"


@registry.register(
    name="git_status",
    description="Check the current git branch and modified files status.",
    parameters={},
    permission_level=PermissionLevel.AUTO
)
def git_status() -> str:
    out = _run_git_command(["status", "--short"])
    return wrap_untrusted_data(out or "Clean working directory.")


@registry.register(
    name="get_repo_info",
    description="Get current git commit hash and remote repository URL.",
    parameters={},
    permission_level=PermissionLevel.AUTO
)
def get_repo_info() -> str:
    branch = _run_git_command(["rev-parse", "--abbrev-ref", "HEAD"])
    commit = _run_git_command(["rev-parse", "--short", "HEAD"])
    remote = _run_git_command(["remote", "get-url", "origin"])
    return wrap_untrusted_data(f"Branch: {branch}\nCommit: {commit}\nRemote: {remote}")


@registry.register(
    name="git_commit",
    description="Stage and commit changes to git repository. Dangerous: requires user confirmation.",
    parameters={"message": "string commit message"},
    permission_level=PermissionLevel.ASK_USER
)
def git_commit(message: str) -> str:
    _run_git_command(["add", "."])
    return _run_git_command(["commit", "-m", message])


@registry.register(
    name="git_push",
    description="Push committed changes to remote git repository. Dangerous: requires user confirmation.",
    parameters={},
    permission_level=PermissionLevel.ASK_USER
)
def git_push() -> str:
    return _run_git_command(["push"])
