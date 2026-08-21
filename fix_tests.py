import os

# fix test_phase3.py
with open('tests/test_phase3.py', 'r') as f:
    t3 = f.read()

t3 = t3.replace('api.documents.DocumentService = self.original_document_service', 'import api.documents\n        api.documents.DocumentService = self.original_document_service')
with open('tests/test_phase3.py', 'w') as f:
    f.write(t3)

# The mock patches in test_phase4, test_phase5 and test_pdf_extraction need to mock pi.documents.DocumentService properly
# Wait, they mock services.document_service.DocumentNotionService. Let's check 	est_phase5.py.
