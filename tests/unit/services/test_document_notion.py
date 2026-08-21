import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from services.notion import DocumentNotionService

DOCUMENT_INBOX_SCHEMA = {
    "id": "source-id",
    "properties": {
        "File Hash": {"type": "rich_text"},
        "Document Name": {"type": "title"},
        "Processing Status": {"type": "status", "status": {"options": [{"name": "Processing"}]}},
        "Decision Status": {"type": "status", "status": {"options": [{"name": "Pending Decision"}]}},
    },
}

class TestDocumentNotionUnit(unittest.IsolatedAsyncioTestCase):
    async def test_duplicate_query_uses_exact_file_hash_filter(self) -> None:
        service = DocumentNotionService()
        service.client = MagicMock()
        service.client.settings = SimpleNamespace(document_inbox_id="database-id")
        service.client._get_data_source = AsyncMock(return_value=DOCUMENT_INBOX_SCHEMA)
        service.client._request = AsyncMock(return_value={"results": []})

        result = await service.check_duplicate_document("a" * 64)

        self.assertFalse(result["is_duplicate"])
        service.client._request.assert_called_once()
        request_json = service.client._request.call_args.kwargs["json"]
        self.assertEqual(request_json["filter"]["property"], "File Hash")
        self.assertEqual(request_json["filter"]["rich_text"]["equals"], "a" * 64)

if __name__ == "__main__":
    unittest.main()
