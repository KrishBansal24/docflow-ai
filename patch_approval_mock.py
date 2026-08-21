import os
import glob

for test_file in glob.glob("tests/test_*.py"):
    with open(test_file, 'r') as f:
        content = f.read()
    
    # Add mock for ApprovalNotionService to test_phase4, test_phase5, test_pdf_extraction
    if 'ApprovalNotionService' not in content and 'mock_approval' not in content and 'services.document_service' in content:
        content = content.replace(
            'self.run_log_patcher.start()',
            'self.run_log_patcher.start()\n        \n        self.mock_approval_notion = MagicMock()\n        self.mock_approval_notion.check_existing_approval = AsyncMock(return_value=None)\n        self.approval_patcher = patch("services.approval_service.ApprovalNotionService", return_value=self.mock_approval_notion)\n        self.approval_patcher.start()'
        )
        content = content.replace(
            'self.run_log_patcher.stop()',
            'self.run_log_patcher.stop()\n        self.approval_patcher.stop()'
        )
        with open(test_file, 'w') as f:
            f.write(content)
