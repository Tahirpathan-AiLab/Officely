from backend.tools.registry import registry, PermissionLevel, wrap_untrusted_data
from backend.security.secrets import SecretManager


@registry.register(
    name="list_drive_files",
    description="List files in connected Google Drive.",
    parameters={"query": "optional search query"},
    permission_level=PermissionLevel.AUTO
)
def list_drive_files(query: str = "") -> str:
    token = SecretManager.get_secret("GOOGLE_DRIVE_TOKEN")
    if not token:
        return wrap_untrusted_data("Google Drive is not connected. Please connect your Google account in Plugins tab.")
    return wrap_untrusted_data(f"Google Drive search '{query}': No external files synced yet.")
