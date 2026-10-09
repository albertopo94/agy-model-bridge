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
    AnthropicChatRequest,
    ChatRequest,
    OpenAIChatRequest,
    ResponsesChatRequest,
    StreamEvent,
    ToolCallDelta,
    Usage,
    append_or_merge_turn,
    build_system_instruction,
    build_tool_declarations,
    normalize_turn_boundaries,
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


class TestChatRequestIR(unittest.TestCase):
    """Tests for ChatRequest IR and protocol-specific request specializations."""

    def test_chat_request_attributes_and_extra_kwargs(self):
        req = ChatRequest(
            model="gemini-2.5-pro",
            contents=[{"role": "user", "parts": [{"text": "Hello"}]}],
            system_instruction={"parts": [{"text": "Be concise"}]},
            generation_config={"temperature": 0.7, "maxOutputTokens": 100},
            tools=[{"functionDeclarations": [{"name": "test_tool"}]}],
            tool_config={"functionCallingConfig": {"mode": "AUTO"}},
        )
        self.assertEqual(req.model, "gemini-2.5-pro")
        self.assertEqual(len(req.contents), 1)
        self.assertEqual(req.system_instruction, {"parts": [{"text": "Be concise"}]})
        self.assertEqual(
            req.extra_kwargs,
            {
                "generation_config": {"temperature": 0.7, "maxOutputTokens": 100},
                "tools": [{"functionDeclarations": [{"name": "test_tool"}]}],
                "tool_config": {"functionCallingConfig": {"mode": "AUTO"}},
            },
        )

    def test_chat_request_extra_kwargs_empty_when_none(self):
        req = ChatRequest(
            model="gemini-2.5-flash",
            contents=[{"role": "user", "parts": [{"text": "Hi"}]}],
        )
        self.assertEqual(req.extra_kwargs, {})
        self.assertIsNone(req.system_instruction)
        self.assertIsNone(req.generation_config)
        self.assertIsNone(req.tools)
        self.assertIsNone(req.tool_config)

    def test_to_legacy_tuple(self):
        req = ChatRequest(
            model="gemini-2.5-flash",
            contents=[{"role": "user", "parts": [{"text": "Hi"}]}],
            system_instruction={"parts": [{"text": "Sys"}]},
            generation_config={"temperature": 0.5},
            tools=[{"functionDeclarations": []}],
        )
        tup = req.to_legacy_tuple()
        self.assertEqual(len(tup), 5)
        self.assertEqual(tup[0], "gemini-2.5-flash")
        self.assertEqual(tup[1], [{"role": "user", "parts": [{"text": "Hi"}]}])
        self.assertEqual(tup[2], {"parts": [{"text": "Sys"}]})
        self.assertEqual(tup[3], {"temperature": 0.5})
        self.assertEqual(tup[4], [{"functionDeclarations": []}])

    def test_to_anthropic_tuple(self):
        req = ChatRequest(
            model="claude-sonnet-5-5",
            contents=[{"role": "user", "parts": [{"text": "Hi"}]}],
            system_instruction=None,
            generation_config={"temperature": 0.2},
            tools=None,
            tool_config={"functionCallingConfig": {"mode": "NONE"}},
        )
        tup = req.to_anthropic_tuple()
        self.assertEqual(len(tup), 6)
        self.assertEqual(tup[0], "claude-sonnet-5-5")
        self.assertEqual(tup[5], {"functionCallingConfig": {"mode": "NONE"}})

    def test_openai_chat_request_unpacking_5_tuple(self):
        req = OpenAIChatRequest(
            model="gemini-2.5-flash",
            contents=[{"role": "user", "parts": [{"text": "Hi"}]}],
            system_instruction={"parts": [{"text": "Sys"}]},
            generation_config={"temperature": 0.5},
            tools=[{"functionDeclarations": []}],
        )
        self.assertIsInstance(req, ChatRequest)
        self.assertEqual(len(req), 5)
        self.assertEqual(req[0], "gemini-2.5-flash")
        m, c, s, g, t = req
        self.assertEqual(m, "gemini-2.5-flash")
        self.assertEqual(c, [{"role": "user", "parts": [{"text": "Hi"}]}])
        self.assertEqual(s, {"parts": [{"text": "Sys"}]})
        self.assertEqual(g, {"temperature": 0.5})
        self.assertEqual(t, [{"functionDeclarations": []}])

    def test_responses_chat_request_unpacking_5_tuple(self):
        req = ResponsesChatRequest(
            model="gemini-2.5-pro",
            contents=[{"role": "user", "parts": [{"text": "Input"}]}],
            system_instruction=None,
            generation_config=None,
            tools=None,
        )
        self.assertIsInstance(req, ChatRequest)
        self.assertEqual(len(req), 5)
        m, c, s, g, t = req
        self.assertEqual(m, "gemini-2.5-pro")
        self.assertEqual(c, [{"role": "user", "parts": [{"text": "Input"}]}])
        self.assertIsNone(s)
        self.assertIsNone(g)
        self.assertIsNone(t)

    def test_anthropic_chat_request_unpacking_6_tuple(self):
        req = AnthropicChatRequest(
            model="claude-sonnet-5-5",
            contents=[{"role": "user", "parts": [{"text": "Claude"}]}],
            system_instruction={"parts": [{"text": "Be helpful"}]},
            generation_config={"maxOutputTokens": 2048},
            tools=[{"functionDeclarations": [{"name": "calculator"}]}],
            tool_config={"functionCallingConfig": {"mode": "AUTO"}},
        )
        self.assertIsInstance(req, ChatRequest)
        self.assertEqual(len(req), 6)
        self.assertEqual(req[0], "claude-sonnet-5-5")
        self.assertEqual(req[5], {"functionCallingConfig": {"mode": "AUTO"}})
        m, c, s, g, t, tc = req
        self.assertEqual(m, "claude-sonnet-5-5")
        self.assertEqual(c, [{"role": "user", "parts": [{"text": "Claude"}]}])
        self.assertEqual(s, {"parts": [{"text": "Be helpful"}]})
        self.assertEqual(g, {"maxOutputTokens": 2048})
        self.assertEqual(t, [{"functionDeclarations": [{"name": "calculator"}]}])
        self.assertEqual(tc, {"functionCallingConfig": {"mode": "AUTO"}})


class TestRequestHelpers(unittest.TestCase):
    """Tests for shared request normalization helpers."""

    def test_build_system_instruction(self):
        self.assertIsNone(build_system_instruction([]))
        self.assertIsNone(build_system_instruction(["   ", ""]))
        inst = build_system_instruction(["You are an AI.", "Follow user instructions."])
        self.assertIsNotNone(inst)
        self.assertEqual(
            inst,
            {"parts": [{"text": "You are an AI.\nFollow user instructions."}]},
        )

    def test_normalize_turn_boundaries_empty(self):
        self.assertEqual(normalize_turn_boundaries([]), [])

    def test_normalize_turn_boundaries_starting_with_model(self):
        contents = [{"role": "model", "parts": [{"text": "Hi"}]}]
        res = normalize_turn_boundaries(contents)
        self.assertEqual(res[0], {"role": "user", "parts": [{"text": "Hello"}]})
        self.assertEqual(res[1], {"role": "model", "parts": [{"text": "Hi"}]})
        self.assertEqual(res[2], {"role": "user", "parts": [{"text": "Continue"}]})

    def test_normalize_turn_boundaries_already_valid(self):
        contents = [
            {"role": "user", "parts": [{"text": "Hello"}]},
            {"role": "model", "parts": [{"text": "Hi"}]},
            {"role": "user", "parts": [{"text": "How are you?"}]},
        ]
        res = normalize_turn_boundaries(list(contents))
        self.assertEqual(res, contents)

    def test_append_or_merge_turn_new_role(self):
        contents: list[dict] = []
        append_or_merge_turn(contents, "user", [{"text": "Hello"}])
        self.assertEqual(contents, [{"role": "user", "parts": [{"text": "Hello"}]}])
        append_or_merge_turn(contents, "model", [{"text": "World"}])
        self.assertEqual(
            contents,
            [
                {"role": "user", "parts": [{"text": "Hello"}]},
                {"role": "model", "parts": [{"text": "World"}]},
            ],
        )

    def test_append_or_merge_turn_same_role_merges_parts(self):
        contents: list[dict] = [{"role": "user", "parts": [{"text": "First"}]}]
        append_or_merge_turn(contents, "user", [{"text": "Second"}])
        self.assertEqual(
            contents,
            [{"role": "user", "parts": [{"text": "First"}, {"text": "Second"}]}],
        )

    def test_build_tool_declarations(self):
        self.assertIsNone(build_tool_declarations([]))
        decls = [{"name": "foo", "description": "bar"}]
        self.assertEqual(
            build_tool_declarations(decls),
            [{"functionDeclarations": decls}],
        )


if __name__ == "__main__":
    unittest.main()
