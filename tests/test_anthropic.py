"""Unit tests for the Anthropic Messages API shim."""

import json
import unittest
from bridge.anthropic import (
    anthropic_to_cloudcode_request,
    build_anthropic_message,
    build_anthropic_sse_events,
    build_anthropic_error_response,
)


class TestAnthropicRequestTranslation(unittest.TestCase):
    def test_valid_request_with_system_and_messages(self):
        payload = {
            "model": "gemini-2.5-pro",
            "system": "You are Claude.",
            "messages": [
                {"role": "user", "content": "Hello world"},
            ],
            "max_tokens": 1024,
            "temperature": 0.5,
        }
        model, contents, system_inst, gen_config = anthropic_to_cloudcode_request(
            payload, project="test-project"
        )
        self.assertEqual(model, "gemini-2.5-pro")
        self.assertEqual(system_inst, {"parts": [{"text": "You are Claude."}]})
        self.assertEqual(contents, [{"role": "user", "parts": [{"text": "Hello world"}]}])
        self.assertIsNotNone(gen_config)
        self.assertEqual(gen_config["maxOutputTokens"], 1024)
        self.assertEqual(gen_config["temperature"], 0.5)
        self.assertNotIn("thinkingConfig", gen_config)

    def test_system_as_content_blocks(self):
        payload = {
            "model": "gemini-2.5-pro",
            "system": [
                {"type": "text", "text": "First instruction."},
                {"type": "text", "text": "Second instruction."},
            ],
            "messages": [{"role": "user", "content": "Hi"}],
        }
        _, _, system_inst, _ = anthropic_to_cloudcode_request(payload, "test-project")
        self.assertEqual(
            system_inst,
            {"parts": [{"text": "First instruction.\nSecond instruction."}]},
        )

    def test_user_content_as_blocks_and_multi_turn(self):
        payload = {
            "model": "gemini-2.5-pro",
            "messages": [
                {"role": "user", "content": [{"type": "text", "text": "What is 2+2?"}]},
                {"role": "assistant", "content": [{"type": "text", "text": "It is 4."}]},
                {"role": "user", "content": "Thanks!"},
            ],
        }
        _, contents, _, _ = anthropic_to_cloudcode_request(payload, "test-project")
        self.assertEqual(len(contents), 3)
        self.assertEqual(contents[0]["role"], "user")
        self.assertEqual(contents[0]["parts"], [{"text": "What is 2+2?"}])
        self.assertEqual(contents[1]["role"], "model")
        self.assertEqual(contents[1]["parts"], [{"text": "It is 4."}])
        self.assertEqual(contents[2]["role"], "user")
        self.assertEqual(contents[2]["parts"], [{"text": "Thanks!"}])

    def test_tool_use_and_tool_result_content_blocks(self):
        payload = {
            "model": "gemini-2.5-pro",
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {"type": "tool_use", "id": "t1", "name": "get_weather", "input": {"location": "Paris"}},
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": "t1", "content": "Sunny, 22C"},
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": "t2", "content": {"temperature": 22}},
                    ],
                },
            ],
        }
        _, contents, _, _ = anthropic_to_cloudcode_request(payload, "test-project")
        # Starts with assistant turn, so "Hello" user turn prepended
        self.assertEqual(contents[0]["role"], "user")
        self.assertEqual(contents[0]["parts"], [{"text": "Hello"}])
        # Tool call
        self.assertEqual(contents[1]["role"], "model")
        self.assertEqual(contents[1]["parts"], [{"text": '[Tool Call]: get_weather({"location": "Paris"})'}])
        # Tool results merged or sequenced
        self.assertEqual(contents[2]["role"], "user")
        self.assertEqual(
            contents[2]["parts"],
            [
                {"text": "[Tool Result]: Sunny, 22C"},
                {"text": '[Tool Result]: {"temperature": 22}'},
            ],
        )

    def test_thinking_config_integration(self):
        # Reasoning model variant
        payload_high = {
            "model": "gemini-3.1-pro-high",
            "messages": [{"role": "user", "content": "Think deeply"}],
        }
        _, _, _, gen_config_high = anthropic_to_cloudcode_request(payload_high, "test-project")
        self.assertEqual(gen_config_high["thinkingConfig"], {"thinkingLevel": "HIGH"})

        # Explicit client thinking override
        payload_override = {
            "model": "gemini-3.1-pro-high",
            "messages": [{"role": "user", "content": "Think deeply"}],
            "thinking": {"type": "enabled", "budget_tokens": 4096},
        }
        _, _, _, gen_config_ovr = anthropic_to_cloudcode_request(payload_override, "test-project")
        self.assertEqual(gen_config_ovr["thinkingConfig"], {"thinkingBudget": 4096})

    def test_validation_missing_model_raises_value_error(self):
        with self.assertRaises(ValueError):
            anthropic_to_cloudcode_request({"messages": [{"role": "user", "content": "Hi"}]}, "p")

    def test_validation_missing_or_empty_messages_raises_value_error(self):
        with self.assertRaises(ValueError):
            anthropic_to_cloudcode_request({"model": "gemini-2.5-pro"}, "p")
        with self.assertRaises(ValueError):
            anthropic_to_cloudcode_request({"model": "gemini-2.5-pro", "messages": []}, "p")


class TestAnthropicResponseBuilder(unittest.TestCase):
    def test_build_anthropic_message_structure(self):
        resp = build_anthropic_message(
            message_id="msg_123456",
            model="gemini-2.5-pro",
            text="Hello from Claude shim",
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            stop_reason="end_turn",
        )
        self.assertEqual(resp["id"], "msg_123456")
        self.assertEqual(resp["type"], "message")
        self.assertEqual(resp["role"], "assistant")
        self.assertEqual(resp["model"], "gemini-2.5-pro")
        self.assertEqual(resp["content"], [{"type": "text", "text": "Hello from Claude shim"}])
        self.assertEqual(resp["stop_reason"], "end_turn")
        self.assertIsNone(resp["stop_sequence"])
        self.assertEqual(resp["usage"], {"input_tokens": 10, "output_tokens": 5})

    def test_build_anthropic_message_defaults(self):
        resp = build_anthropic_message(
            message_id="msg_abcdef",
            model="gemini-2.5-flash",
            text="Short answer",
        )
        self.assertEqual(resp["stop_reason"], "end_turn")
        self.assertEqual(resp["usage"], {"input_tokens": 0, "output_tokens": 0})

    def test_build_anthropic_message_content_filter_maps_to_end_turn(self):
        resp = build_anthropic_message(
            message_id="msg_filtered",
            model="gemini-2.5-flash",
            text="Blocked",
            stop_reason="content_filter",
        )
        self.assertEqual(resp["stop_reason"], "end_turn")


class TestAnthropicSSEEvents(unittest.TestCase):
    def test_build_anthropic_sse_events_sequence(self):
        mock_upstream_lines = [
            'data: {"candidates": [{"content": {"parts": [{"thought": true, "text": "hidden"}]}}]}\n',
            'data: {"candidates": [{"content": {"parts": [{"text": "Hello "}]}}]}\n',
            'data: {"candidates": [{"content": {"parts": [{"text": "world!"}]}}], "usageMetadata": {"promptTokenCount": 8, "candidatesTokenCount": 12, "totalTokenCount": 20}}\n',
            'data: {"candidates": [{"finishReason": "STOP"}]}\n',
        ]

        events = list(build_anthropic_sse_events(iter(mock_upstream_lines), "gemini-2.5-pro"))
        self.assertGreater(len(events), 0)

        # Parse SSE events into list of (event_name, data_dict)
        parsed_events = []
        for raw in events:
            lines = [l for l in raw.strip().split("\n") if l]
            event_name = None
            data_dict = None
            for l in lines:
                if l.startswith("event:"):
                    event_name = l[6:].strip()
                elif l.startswith("data:"):
                    data_dict = json.loads(l[5:].strip())
            if event_name and data_dict:
                parsed_events.append((event_name, data_dict))

        event_names = [e[0] for e in parsed_events]
        # Strict sequence: message_start, content_block_start, content_block_delta..., content_block_stop, message_delta, message_stop
        self.assertEqual(event_names[0], "message_start")
        self.assertEqual(event_names[1], "content_block_start")
        self.assertEqual(event_names[-3], "content_block_stop")
        self.assertEqual(event_names[-2], "message_delta")
        self.assertEqual(event_names[-1], "message_stop")

        # Verify message_start
        msg_start_data = parsed_events[0][1]
        self.assertEqual(msg_start_data["type"], "message_start")
        self.assertTrue(msg_start_data["message"]["id"].startswith("msg_"))
        self.assertEqual(msg_start_data["message"]["model"], "gemini-2.5-pro")

        # Verify text deltas exclude thoughts
        delta_texts = []
        for name, data in parsed_events:
            if name == "content_block_delta":
                self.assertEqual(data["delta"]["type"], "text_delta")
                delta_texts.append(data["delta"]["text"])
        self.assertEqual("".join(delta_texts), "Hello world!")

        # Verify message_delta has stop_reason and usage
        msg_delta_data = parsed_events[-2][1]
        self.assertEqual(msg_delta_data["type"], "message_delta")
        self.assertEqual(msg_delta_data["delta"]["stop_reason"], "end_turn")
        self.assertEqual(msg_delta_data["usage"]["output_tokens"], 12)

    def test_sse_events_content_filter_maps_to_end_turn(self):
        mock_upstream_lines = [
            'data: {"candidates": [{"finishReason": "SAFETY"}]}\n',
        ]
        events = list(build_anthropic_sse_events(iter(mock_upstream_lines), "gemini-2.5-pro"))
        delta_events = []
        for e in events:
            if "event: message_delta" in e:
                for line in e.strip().split("\n"):
                    if line.startswith("data:"):
                        delta_events.append(json.loads(line[5:].strip()))
        self.assertEqual(len(delta_events), 1)
        self.assertEqual(delta_events[0]["delta"]["stop_reason"], "end_turn")


class TestAnthropicErrorResponses(unittest.TestCase):
    def test_error_status_and_schema_mapping(self):
        code, err = build_anthropic_error_response(400, "Bad message format")
        self.assertEqual(code, 400)
        self.assertEqual(err["type"], "error")
        self.assertEqual(err["error"]["type"], "invalid_request_error")
        self.assertEqual(err["error"]["message"], "Bad message format")

        code, err = build_anthropic_error_response(401, "Invalid token")
        self.assertEqual(code, 401)
        self.assertEqual(err["error"]["type"], "authentication_error")

        code, err = build_anthropic_error_response(429, "Rate limit exceeded")
        self.assertEqual(code, 429)
        self.assertEqual(err["error"]["type"], "rate_limit_error")

        code, err = build_anthropic_error_response(503, "Service unavailable")
        self.assertEqual(code, 503)
        self.assertIn(err["error"]["type"], ("api_error", "overloaded_error"))


if __name__ == "__main__":
    unittest.main()
