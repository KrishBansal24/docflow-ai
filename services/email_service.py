import logging
import smtplib
from email.message import EmailMessage

from config import get_settings


logger = logging.getLogger(__name__)


class EmailServiceError(Exception):
    """Exception raised for errors in the EmailService."""
    pass


class EmailService:
    def __init__(self) -> None:
        self.settings = get_settings()
        
    def _is_configured(self) -> bool:
        """Check if SMTP credentials are fully provided."""
        return bool(self.settings.smtp_username and self.settings.smtp_password)

    def _send_email(self, to_email: str, subject: str, content: str) -> None:
        """Core method to dispatch an email via SMTP."""
        if not self._is_configured():
            logger.warning("Email service is not configured. Skipping email send.")
            return

        msg = EmailMessage()
        msg.set_content(content)
        msg["Subject"] = subject
        msg["From"] = self.settings.smtp_from_email or self.settings.smtp_username
        msg["To"] = to_email

        try:
            with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port) as server:
                server.starttls()
                server.login(self.settings.smtp_username, self.settings.smtp_password)  # type: ignore
                server.send_message(msg)
            logger.info(f"Successfully sent email to {to_email} with subject '{subject}'")
        except Exception as exc:
            logger.error(f"Failed to send email to {to_email}: {exc}")
            raise EmailServiceError(f"Email dispatch failed: {exc}") from exc

    def send_approval_notification(self, recipient_email: str, document_name: str, approval_notes: str | None) -> None:
        """Send an email when a document is successfully approved."""
        subject = f"Document Approved: {document_name}"
        content = f"Hello,\n\nThe document '{document_name}' has been approved and is ready for payment/processing.\n\n"
        if approval_notes:
            content += f"Reviewer Notes:\n{approval_notes}\n\n"
        content += "Thank you,\nDocFlow AI Workflow"
        
        self._send_email(recipient_email, subject, content)

    def send_correction_notification(self, recipient_email: str, document_name: str, correction_notes: str | None) -> None:
        """Send an email requesting clarification or correction for a document."""
        subject = f"Action Required: Correction Needed for {document_name}"
        content = f"Hello,\n\nThe document '{document_name}' requires your attention before it can be processed.\n\n"
        if correction_notes:
            content += f"Reviewer Notes (Please address these issues):\n{correction_notes}\n\n"
        else:
            content += "Please review the document and submit any necessary corrections.\n\n"
        content += "Thank you,\nDocFlow AI Workflow"
        
        self._send_email(recipient_email, subject, content)
