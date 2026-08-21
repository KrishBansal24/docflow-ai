import os
import glob

for test_file in glob.glob("tests/test_*.py"):
    with open(test_file, 'r') as f:
        content = f.read()
    
    if 'self.mock_approval_notion = MagicMock()' in content:
        content = content.replace(
            'self.mock_approval_notion = MagicMock()\n        self.mock_approval_notion.check_existing_approval = AsyncMock(return_value=None)',
            'self.mock_approval_notion = MagicMock()\n        self.mock_approval_notion.check_existing_approval = AsyncMock(return_value=None)\n        self.mock_approval_notion.create_approval_entry = AsyncMock(return_value={"id": "fake-approval-id"})\n        self.mock_approval_notion.update_approval_decision = AsyncMock(return_value={"id": "fake-approval-id"})'
        )
        with open(test_file, 'w') as f:
            f.write(content)
