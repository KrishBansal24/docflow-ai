import sys
with open('tests/test_phase3.py', 'r') as f:
    content = f.read()

content = content.replace('self.original_document_service = api.documents.DocumentService', 'import api.documents\n        self.original_document_service = api.documents.DocumentService')

with open('tests/test_phase3.py', 'w') as f:
    f.write(content)
