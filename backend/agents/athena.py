from backend.agents.base import BaseAgent


class AthenaAgent(BaseAgent):
    """
    Athena: Architect & Structural Layout Lead (Rose/Pink #f08a9d).
    Focuses on layout wireframes, HTML skeletons, database schemas, and modular system design.
    """

    def __init__(self):
        super().__init__(
            name="Athena",
            role="System Architecture, Structural Wireframes & Layout Skeletons",
            prompt_filename="athena.md",
            allowed_tools=["read_file", "write_file", "list_directory"]
        )


athena_agent = AthenaAgent()
