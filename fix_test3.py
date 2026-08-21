import sys
with open('tests/test_phase3.py', 'r') as f:
    content = f.read()

content = content.replace('from services.notion_service import NotionService', 'from services.notion import DocumentNotionService\nfrom unittest.mock import MagicMock')

content = content.replace('main.DocumentService', 'api.documents.DocumentService')

content = content.replace('''    def test_duplicate_query_uses_exact_file_hash_filter(self) -> None:
        service = object.__new__(NotionService)
        service.settings = SimpleNamespace(document_inbox_id="database-id")
        service._get_data_source = AsyncMock(return_value=DOCUMENT_INBOX_SCHEMA)
        service._request = AsyncMock(return_value={"results": []})

        result = asyncio.run(service.check_duplicate_document("a" * 64))

        self.assertEqual(result, {"is_duplicate": False})
        request_json = service._request.call_args.kwargs["json"]
        self.assertEqual(request_json["filter"]["property"], "File Hash")
        self.assertEqual(request_json["filter"]["rich_text"]["equals"], "a" * 64)''', '''    def test_duplicate_query_uses_exact_file_hash_filter(self) -> None:
        service = DocumentNotionService()
        service.client = MagicMock()
        service.client.settings = SimpleNamespace(document_inbox_id="database-id")
        service.client._get_data_source = AsyncMock(return_value=DOCUMENT_INBOX_SCHEMA)
        service.client._request = AsyncMock(return_value={"results": []})

        result = asyncio.run(service.check_duplicate_document("a" * 64))

        self.assertFalse(result["is_duplicate"])
        service.client._request.assert_called_once()
        request_json = service.client._request.call_args.kwargs["json"]
        self.assertEqual(request_json["filter"]["property"], "File Hash")
        self.assertEqual(request_json["filter"]["rich_text"]["equals"], "a" * 64)''')

content = content.replace('main.documents_router', 'import api.documents\n        api.documents.DocumentService')

with open('tests/test_phase3.py', 'w') as f:
    f.write(content)
