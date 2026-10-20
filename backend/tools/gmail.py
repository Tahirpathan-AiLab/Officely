from backend.tools.registry import registry, PermissionLevel, wrap_untrusted_data
from backend.security.secrets import SecretManager


@registry.register(
    name="read_recent_emails",
    description="Fetch recent email headers or messages (requires Gmail integration).",
    parameters={"limit": "optional integer count (default 5)"},
    permission_level=PermissionLevel.AUTO
)
def read_recent_emails(limit: int = 5) -> str:
    token = SecretManager.get_secret("GMAIL_TOKEN")
    if not token:
        return wrap_untrusted_data("Gmail is not connected. Please connect your Google account in Plugins tab.")
    return wrap_untrusted_data(f"Retrieved {limit} mock emails from inbox.")


@registry.register(
    name="send_email",
    description="Send an email to a recipient. Dangerous: requires explicit user confirmation.",
    parameters={
        "recipient": "string email address",
        "subject": "string subject line",
        "body": "string message body"
    },
    permission_level=PermissionLevel.ASK_USER
)
def send_email(recipient: str, subject: str, body: str) -> str:
    token = SecretManager.get_secret("GMAIL_TOKEN")
    if not token:
        return "Gmail is not connected. Connect in Plugins tab."
    return f"Email queued to {recipient} with subject '{subject}'"
