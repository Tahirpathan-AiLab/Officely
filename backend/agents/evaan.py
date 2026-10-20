from backend.agents.base import BaseAgent


class EvaanAgent(BaseAgent):
    """
    Evaan: Designer & Creative Lead (Sky Blue #9fd3e6).
    Focuses on colors, visual styles, fonts, brand copy, and user interface aesthetics.
    """

    def __init__(self):
        super().__init__(
            name="Evaan",
            role="UI/UX Design, Visual Styling & Creative Direction",
            prompt_filename="evaan.md",
            allowed_tools=["read_file", "write_file", "search_web"]
        )


evaan_agent = EvaanAgent()
