import urllib.request
import urllib.parse
from bs4 import BeautifulSoup
from backend.tools.registry import registry, PermissionLevel, wrap_untrusted_data


@registry.register(
    name="fetch_web_page",
    description="Fetch and extract readable plain text content from a web URL.",
    parameters={"url": "string valid HTTP or HTTPS URL", "max_chars": "optional limit (default 6000)"},
    permission_level=PermissionLevel.AUTO
)
def fetch_web_page(url: str, max_chars: int = 6000) -> str:
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (RoboNest Agentic Browser)"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        
        soup = BeautifulSoup(html, "html.parser")
        # Remove script and style tags
        for element in soup(["script", "style", "nav", "footer"]):
            element.extract()
        
        text = " ".join(soup.stripped_strings)
        if len(text) > max_chars:
            text = text[:max_chars] + f"\n... [Truncated. Showing first {max_chars} chars]"
        return wrap_untrusted_data(text)
    except Exception as e:
        return f"Error fetching web page: {e}"


@registry.register(
    name="search_web",
    description="Search the web for documentation or technical references.",
    parameters={"query": "string search query keywords"},
    permission_level=PermissionLevel.AUTO
)
def search_web(query: str) -> str:
    # Safe mock search / fallback returning structured guidance
    return wrap_untrusted_data(
        f"Search results for '{query}':\n"
        f"- Result 1: Official reference for {query} - Best practices and usage.\n"
        f"- Result 2: Documentation overview: setup, integration, API methods."
    )
