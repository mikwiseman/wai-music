"""Email delivery for passwordless browser sign-in."""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from html import escape
from typing import Any, Protocol, cast


class EmailDeliveryError(RuntimeError):
    """Raised when a magic-link email cannot be delivered."""


class MagicLinkEmailSender(Protocol):
    def send_magic_link(
        self,
        *,
        recipient_email: str,
        magic_link: str,
        expires_in_minutes: int,
    ) -> None: ...


@dataclass(frozen=True)
class ResendMagicLinkEmailSender:
    api_key: str | None
    from_email: str | None

    def send_magic_link(
        self,
        *,
        recipient_email: str,
        magic_link: str,
        expires_in_minutes: int,
    ) -> None:
        if not self.api_key:
            raise EmailDeliveryError("RESEND_API_KEY is not configured.")
        if not self.from_email:
            raise EmailDeliveryError("WAI_MUSIC_MAGIC_LINK_FROM_EMAIL is not configured.")

        resend = cast(Any, importlib.import_module("resend"))
        resend.api_key = self.api_key
        try:
            response = resend.Emails.send(
                {
                    "from": self.from_email,
                    "to": [recipient_email],
                    "subject": "Sign in to wai-music",
                    "html": _magic_link_html(magic_link, expires_in_minutes),
                    "text": _magic_link_text(magic_link, expires_in_minutes),
                    "tags": [
                        {"name": "category", "value": "auth"},
                        {"name": "type", "value": "magic-link"},
                    ],
                }
            )
        except Exception as exc:
            raise EmailDeliveryError(f"Resend failed to send the magic link: {exc}") from exc
        message_id = (
            response.get("id") if isinstance(response, dict) else getattr(response, "id", None)
        )
        if not isinstance(message_id, str) or not message_id:
            raise EmailDeliveryError("Resend did not return an email id.")


def _magic_link_html(magic_link: str, expires_in_minutes: int) -> str:
    escaped_link = escape(magic_link, quote=True)
    return f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; line-height: 1.5; color: #17130f;">
      <h1 style="font-family: Georgia, serif; font-size: 32px; margin: 0 0 16px;">Sign in to wai-music</h1>
      <p>Use this secure link to open your wai-music account.</p>
      <p>
        <a href="{escaped_link}" style="display: inline-block; background: #064b47; color: #ffffff; padding: 12px 18px; border-radius: 8px; text-decoration: none; font-weight: 700;">
          Sign in
        </a>
      </p>
      <p style="color: #5c554c;">This link expires in {expires_in_minutes} minutes and can be used once.</p>
      <p style="word-break: break-all; color: #5c554c;">{escaped_link}</p>
    </div>
    """


def _magic_link_text(magic_link: str, expires_in_minutes: int) -> str:
    return (
        "Sign in to wai-music\n\n"
        f"Open this link to sign in: {magic_link}\n\n"
        f"This link expires in {expires_in_minutes} minutes and can be used once."
    )
