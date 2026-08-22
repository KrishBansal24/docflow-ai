"""Service for interacting with the Notion Routing Directory database."""

import logging
from typing import Any

from .client import NotionClient, NotionServiceError

logger = logging.getLogger(__name__)


class DirectoryNotionService:
    def __init__(self, client: NotionClient | None = None) -> None:
        self.client = client or NotionClient()

    async def get_department_routing(self) -> dict[str, dict[str, list[str]]]:
        """Fetch all routing rules from the Notion database.
        
        Returns:
            A dictionary mapping department names to a dictionary containing
            their respective emails and whatsapp numbers.
            Example:
            {
                "Finance": {
                    "emails": ["finance@example.com"],
                    "whatsapp": ["whatsapp:+14155238886"]
                }
            }
        """
        routing_db_id = self.client.settings.routing_directory_id
        if not routing_db_id:
            logger.warning("[ROUTING] ROUTING_DIRECTORY_ID is not configured. Routing will rely on fallbacks.")
            return {}

        try:
            routing_source = await self.client._get_data_source(routing_db_id)
            response = await self.client._request("POST", f"/data_sources/{routing_source['id']}/query")
            results = response.get("results", [])
            
            mapping: dict[str, dict[str, list[str]]] = {}
            
            for page in results:
                props = page.get("properties", {})
                
                # Extract Department (Title property)
                dept_prop = props.get("Department", {}).get("title", [])
                department = "".join(t.get("plain_text", "") for t in dept_prop).strip()
                
                if not department:
                    continue
                    
                # Extract Email
                email_prop = props.get("Email Address", {})
                email = email_prop.get("email") if email_prop.get("type") == "email" else None
                if not email and email_prop.get("type") == "rich_text":
                    rt = email_prop.get("rich_text", [])
                    email = "".join(t.get("plain_text", "") for t in rt).strip()
                
                # Extract WhatsApp Number
                wa_prop = props.get("WhatsApp Number", {})
                whatsapp = wa_prop.get("phone_number") if wa_prop.get("type") == "phone_number" else None
                if not whatsapp and wa_prop.get("type") == "rich_text":
                    rt = wa_prop.get("rich_text", [])
                    whatsapp = "".join(t.get("plain_text", "") for t in rt).strip()
                    
                if department not in mapping:
                    mapping[department] = {"emails": [], "whatsapp": []}
                    
                if email:
                    mapping[department]["emails"].append(email)
                if whatsapp:
                    # Format for twilio if not already
                    if not whatsapp.startswith("whatsapp:"):
                        whatsapp = f"whatsapp:{whatsapp}"
                    mapping[department]["whatsapp"].append(whatsapp)
                    
            return mapping
            
        except NotionServiceError as exc:
            logger.error("[ROUTING] Failed to query Routing Directory: %s", exc)
            return {}
