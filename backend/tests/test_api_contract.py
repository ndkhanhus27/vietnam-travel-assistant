import json
import unittest
from pydantic import ValidationError
from app.api.schemas import SendMessageRequest
from app.api.sse import encode_sse


class ApiContractTest(unittest.TestCase):
    def test_chat_payload_accepts_content_and_rejects_client_owned_history(self):
        self.assertEqual(SendMessageRequest.model_validate({"content": "Hue?"}).content, "Hue?")
        for payload in ({"content": ""}, {"content": "Hue?", "user_id": "another-user"},
                        {"content": "Hue?", "messages": []}):
            with self.assertRaises(ValidationError):
                SendMessageRequest.model_validate(payload)

    def test_sse_frames_match_frontend_event_data_contract(self):
        payload = {"stage": "planning", "message": "Preparing"}
        frame = encode_sse("stage", payload)
        if isinstance(frame, bytes):
            frame = frame.decode()
        self.assertTrue(frame.endswith("\n\n"))
        lines = frame.splitlines()
        self.assertEqual(lines[0], "event: stage")
        self.assertEqual(json.loads(lines[1].removeprefix("data: ")), payload)
