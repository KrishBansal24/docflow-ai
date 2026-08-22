import imaplib
import email
import logging
from email.header import decode_header
from config import get_settings
import re

logger = logging.getLogger(__name__)

class IMAPServiceError(Exception):
    pass

class IMAPService:
    def __init__(self) -> None:
        self.settings = get_settings()
        # Default to Gmail IMAP if SMTP is Gmail, otherwise assume the user will configure IMAP later.
        # Since this is an MVP for Gmail, we default to imap.gmail.com
        self.imap_host = "imap.gmail.com"
        
    def _is_configured(self) -> bool:
        return bool(self.settings.smtp_username and self.settings.smtp_password)

    def _connect(self) -> imaplib.IMAP4_SSL:
        if not self._is_configured():
            raise IMAPServiceError("IMAP credentials not configured. Please set SMTP_USERNAME and SMTP_PASSWORD.")
        
        try:
            mail = imaplib.IMAP4_SSL(self.imap_host)
            mail.login(self.settings.smtp_username, self.settings.smtp_password) # type: ignore
            return mail
        except Exception as exc:
            raise IMAPServiceError(f"Failed to connect to IMAP server: {exc}") from exc

    def extract_sender_email(self, from_header: str) -> str:
        """Extracts just the email address from a format like 'John Doe <john@example.com>'."""
        match = re.search(r'<([^>]+)>', str(from_header))
        if match:
            return match.group(1).strip()
        return str(from_header).strip()

    def fetch_unread_pdfs(self) -> list[dict]:
        """
        Connects to IMAP, searches for UNREAD emails, downloads PDF attachments, 
        marks them as read, and returns a list of dictionaries with sender and bytes.
        """
        if not self._is_configured():
            return []

        results = []
        try:
            mail = self._connect()
            mail.select("inbox")

            # Only fetch emails explicitly addressed to the +docflow alias
            # The search string MUST have explicit literal quotes around it to be parsed correctly by IMAP
            status, messages = mail.search(None, "UNSEEN", "TO", '"+docflow"')
            if status != "OK" or not messages[0]:
                mail.logout()
                return results
                
            for num in messages[0].split():
                status, msg_data = mail.fetch(num, "(RFC822)")
                if status != "OK":
                    continue
                    
                for response_part in msg_data:
                    if isinstance(response_part, tuple):
                        msg = email.message_from_bytes(response_part[1])
                        
                        # Double-check the To header on the client side just to be safe
                        to_header = str(msg.get("To", "")).lower()
                        if "+docflow" not in to_header:
                            continue
                            
                        sender = self.extract_sender_email(msg.get("From", "Unknown"))
                        
                        pdf_found = False
                        if msg.is_multipart():
                            for part in msg.walk():
                                content_type = part.get_content_type()
                                filename = part.get_filename()
                                
                                if filename and (content_type == "application/pdf" or filename.lower().endswith(".pdf")):
                                    pdf_bytes = part.get_payload(decode=True)
                                    if pdf_bytes:
                                        results.append({
                                            "sender": sender,
                                            "filename": filename,
                                            "content": pdf_bytes
                                        })
                                        pdf_found = True
                        
                        # Only mark as read if we actually processed it, or if it has no PDF maybe we just ignore it?
                        # Actually, let's mark it as read regardless so we don't get stuck in a loop parsing the same junk email.
                        mail.store(num, "+FLAGS", "\\Seen")

            mail.logout()
            return results
        except Exception as exc:
            logger.error(f"[IMAP] Polling error: {exc}")
            return results
