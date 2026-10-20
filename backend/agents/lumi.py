from backend.agents.base import BaseAgent


class LumiAgent(BaseAgent):
    """
    Lumi: Software Engineer & Implementation Specialist (Lavender #b99be6).
    Focuses on executable logic, file operations, codebase inspection, testing, and debugging.
    """

    def __init__(self):
        super().__init__(
            name="Lumi",
            role="Software Engineering, Logic Implementation & File Processing",
            prompt_filename="lumi.md",
            allowed_tools=["read_file", "write_file", "delete_file", "list_directory", "git_status", "get_repo_info"]
        )


lumi_agent = LumiAgent()
