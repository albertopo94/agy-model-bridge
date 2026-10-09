"""Unit tests for StreamEvent intermediate representation and unified parser."""

import unittest
from bridge.errors import (
    AuthenticationError,
    BridgeError,
    CapacityExhaustedError,
    ForbiddenError,
    InvalidRequestError,
    ModelNotFoundError,
    RateLimitError,
)
from bridge.events import (
    StreamEvent,
    ToolCallDelta,
    Usage,
    parse_stream_event,
)


class TestStreamEventIR(unittest.TestCase):
    """Tests for ToolCallDelta, Usage, and StreamEvent data structures."""

    def test_tool_call_delta_defaults_and_to_dict(self):
        tc = ToolCallDelta(id="call_1", name="search")
        self.assertEqual(tc.id, "call_1")
        self.assertEqual(tc.name, "search")
        self.assertEqual(tc.args, {})
        self.assertIsNone(tc.thought_signature)
        self.assertEqual(tc.to_dict(), {"id": "call_1", "name": "search", "args": {}})

    def test_tool_call_delta_with_thought_signature(self):
        tc = ToolCallDelta(
            id="call_2",
            name="run",
            args={"cmd": "pwd"},
            thought_signature="sig_abc",
        )
        self.assertEqual(
            tc.to_dict(),
            {
                "id": "call_2",
                "name": "run",
                "args": {"cmd": "pwd"},
                "thought_signature": "sig_abc",
            },
        )

    def test_usage_defaults_and_to_dict(self):
        usage = Usage()
        self.assertEqual(usage.prompt_tokens, 0)
        self.assertEqual(usage.completion_tokens, 0)
        self.assertEqual(usage.total_tokens, 0)
        self.assertEqual(usage.thought_tokens, 0)
        self.assertEqual(
            usage.to_dict(),
            {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
        )

    def test_usage_with_values(self):
        usage = Usage(
            prompt_tokens=10,
            completion_tokens=20,
            total_tokens=30,
            thought_tokens=5,
        )
        self.assertEqual(usage.thought_tokens, 5)
        self.assertEqual(
            usage.to_dict(),
            {
                "prompt_tokens": 10,
                "completion_tokens": 20,
                "total_tokens": 30,
            },
        )

    def test_stream_event_defaults(self):
        event = StreamEvent()
        self.assertIsNone(event.delta_text)
        self.assertIsNone(event.delta_thought)
        self.assertIsNone(event.thought_signature)
        self.assertEqual(event.tool_calls, [])
        self.assertIsNone(event.finish_reason)
        self.assertIsNone(event.usage)
        self.assertIsNone(event.raw)
        self.assertFalse(event.has_content)

    def test_stream_event_has_content_flags(self):
        self.assertTrue(StreamEvent(delta_text="hello").has_content)
        self.assertTrue(StreamEvent(delta_thought="thinking").has_content)
        self.assertTrue(StreamEvent(thought_signature="sig").has_content)
        self.assertTrue(
            StreamEvent(
                tool_calls=[ToolCallDelta(id="1", name="fn")]
            ).has_content
        )
        self.assertTrue(StreamEvent(finish_reason="stop").has_content)
        self.assertTrue(StreamEvent(usage=Usage()).has_content)
        # raw alone does not count as content
        self.assertFalse(StreamEvent(raw={"foo": "bar"}).has_content)


class TestParseStreamEventTextAndThoughts(unittest.TestCase):
    """Tests text and thought extraction in parse_stream_event."""

    def test_text_chunk_extraction(self):
        payload = {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": "Hello world!"}],
                        "role": "model",
                    }
                }
            ]
        }
        event = parse_stream_event(payload)
        self.assertEqual(event.delta_text, "Hello world!")
        self.assertIsNone(event.delta_thought)
        self.assertEqual(event.raw, payload)
        self.assertTrue(event.has_content)

    def test_text_chunk_wrapped_in_response(self):
        payload = {
            "response": {
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": "Wrapped text"}],
                            "role": "model",
                        }
                    }
                ]
            }
        }
        event = parse_stream_event(payload)
        self.assertEqual(event.delta_text, "Wrapped text")
        self.assertIsNone(event.delta_thought)

    def test_thought_chunk_extraction(self):
        payload = {
            "candidates": [
                {
                    "content": {
                        "parts": [{"thought": True, "text": "Deep reasoning..."}],
                        "role": "model",
                    }
                }
            ]
        }
        event = parse_stream_event(payload)
        self.assertIsNone(event.delta_text)
        self.assertEqual(event.delta_thought, "Deep reasoning...")
        self.assertTrue(event.has_content)

    def test_mixed_text_and_thought_in_single_chunk(self):
        payload = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"thought": True, "text": "Thinking steps. "},
                            {"thought": True, "text": "More thoughts."},
                            {"text": "Final answer."},
                        ],
                        "role": "model",
                    }
                }
            ]
        }
        event = parse_stream_event(payload)
        self.assertEqual(event.delta_text, "Final answer.")
        self.assertEqual(event.delta_thought, "Thinking steps. More thoughts.")

    def test_thought_signature_on_part(self):
        payload = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"thoughtSignature": "sig_xyz_part", "text": "Result"},
                        ],
                        "role": "model",
                    }
                }
            ]
        }
        event = parse_stream_event(payload)
        self.assertEqual(event.delta_text, "Result")
        self.assertEqual(event.thought_signature, "sig_xyz_part")

    def test_empty_candidates_or_parts(self):
        self.assertFalse(parse_stream_event({}).has_content)
        self.assertFalse(parse_stream_event({"candidates": []}).has_content)
        self.assertFalse(parse_stream_event({"candidates": [{}]}).has_content)
        self.assertFalse(
            parse_stream_event({"candidates": [{"content": {"parts": []}}]}).has_content
        )


class TestParseStreamEventToolCalls(unittest.TestCase):
    """Tests functionCall parsing in parse_stream_event."""

    def test_function_call_with_dict_args(self):
        payload = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "functionCall": {
                                    "name": "read_file",
                                    "args": {"path": "/etc/hosts"},
                                }
                            }
                        ]
                    }
                }
            ]
        }
        event = parse_stream_event(payload)
        self.assertEqual(len(event.tool_calls), 1)
        tc = event.tool_calls[0]
        self.assertEqual(tc.name, "read_file")
        self.assertEqual(tc.args, {"path": "/etc/hosts"})
        self.assertTrue(tc.id.startswith("toolu_"))
        self.assertIsNone(tc.thought_signature)

    def test_function_call_with_json_string_args(self):
        payload = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "functionCall": {
                                    "id": "call_123",
                                    "name": "parse",
                                    "args": '{"count": 42}',
                                }
                            }
                        ]
                    }
                }
            ]
        }
        event = parse_stream_event(payload)
        self.assertEqual(len(event.tool_calls), 1)
        tc = event.tool_calls[0]
        self.assertEqual(tc.id, "call_123")
        self.assertEqual(tc.name, "parse")
        self.assertEqual(tc.args, {"count": 42})

    def test_function_call_with_thought_signature(self):
        payload = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "thoughtSignature": "sig_fn_call",
                                "functionCall": {
                                    "id": "call_with_sig",
                                    "name": "calc",
                                    "args": {"expr": "1+1"},
                                },
                            }
                        ]
                    }
                }
            ]
        }
        event = parse_stream_event(payload)
        self.assertEqual(len(event.tool_calls), 1)
        tc = event.tool_calls[0]
        self.assertEqual(tc.id, "call_with_sig")
        self.assertEqual(tc.name, "calc")
        self.assertEqual(tc.thought_signature, "sig_fn_call")
        self.assertEqual(event.thought_signature, "sig_fn_call")

    def test_multiple_function_calls(self):
        payload = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"functionCall": {"name": "tool_a", "args": {}}},
                            {"functionCall": {"name": "tool_b", "args": {"y": 2}}},
                        ]
                    }
                }
            ]
        }
        event = parse_stream_event(payload)
        self.assertEqual(len(event.tool_calls), 2)
        self.assertEqual(event.tool_calls[0].name, "tool_a")
        self.assertEqual(event.tool_calls[1].name, "tool_b")
        self.assertEqual(event.tool_calls[1].args, {"y": 2})


class TestParseStreamEventUsage(unittest.TestCase):
    """Tests usageMetadata parsing into Usage."""

    def test_usage_metadata_parsing(self):
        payload = {
            "usageMetadata": {
                "promptTokenCount": 12,
                "candidatesTokenCount": 34,
                "totalTokenCount": 46,
                "thoughtsTokenCount": 8,
            }
        }
        event = parse_stream_event(payload)
        self.assertIsNotNone(event.usage)
        self.assertEqual(event.usage.prompt_tokens, 12)
        self.assertEqual(event.usage.completion_tokens, 34)
        self.assertEqual(event.usage.total_tokens, 46)
        self.assertEqual(event.usage.thought_tokens, 8)
        self.assertEqual(
            event.usage.to_dict(),
            {"prompt_tokens": 12, "completion_tokens": 34, "total_tokens": 46},
        )

    def test_usage_metadata_wrapped_in_response(self):
        payload = {
            "response": {
                "usageMetadata": {
                    "promptTokenCount": 100,
                    "candidatesTokenCount": 50,
                }
            }
        }
        event = parse_stream_event(payload)
        self.assertIsNotNone(event.usage)
        self.assertEqual(event.usage.prompt_tokens, 100)
        self.assertEqual(event.usage.completion_tokens, 50)
        self.assertEqual(event.usage.total_tokens, 150)
        self.assertEqual(event.usage.thought_tokens, 0)

    def test_missing_usage_returns_none(self):
        self.assertIsNone(parse_stream_event({}).usage)


class TestParseStreamEventFinishReason(unittest.TestCase):
    """Tests finishReason parsing in parse_stream_event."""

    def test_finish_reason_stop(self):
        self.assertEqual(
            parse_stream_event({"candidates": [{"finishReason": "STOP"}]}).finish_reason,
            "stop",
        )
        self.assertEqual(
            parse_stream_event({"candidates": [{"finishReason": "1"}]}).finish_reason,
            "stop",
        )
        self.assertEqual(
            parse_stream_event({"candidates": [{"finishReason": 1}]}).finish_reason,
            "stop",
        )

    def test_finish_reason_length(self):
        self.assertEqual(
            parse_stream_event({"candidates": [{"finishReason": "MAX_TOKENS"}]}).finish_reason,
            "length",
        )
        self.assertEqual(
            parse_stream_event({"candidates": [{"finishReason": "LENGTH"}]}).finish_reason,
            "length",
        )
        self.assertEqual(
            parse_stream_event({"candidates": [{"finishReason": "2"}]}).finish_reason,
            "length",
        )

    def test_finish_reason_content_filter(self):
        for reason in (
            "SAFETY",
            "RECITATION",
            "BLOCKLIST",
            "PROHIBITED_CONTENT",
            "SPII",
            "MALICIOUS",
            "3",
            "4",
            "5",
            "6",
            "7",
            "8",
            "9",
        ):
            with self.subTest(reason=reason):
                ev = parse_stream_event({"candidates": [{"finishReason": reason}]})
                self.assertEqual(ev.finish_reason, "content_filter")

    def test_prompt_feedback_block_reason(self):
        ev = parse_stream_event({"promptFeedback": {"blockReason": "SAFETY"}})
        self.assertEqual(ev.finish_reason, "content_filter")

        wrapped = parse_stream_event(
            {"response": {"promptFeedback": {"blockReason": "PROHIBITED_CONTENT"}}}
        )
        self.assertEqual(wrapped.finish_reason, "content_filter")

    def test_prompt_feedback_unspecified_ignored(self):
        payload = {
            "promptFeedback": {"blockReason": "BLOCK_REASON_UNSPECIFIED"},
            "candidates": [{"finishReason": "STOP"}],
        }
        ev = parse_stream_event(payload)
        self.assertEqual(ev.finish_reason, "stop")

    def test_finish_reason_unspecified_returns_none(self):
        for val in ("FINISH_REASON_UNSPECIFIED", "0", "UNSPECIFIED", "", "   "):
            with self.subTest(val=val):
                ev = parse_stream_event({"candidates": [{"finishReason": val}]})
                self.assertIsNone(ev.finish_reason)


class TestParseStreamEventErrorHandling(unittest.TestCase):
    """Tests error handling and BridgeError raising in parse_stream_event."""

    def test_rate_limit_error(self):
        payload = {"error": {"code": 429, "message": "Resource exhausted"}}
        with self.assertRaises(RateLimitError):
            parse_stream_event(payload, check_error=True)

    def test_capacity_exhausted_error(self):
        payload = {"error": {"code": 503, "status": "UNAVAILABLE"}}
        with self.assertRaises(CapacityExhaustedError):
            parse_stream_event(payload, check_error=True)

    def test_forbidden_error(self):
        payload = {"error": {"code": 403, "status": "PERMISSION_DENIED"}}
        with self.assertRaises(ForbiddenError):
            parse_stream_event(payload, check_error=True)

    def test_authentication_error(self):
        payload = {"error": {"code": 401, "status": "UNAUTHENTICATED"}}
        with self.assertRaises(AuthenticationError):
            parse_stream_event(payload, check_error=True)

    def test_model_not_found_error(self):
        payload = {"error": {"code": 404, "status": "NOT_FOUND"}}
        with self.assertRaises(ModelNotFoundError):
            parse_stream_event(payload, check_error=True)

    def test_invalid_request_error(self):
        payload = {"error": {"code": 400, "status": "INVALID_ARGUMENT"}}
        with self.assertRaises(InvalidRequestError):
            parse_stream_event(payload, check_error=True)

    def test_generic_bridge_error(self):
        payload = {"error": {"code": 500, "message": "Internal error"}}
        with self.assertRaises(BridgeError):
            parse_stream_event(payload, check_error=True)

    def test_check_error_false_does_not_raise(self):
        payload = {"error": {"code": 429, "message": "Resource exhausted"}}
        # When check_error=False, it should not raise
        ev = parse_stream_event(payload, check_error=False)
        self.assertIsInstance(ev, StreamEvent)
        self.assertEqual(ev.raw, payload)


if __name__ == "__main__":
    unittest.main()
