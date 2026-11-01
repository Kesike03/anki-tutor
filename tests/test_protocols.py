import unittest

from protocols import DEFAULTS, ProtocolError, build_request, parse_response, provider_error


class ProtocolTests(unittest.TestCase):
    def config(self, mode):
        host, path, model = DEFAULTS[mode]
        return {
            "api_mode": mode,
            "api_key": "test-secret",
            "api_host": host,
            "api_path": path,
            "model": model,
        }

    def test_chat_completions(self):
        spec = build_request(self.config("chat"), "card context", [{"role": "user", "content": "Why?"}])
        self.assertEqual(spec.url, "https://api.openai.com/v1/chat/completions")
        self.assertEqual(spec.headers["Authorization"], "Bearer test-secret")
        self.assertEqual(spec.body["messages"][0], {"role": "system", "content": "card context"})
        self.assertEqual(parse_response("chat", {"choices": [{"message": {"content": "Because."}}]}), "Because.")

    def test_responses(self):
        turns = [{"role": "user", "content": "First"}, {"role": "assistant", "content": "Second"}]
        spec = build_request(self.config("responses"), "card context", turns)
        self.assertEqual(spec.body["instructions"], "card context")
        self.assertEqual(spec.body["input"], turns)
        output = {"output": [
            {"type": "reasoning", "content": []},
            {"type": "message", "content": [{"type": "output_text", "text": "Part one"}, {"type": "output_text", "text": "Part two"}]},
        ]}
        self.assertEqual(parse_response("responses", output), "Part one\nPart two")

    def test_claude(self):
        spec = build_request(self.config("claude"), "card context", [{"role": "user", "content": "Hi"}])
        self.assertEqual(spec.url, "https://api.anthropic.com/v1/messages")
        self.assertEqual(spec.headers["x-api-key"], "test-secret")
        self.assertEqual(spec.headers["anthropic-version"], "2023-06-01")
        self.assertEqual(spec.body["system"], "card context")
        self.assertEqual(parse_response("claude", {"content": [{"type": "thinking", "thinking": "hidden"}, {"type": "text", "text": "Hello"}]}), "Hello")

    def test_gemini(self):
        config = self.config("gemini")
        config["model"] = "custom/model"
        turns = [{"role": "user", "content": "Hi"}, {"role": "assistant", "content": "Hello"}]
        spec = build_request(config, "card context", turns)
        self.assertIn("/custom%2Fmodel:generateContent", spec.url)
        self.assertEqual(spec.headers["x-goog-api-key"], "test-secret")
        self.assertEqual(spec.body["systemInstruction"]["parts"][0]["text"], "card context")
        self.assertEqual(spec.body["contents"][1]["role"], "model")
        self.assertEqual(parse_response("gemini", {"candidates": [{"content": {"parts": [{"text": "Hello"}]}}]}), "Hello")

    def test_full_endpoint_is_not_appended_twice(self):
        config = self.config("chat")
        config["api_host"] += "/chat/completions"
        self.assertEqual(build_request(config, "prompt", []).url, config["api_host"])

    def test_images_are_attached_in_each_provider_format(self):
        image = {"name": "card.png", "mime": "image/png", "data": "cGljdHVyZQ=="}
        turns = [{"role": "user", "content": "What does this show?"}]
        chat = build_request(self.config("chat"), "prompt", turns, [image]).body["messages"]
        self.assertEqual(chat[0]["role"], "system")
        self.assertEqual(chat[1]["content"][1]["image_url"]["url"], "data:image/png;base64,cGljdHVyZQ==")
        self.assertEqual(chat[2], turns[0])

        responses = build_request(self.config("responses"), "prompt", turns, [image]).body["input"]
        self.assertEqual(responses[0]["content"][1]["type"], "input_image")
        self.assertEqual(responses[1], turns[0])

        claude = build_request(self.config("claude"), "prompt", turns, [image]).body["messages"]
        self.assertEqual(claude[0]["content"][1]["source"]["data"], image["data"])
        self.assertEqual(claude[1], turns[0])

        gemini = build_request(self.config("gemini"), "prompt", turns, [image]).body["contents"]
        self.assertEqual(gemini[0]["parts"][1]["inlineData"]["mimeType"], "image/png")
        self.assertEqual(gemini[1]["parts"][0]["text"], turns[0]["content"])

    def test_user_attachments_follow_the_message_across_providers(self):
        attachments = [
            {"name": "diagram.png", "kind": "image", "mime": "image/png", "data": "cGljdHVyZQ=="},
            {"name": "notes.txt", "kind": "text", "mime": "text/plain", "data": "aGVsbG8="},
        ]
        turns = [{"role": "user", "content": "Explain", "attachments": attachments}]
        for mode in DEFAULTS:
            spec = build_request(self.config(mode), "prompt", turns)
            body = spec.body["contents"] if mode == "gemini" else spec.body["input"] if mode == "responses" else spec.body["messages"]
            self.assertIn("hello", str(body))
            self.assertIn("cGljdHVyZQ==", str(body))
        pdf_turn = [{"role": "user", "content": "Read", "attachments": [
            {"name": "doc.pdf", "kind": "pdf", "mime": "application/pdf", "data": "cGRm"}
        ]}]
        with self.assertRaisesRegex(ProtocolError, "pdf_not_supported"):
            build_request(self.config("chat"), "prompt", pdf_turn)
        for mode in ("responses", "claude", "gemini"):
            self.assertIn("cGRm", str(build_request(self.config(mode), "prompt", pdf_turn).body))

    def test_invalid_settings_and_responses(self):
        config = self.config("chat")
        config["api_key"] = ""
        with self.assertRaisesRegex(ProtocolError, "missing_key"):
            build_request(config, "prompt", [])
        config["api_key"] = "test-secret"
        config["api_host"] = "ftp://example.com"
        with self.assertRaisesRegex(ProtocolError, "invalid_host"):
            build_request(config, "prompt", [])
        with self.assertRaisesRegex(ProtocolError, "invalid_response"):
            parse_response("chat", {})
        with self.assertRaisesRegex(ProtocolError, "empty_response"):
            parse_response("responses", {"output": []})
        self.assertEqual(provider_error(401, {"error": {"message": "Unauthorized"}}), "HTTP 401: Unauthorized")


if __name__ == "__main__":
    unittest.main()
