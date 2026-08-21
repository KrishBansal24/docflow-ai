import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from main import app
from models.approval import ApprovalDecision
from models.workflow import ProcessingStatus, DecisionStatus

class TestPhase6(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    @patch("main.approval_service")
    def test_get_pending_approvals(self, mock_approval_service):
        mock_approval_service.get_pending_approvals = AsyncMock(return_value=[
            {
                "approval_id": "app-123",
                "document_id": "doc-123",
                "document_name": "Invoice.pdf",
                "status": "Pending Approval",
                "reason": "AI Confidence Low",
                "created_at": "2024-01-01T00:00:00Z"
            }
        ])

        response = self.client.get("/approvals")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("approvals", data)
        self.assertEqual(len(data["approvals"]), 1)
        self.assertEqual(data["approvals"][0]["approval_id"], "app-123")
        self.assertEqual(data["approvals"][0]["document_id"], "doc-123")

    @patch("main.approval_service")
    def test_submit_approval_decision(self, mock_approval_service):
        mock_approval_service.submit_decision = AsyncMock(return_value={
            "success": True,
            "approval_id": "app-123",
            "decision": "Approved"
        })

        payload = {
            "decision": "Approved",
            "reviewer_notes": "Looks good."
        }
        
        response = self.client.post("/approvals/app-123/decision", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["decision"], "Approved")

        # Verify service call
        mock_approval_service.submit_decision.assert_called_once_with(
            approval_id="app-123",
            decision="Approved",
            notes="Looks good."
        )

if __name__ == "__main__":
    unittest.main()
