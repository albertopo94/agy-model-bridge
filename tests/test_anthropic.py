"""Unit tests for the Anthropic Messages API shim."""

import json
import unittest
from bridge.anthropic import (
    _extract_event_thought_signature,
    anthropic_to_cloudcode_request,
    build_anthropic_message,
    build_anthropic_sse_events,
    build_anthropic_error_response,
)
from bridge.transform import (
    DUMMY_THOUGHT_SIGNATURE,
    get_thought_signature,
    get_tool_name,
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
        model, contents, system_inst, gen_config, tools = anthropic_to_cloudcode_request(
            payload, project="test-project"
        )
        self.assertEqual(model, "gemini-2.5-pro")
        self.assertEqual(system_inst, {"parts": [{"text": "You are Claude."}]})
        self.assertEqual(contents, [{"role": "user", "parts": [{"text": "Hello world"}]}])
        self.assertIsNotNone(gen_config)
        self.assertEqual(gen_config["maxOutputTokens"], 1024)
        self.assertEqual(gen_config["temperature"], 0.5)
        self.assertNotIn("thinkingConfig", gen_config)
        self.assertIsNone(tools)

    def test_request_translation_with_tools(self):
        payload = {
            "model": "gemini-2.5-pro",
            "messages": [{"role": "user", "content": "What is the weather?"}],
            "tools": [
                {
                    "name": "get_weather",
                    "description": "Get current weather in location",
                    "input_schema": {
                        "type": "object",
                        "properties": {"location": {"type": "string"}},
                        "required": ["location"],
                    },
                }
            ],
        }
        _, _, _, _, tools = anthropic_to_cloudcode_request(payload, "test-project")
        self.assertIsNotNone(tools)
        self.assertEqual(len(tools), 1)
        self.assertIn("functionDeclarations", tools[0])
        decls = tools[0]["functionDeclarations"]
        self.assertEqual(len(decls), 1)
        self.assertEqual(decls[0]["name"], "get_weather")
        self.assertEqual(decls[0]["description"], "Get current weather in location")
        self.assertEqual(
            decls[0]["parameters"],
            {
                "type": "object",
                "properties": {"location": {"type": "string"}},
                "required": ["location"],
            },
        )

    def test_request_translation_sanitizes_tool_schema(self):
        payload = {
            "model": "gemini-3.8-flash-high",
            "messages": [{"role": "user", "content": "Run command"}],
            "tools": [
                {
                    "name": "Bash",
                    "description": "Execute bash command",
                    "input_schema": {
                        "$schema": "http://json-schema.org/draft-07/schema#",
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "command": {
                                "type": "string",
                                "description": "The command to run",
                            },
                            "env": {
                                "type": "object",
                                "propertyNames": {"pattern": "^[A-Z_]+$"},
                                "anyOf": [
                                    {"const": "prod", "type": "string"},
                                    {"type": "string", "propertyNames": {"pattern": "^[a-z]+$"}},
                                ],
                            },
                        },
                        "required": ["command"],
                    },
                }
            ],
        }
        _, _, _, _, tools = anthropic_to_cloudcode_request(payload, "test-project")
        self.assertIsNotNone(tools)
        decls = tools[0]["functionDeclarations"]
        params = decls[0]["parameters"]
        self.assertNotIn("$schema", params)
        self.assertNotIn("additionalProperties", params)
        self.assertNotIn("propertyNames", params["properties"]["env"])
        self.assertNotIn("const", params["properties"]["env"]["anyOf"][0])
        self.assertNotIn("propertyNames", params["properties"]["env"]["anyOf"][1])


    def test_request_translation_empty_tools_returns_none(self):
        payload = {
            "model": "gemini-2.5-pro",
            "messages": [{"role": "user", "content": "Hi"}],
            "tools": [],
        }
        _, _, _, _, tools = anthropic_to_cloudcode_request(payload, "test-project")
        self.assertIsNone(tools)

    def test_system_as_content_blocks(self):
        payload = {
            "model": "gemini-2.5-pro",
            "system": [
                {"type": "text", "text": "First instruction."},
                {"type": "text", "text": "Second instruction."},
            ],
            "messages": [{"role": "user", "content": "Hi"}],
        }
        _, _, system_inst, _, _ = anthropic_to_cloudcode_request(payload, "test-project")
        self.assertEqual(
            system_inst,
            {"parts": [{"text": "First instruction.\nSecond instruction."}]},
        )

    def test_system_role_in_messages_array(self):
        payload = {
            "model": "gemini-3.8-flash-high",
            "messages": [
                {"role": "system", "content": "You are Claude Code assistant."},
                {"role": "user", "content": "hola"},
            ],
        }
        _, contents, system_inst, _, _ = anthropic_to_cloudcode_request(payload, "test-project")
        self.assertEqual(
            system_inst,
            {"parts": [{"text": "You are Claude Code assistant."}]},
        )
        self.assertEqual(len(contents), 1)
        self.assertEqual(contents[0]["role"], "user")
        self.assertEqual(contents[0]["parts"], [{"text": "hola"}])

    def test_anthropic_thinking_adaptive_sanitization(self):
        payload = {
            "model": "gemini-3.8-flash-high",
            "messages": [{"role": "user", "content": "hola"}],
            "thinking": {"type": "adaptive"},
        }
        model, contents, _, gen_config, _ = anthropic_to_cloudcode_request(payload, "test-project")
        self.assertEqual(model, "gemini-3.8-flash-tiered")
        self.assertIsNotNone(gen_config)
        self.assertEqual(gen_config.get("thinkingConfig"), {"thinkingLevel": "HIGH"})
        self.assertNotIn("type", gen_config.get("thinkingConfig", {}))

    def test_user_content_as_blocks_and_multi_turn(self):
        payload = {
            "model": "gemini-2.5-pro",
            "messages": [
                {"role": "user", "content": [{"type": "text", "text": "What is 2+2?"}]},
                {"role": "assistant", "content": [{"type": "text", "text": "It is 4."}]},
                {"role": "user", "content": "Thanks!"},
            ],
        }
        _, contents, _, _, _ = anthropic_to_cloudcode_request(payload, "test-project")
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
        _, contents, _, _, _ = anthropic_to_cloudcode_request(payload, "test-project")
        # Starts with assistant turn, so "Hello" user turn prepended
        self.assertEqual(contents[0]["role"], "user")
        self.assertEqual(contents[0]["parts"], [{"text": "Hello"}])
        # Tool call in model turn
        self.assertEqual(contents[1]["role"], "model")
        self.assertEqual(len(contents[1]["parts"]), 1)
        part = contents[1]["parts"][0]
        self.assertEqual(part.get("functionCall"), {"name": "get_weather", "args": {"location": "Paris"}})
        self.assertTrue(part.get("thoughtSignature"))
        # Tool results merged into user turn
        self.assertEqual(contents[2]["role"], "user")
        self.assertEqual(len(contents[2]["parts"]), 2)
        self.assertEqual(
            contents[2]["parts"][0],
            {"functionResponse": {"name": "get_weather", "response": {"output": "Sunny, 22C"}}},
        )
        self.assertEqual(
            contents[2]["parts"][1],
            {"functionResponse": {"name": "tool", "response": {"temperature": 22}}},
        )

    def test_mixed_text_and_tool_use_in_assistant_turn(self):
        payload = {
            "model": "gemini-2.5-pro",
            "messages": [
                {"role": "user", "content": "What is the weather in Tokyo?"},
                {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "I will check the weather for Tokyo."},
                        {"type": "tool_use", "id": "t_tokyo", "name": "get_weather", "input": {"city": "Tokyo"}},
                    ],
                },
            ],
        }
        _, contents, _, _, _ = anthropic_to_cloudcode_request(payload, "test-project")
        # Turn 0: user
        self.assertEqual(contents[0]["role"], "user")
        self.assertEqual(contents[0]["parts"], [{"text": "What is the weather in Tokyo?"}])
        # Turn 1: model with both text and functionCall parts
        self.assertEqual(contents[1]["role"], "model")
        self.assertEqual(len(contents[1]["parts"]), 2)
        self.assertEqual(contents[1]["parts"][0], {"text": "I will check the weather for Tokyo."})
        self.assertEqual(contents[1]["parts"][1]["functionCall"], {"name": "get_weather", "args": {"city": "Tokyo"}})
        self.assertTrue(contents[1]["parts"][1].get("thoughtSignature"))
        # Since last turn was model, alternation appends "Continue" user turn
        self.assertEqual(contents[2]["role"], "user")
        self.assertEqual(contents[2]["parts"], [{"text": "Continue"}])

    def test_tool_use_explicit_thought_signature_and_list_tool_result(self):
        payload = {
            "model": "gemini-2.5-pro",
            "messages": [
                {"role": "user", "content": "Run ls"},
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "t_bash",
                            "name": "Bash",
                            "input": {"command": "ls -la"},
                            "thoughtSignature": "explicit_sig_456",
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "t_bash",
                            "content": [
                                {"type": "text", "text": "file1.txt\nfile2.txt"},
                            ],
                        }
                    ],
                },
            ],
        }
        _, contents, _, _, _ = anthropic_to_cloudcode_request(payload, "test-project")
        self.assertEqual(len(contents), 3)
        # Turn 1: model
        self.assertEqual(contents[1]["role"], "model")
        self.assertEqual(
            contents[1]["parts"][0],
            {
                "thoughtSignature": "explicit_sig_456",
                "functionCall": {"name": "Bash", "args": {"command": "ls -la"}},
            },
        )
        # Turn 2: user tool_result extracted from block list
        self.assertEqual(contents[2]["role"], "user")
        self.assertEqual(
            contents[2]["parts"][0],
            {
                "functionResponse": {
                    "name": "Bash",
                    "response": {"output": "file1.txt\nfile2.txt"},
                }
            },
        )

    def test_thinking_config_integration(self):
        # Reasoning model variant
        payload_high = {
            "model": "gemini-3.1-pro-high",
            "messages": [{"role": "user", "content": "Think deeply"}],
        }
        _, _, _, gen_config_high, _ = anthropic_to_cloudcode_request(payload_high, "test-project")
        self.assertEqual(gen_config_high["thinkingConfig"], {"thinkingLevel": "HIGH"})

        # Explicit client thinking override
        payload_override = {
            "model": "gemini-3.1-pro-high",
            "messages": [{"role": "user", "content": "Think deeply"}],
            "thinking": {"type": "enabled", "budget_tokens": 4096},
        }
        _, _, _, gen_config_ovr, _ = anthropic_to_cloudcode_request(payload_override, "test-project")
        self.assertEqual(gen_config_ovr["thinkingConfig"], {"thinkingBudget": 4096})

    def test_omitted_or_aliased_model_resolves_to_flash_tiered(self):
        # Omitted model defaults to flash-tiered with HIGH thinking
        model, _, _, gen_config, _ = anthropic_to_cloudcode_request(
            {"messages": [{"role": "user", "content": "Hi"}]}, "p"
        )
        self.assertEqual(model, "gemini-3.8-flash-tiered")
        self.assertEqual(gen_config.get("thinkingConfig"), {"thinkingLevel": "HIGH"})

        # "auto" model
        model_auto, _, _, gen_config_auto, _ = anthropic_to_cloudcode_request(
            {"model": "auto", "messages": [{"role": "user", "content": "Hi"}]}, "p"
        )
        self.assertEqual(model_auto, "gemini-3.8-flash-tiered")
        self.assertEqual(gen_config_auto.get("thinkingConfig"), {"thinkingLevel": "HIGH"})

        # "gemini-3.8-flash-high"
        model_fh, _, _, gen_config_fh, _ = anthropic_to_cloudcode_request(
            {"model": "gemini-3.8-flash-high", "messages": [{"role": "user", "content": "Hi"}]}, "p"
        )
        self.assertEqual(model_fh, "gemini-3.8-flash-tiered")
        self.assertEqual(gen_config_fh.get("thinkingConfig"), {"thinkingLevel": "HIGH"})

    def test_invalid_model_type_raises_value_error(self):
        with self.assertRaises(ValueError):
            anthropic_to_cloudcode_request({"model": 12345, "messages": [{"role": "user", "content": "Hi"}]}, "p")

    def test_validation_missing_or_empty_messages_raises_value_error(self):
        with self.assertRaises(ValueError):
            anthropic_to_cloudcode_request({"model": "gemini-2.5-pro"}, "p")
        with self.assertRaises(ValueError):
            anthropic_to_cloudcode_request({"model": "gemini-2.5-pro", "messages": []}, "p")

    def test_anthropic_to_cloudcode_request_with_thinking_blocks_in_history(self):
        payload = {
            "model": "claude-sonnet-5-5-high",
            "messages": [
                {"role": "user", "content": "How far is the moon?"},
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "thinking",
                            "thinking": "The average distance to the Moon is about 384,400 km.",
                            "signature": "sig_moon_123",
                        },
                        {
                            "type": "text",
                            "text": "The Moon is approximately 384,400 km away.",
                        },
                    ],
                },
                {"role": "user", "content": "What about Mars?"},
            ],
        }
        model, contents, _, gen_config, _ = anthropic_to_cloudcode_request(payload, "test-project")
        self.assertEqual(model, "claude-sonnet-5-5")
        self.assertIsNotNone(gen_config)
        self.assertEqual(gen_config["thinkingConfig"], {"thinkingLevel": "HIGH"})
        self.assertEqual(len(contents), 3)

        model_turn = contents[1]
        self.assertEqual(model_turn["role"], "model")
        self.assertEqual(len(model_turn["parts"]), 2)
        self.assertEqual(
            model_turn["parts"][0],
            {
                "thought": True,
                "text": "The average distance to the Moon is about 384,400 km.",
                "thoughtSignature": "sig_moon_123",
            },
        )
        self.assertEqual(
            model_turn["parts"][1],
            {"text": "The Moon is approximately 384,400 km away."},
        )
        for p in model_turn["parts"]:
            if "text" in p:
                self.assertNotIn("<thinking>", p["text"])
                self.assertNotIn("</thinking>", p["text"])

    def test_anthropic_to_cloudcode_request_thinking_with_tool_use(self):
        payload = {
            "model": "claude-sonnet-5-5",
            "messages": [
                {"role": "user", "content": "Check weather"},
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "thinking",
                            "thinking": "I should call get_weather.",
                            "signature": "sig_tool_weather_99",
                        },
                        {
                            "type": "tool_use",
                            "id": "t_weather",
                            "name": "get_weather",
                            "input": {"city": "Paris"},
                        },
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "t_weather",
                            "content": "Sunny, 20C",
                        }
                    ],
                },
            ],
        }
        model, contents, _, _, _ = anthropic_to_cloudcode_request(payload, "test-project")
        self.assertEqual(model, "claude-sonnet-5-5")
        self.assertEqual(len(contents), 3)
        model_turn = contents[1]
        self.assertEqual(model_turn["role"], "model")
        self.assertEqual(len(model_turn["parts"]), 2)
        self.assertEqual(
            model_turn["parts"][0],
            {
                "thought": True,
                "text": "I should call get_weather.",
                "thoughtSignature": "sig_tool_weather_99",
            },
        )
        self.assertEqual(
            model_turn["parts"][1],
            {
                "thoughtSignature": "sig_tool_weather_99",
                "functionCall": {"name": "get_weather", "args": {"city": "Paris"}},
            },
        )


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

    def test_build_anthropic_message_with_thinking(self):
        resp = build_anthropic_message(
            message_id="msg_think",
            model="gemini-2.5-pro",
            text="Done",
            thinking="Thinking carefully...",
        )
        self.assertEqual(len(resp["content"]), 2)
        self.assertEqual(resp["content"][0]["type"], "thinking")
        self.assertEqual(resp["content"][0]["thinking"], "Thinking carefully...")
        self.assertEqual(resp["content"][0]["signature"], DUMMY_THOUGHT_SIGNATURE)
        self.assertEqual(resp["content"][1], {"type": "text", "text": "Done"})

    def test_build_anthropic_message_includes_signature_in_thinking_block(self):
        resp = build_anthropic_message(
            message_id="msg_think_sig",
            model="claude-sonnet-5-5",
            text="Done",
            thinking="Thinking with signature...",
            signature="test_signature_xyz",
        )
        self.assertEqual(
            resp["content"][0],
            {
                "type": "thinking",
                "thinking": "Thinking with signature...",
                "signature": "test_signature_xyz",
            },
        )

    def test_build_anthropic_message_with_tool_use(self):
        resp = build_anthropic_message(
            message_id="msg_tool",
            model="gemini-2.5-pro",
            tool_calls=[{"id": "toolu_abc", "name": "run_command", "args": {"command": "ls"}}],
        )
        self.assertEqual(resp["stop_reason"], "tool_use")
        self.assertEqual(len(resp["content"]), 1)
        self.assertEqual(
            resp["content"][0],
            {"type": "tool_use", "id": "toolu_abc", "name": "run_command", "input": {"command": "ls"}},
        )

    def test_build_anthropic_message_combined_thinking_text_tool_use(self):
        resp = build_anthropic_message(
            message_id="msg_comb",
            model="gemini-2.5-pro",
            text="Running now",
            thinking="I should run bash",
            tool_calls=[{"id": "toolu_xyz", "name": "bash", "args": {"cmd": "pwd"}}],
        )
        self.assertEqual(resp["stop_reason"], "tool_use")
        self.assertEqual(len(resp["content"]), 3)
        self.assertEqual(resp["content"][0]["type"], "thinking")
        self.assertEqual(resp["content"][1]["type"], "text")
        self.assertEqual(resp["content"][2]["type"], "tool_use")

    def test_build_anthropic_message_caches_tool_info(self):
        resp = build_anthropic_message(
            message_id="msg_cache_test",
            model="gemini-2.5-pro",
            tool_calls=[{
                "id": "toolu_cache123",
                "name": "lookup_user",
                "args": {"uid": 42},
                "thought_signature": "sig_cache123",
            }],
        )
        self.assertEqual(get_tool_name("toolu_cache123"), "lookup_user")
        self.assertEqual(get_thought_signature("toolu_cache123", "lookup_user", {"uid": 42}), "sig_cache123")


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
        self.assertEqual(event_names[0], "message_start")
        self.assertEqual(event_names[-2], "message_delta")
        self.assertEqual(event_names[-1], "message_stop")

        # Verify message_start
        msg_start_data = parsed_events[0][1]
        self.assertEqual(msg_start_data["type"], "message_start")
        self.assertTrue(msg_start_data["message"]["id"].startswith("msg_"))
        self.assertEqual(msg_start_data["message"]["model"], "gemini-2.5-pro")

        # Verify block 0 is thinking
        block_0_starts = [d for n, d in parsed_events if n == "content_block_start" and d["index"] == 0]
        self.assertEqual(len(block_0_starts), 1)
        self.assertEqual(block_0_starts[0]["content_block"]["type"], "thinking")

        thinking_deltas = [
            d["delta"]["thinking"]
            for n, d in parsed_events
            if n == "content_block_delta" and d["index"] == 0 and d["delta"].get("type") == "thinking_delta"
        ]
        self.assertEqual("".join(thinking_deltas), "hidden")

        sig_deltas = [
            d["delta"]["signature"]
            for n, d in parsed_events
            if n == "content_block_delta" and d["index"] == 0 and d["delta"].get("type") == "signature_delta"
        ]
        self.assertEqual(len(sig_deltas), 1)
        self.assertTrue(sig_deltas[0])

        # Verify block 1 is text
        block_1_starts = [d for n, d in parsed_events if n == "content_block_start" and d["index"] == 1]
        self.assertEqual(len(block_1_starts), 1)
        self.assertEqual(block_1_starts[0]["content_block"]["type"], "text")

        text_deltas = [d["delta"]["text"] for n, d in parsed_events if n == "content_block_delta" and d["index"] == 1]
        self.assertEqual("".join(text_deltas), "Hello world!")

        # Verify message_delta has stop_reason and usage
        msg_delta_data = parsed_events[-2][1]
        self.assertEqual(msg_delta_data["type"], "message_delta")
        self.assertEqual(msg_delta_data["delta"]["stop_reason"], "end_turn")
        self.assertEqual(msg_delta_data["usage"]["output_tokens"], 12)

    def test_build_anthropic_sse_events_pure_text(self):
        mock_upstream_lines = [
            'data: {"candidates": [{"content": {"parts": [{"text": "Hello "}]}}]}\n',
            'data: {"candidates": [{"content": {"parts": [{"text": "world!"}]}}], "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 10, "totalTokenCount": 15}}\n',
            'data: {"candidates": [{"finishReason": "STOP"}]}\n',
        ]
        events = list(build_anthropic_sse_events(iter(mock_upstream_lines), "gemini-2.5-flash"))
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

        # Block 0 starts immediately with text
        self.assertEqual(parsed_events[1][0], "content_block_start")
        self.assertEqual(parsed_events[1][1]["index"], 0)
        self.assertEqual(parsed_events[1][1]["content_block"]["type"], "text")

        # Deltas
        deltas = [d["delta"]["text"] for n, d in parsed_events if n == "content_block_delta"]
        self.assertEqual("".join(deltas), "Hello world!")

        # Stop reason
        msg_delta = [d for n, d in parsed_events if n == "message_delta"][0]
        self.assertEqual(msg_delta["delta"]["stop_reason"], "end_turn")

    def test_build_anthropic_sse_events_tool_use(self):
        mock_upstream_lines = [
            'data: {"candidates": [{"content": {"parts": [{"functionCall": {"id": "toolu_123", "name": "run_command", "args": {"command": "ls"}}}]}}]}\n',
            'data: {"candidates": [{"finishReason": "STOP"}]}\n',
        ]
        events = list(build_anthropic_sse_events(iter(mock_upstream_lines), "gemini-2.5-pro"))
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

        # Block 0 is tool_use
        tool_starts = [d for n, d in parsed_events if n == "content_block_start"]
        self.assertEqual(len(tool_starts), 1)
        self.assertEqual(tool_starts[0]["content_block"]["type"], "tool_use")
        self.assertEqual(tool_starts[0]["content_block"]["id"], "toolu_123")
        self.assertEqual(tool_starts[0]["content_block"]["name"], "run_command")

        # Delta is input_json_delta
        tool_deltas = [d for n, d in parsed_events if n == "content_block_delta"]
        self.assertEqual(len(tool_deltas), 1)
        self.assertEqual(tool_deltas[0]["delta"]["type"], "input_json_delta")
        self.assertEqual(json.loads(tool_deltas[0]["delta"]["partial_json"]), {"command": "ls"})

        # Stop reason is tool_use
        msg_delta = [d for n, d in parsed_events if n == "message_delta"][0]
        self.assertEqual(msg_delta["delta"]["stop_reason"], "tool_use")

    def test_build_anthropic_sse_events_combined_thinking_text_tools(self):
        mock_upstream_lines = [
            'data: {"candidates": [{"content": {"parts": [{"thought": true, "text": "Need to list directory"}]}}]}\n',
            'data: {"candidates": [{"content": {"parts": [{"text": "Executing ls"}]}}]}\n',
            'data: {"candidates": [{"content": {"parts": [{"functionCall": {"id": "toolu_456", "name": "bash", "args": {"cmd": "ls"}}}]}}]}\n',
            'data: {"candidates": [{"finishReason": "STOP"}]}\n',
        ]
        events = list(build_anthropic_sse_events(iter(mock_upstream_lines), "gemini-2.5-pro"))
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

        # Check block starts
        starts = [d for n, d in parsed_events if n == "content_block_start"]
        self.assertEqual(len(starts), 3)
        self.assertEqual(starts[0]["index"], 0)
        self.assertEqual(starts[0]["content_block"]["type"], "thinking")
        self.assertEqual(starts[1]["index"], 1)
        self.assertEqual(starts[1]["content_block"]["type"], "text")
        self.assertEqual(starts[2]["index"], 2)
        self.assertEqual(starts[2]["content_block"]["type"], "tool_use")
        self.assertEqual(starts[2]["content_block"]["name"], "bash")

        # Check stop reason
        msg_delta = [d for n, d in parsed_events if n == "message_delta"][0]
        self.assertEqual(msg_delta["delta"]["stop_reason"], "tool_use")

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

    def test_sse_events_caches_thought_signature_and_tool_name(self):
        mock_upstream_lines = [
            'data: {"candidates": [{"content": {"parts": [{"functionCall": {"id": "toolu_stream999", "name": "fetch_data", "args": {"key": "val"}}, "thoughtSignature": "stream_sig_999"}]}}]}\n',
            'data: {"candidates": [{"finishReason": "STOP"}]}\n',
        ]
        list(build_anthropic_sse_events(iter(mock_upstream_lines), "gemini-2.5-pro"))
        self.assertEqual(get_tool_name("toolu_stream999"), "fetch_data")
        self.assertEqual(get_thought_signature("toolu_stream999", "fetch_data", {"key": "val"}), "stream_sig_999")

    def test_build_anthropic_sse_events_emits_signature_delta_before_stop(self):
        mock_upstream_lines = [
            'data: {"candidates": [{"content": {"parts": [{"thought": true, "text": "thinking..."}]}}]}\n',
            'data: {"candidates": [{"content": {"parts": [{"text": "final answer"}]}}]}\n',
            'data: {"candidates": [{"finishReason": "STOP"}]}\n',
        ]
        events = list(build_anthropic_sse_events(iter(mock_upstream_lines), "claude-sonnet-5-5"))
        parsed = []
        for raw in events:
            lines = [l for l in raw.strip().split("\n") if l]
            ev_name = None
            ev_data = None
            for l in lines:
                if l.startswith("event:"):
                    ev_name = l[6:].strip()
                elif l.startswith("data:"):
                    ev_data = json.loads(l[5:].strip())
            if ev_name and ev_data:
                parsed.append((ev_name, ev_data))

        idx0_events = [(n, d) for n, d in parsed if d.get("index") == 0]
        self.assertEqual(len(idx0_events), 4)
        self.assertEqual(idx0_events[0][0], "content_block_start")
        self.assertEqual(idx0_events[0][1]["content_block"]["type"], "thinking")
        self.assertEqual(idx0_events[1][0], "content_block_delta")
        self.assertEqual(idx0_events[1][1]["delta"]["type"], "thinking_delta")
        self.assertEqual(idx0_events[2][0], "content_block_delta")
        self.assertEqual(idx0_events[2][1]["delta"]["type"], "signature_delta")
        self.assertEqual(idx0_events[2][1]["delta"]["signature"], DUMMY_THOUGHT_SIGNATURE)
        self.assertEqual(idx0_events[3][0], "content_block_stop")

    def test_build_anthropic_sse_events_signature_delta_from_upstream_event(self):
        mock_upstream_lines = [
            'data: {"candidates": [{"content": {"parts": [{"thought": true, "text": "deep thought"}]}, "thoughtSignature": "upstream_sig_777"}]}\n',
            'data: {"candidates": [{"content": {"parts": [{"text": "result"}]}}]}\n',
            'data: {"candidates": [{"finishReason": "STOP"}]}\n',
        ]
        events = list(build_anthropic_sse_events(iter(mock_upstream_lines), "claude-sonnet-5-5"))
        parsed = []
        for raw in events:
            lines = [l for l in raw.strip().split("\n") if l]
            ev_name = None
            ev_data = None
            for l in lines:
                if l.startswith("event:"):
                    ev_name = l[6:].strip()
                elif l.startswith("data:"):
                    ev_data = json.loads(l[5:].strip())
            if ev_name and ev_data:
                parsed.append((ev_name, ev_data))

        sig_deltas = [
            d["delta"]["signature"]
            for n, d in parsed
            if n == "content_block_delta" and d.get("index") == 0 and d["delta"].get("type") == "signature_delta"
        ]
        self.assertEqual(sig_deltas, ["upstream_sig_777"])


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


class TestExtractEventThoughtSignature(unittest.TestCase):
    def test_extract_from_candidate_root(self):
        parsed = {"candidates": [{"thoughtSignature": "sig_root_123"}]}
        self.assertEqual(_extract_event_thought_signature(parsed), "sig_root_123")

    def test_extract_from_candidate_root_snake_case(self):
        parsed = {"candidates": [{"thought_signature": "sig_snake_123"}]}
        self.assertEqual(_extract_event_thought_signature(parsed), "sig_snake_123")

    def test_extract_from_content_level(self):
        parsed = {"candidates": [{"content": {"thoughtSignature": "sig_content_123", "parts": []}}]}
        self.assertEqual(_extract_event_thought_signature(parsed), "sig_content_123")

    def test_extract_from_content_level_snake_case(self):
        parsed = {"candidates": [{"content": {"thought_signature": "sig_content_snake_123", "parts": []}}]}
        self.assertEqual(_extract_event_thought_signature(parsed), "sig_content_snake_123")

    def test_extract_from_parts(self):
        parsed = {"candidates": [{"content": {"parts": [{"thought": True, "text": "t", "thoughtSignature": "sig_part_123"}]}}]}
        self.assertEqual(_extract_event_thought_signature(parsed), "sig_part_123")

    def test_extract_from_parts_without_content_dict(self):
        parsed = {"candidates": [{"parts": [{"thought": True, "text": "t", "thoughtSignature": "sig_cand_part_123"}]}]}
        self.assertEqual(_extract_event_thought_signature(parsed), "sig_cand_part_123")

    def test_extract_from_function_call(self):
        parsed = {"candidates": [{"content": {"parts": [{"functionCall": {"name": "test", "thoughtSignature": "sig_fc_123"}}]}}]}
        self.assertEqual(_extract_event_thought_signature(parsed), "sig_fc_123")

    def test_extract_from_response_wrapped(self):
        parsed = {"response": {"candidates": [{"thoughtSignature": "sig_wrapped_123"}]}}
        self.assertEqual(_extract_event_thought_signature(parsed), "sig_wrapped_123")

    def test_extract_returns_none_when_absent(self):
        parsed = {"candidates": [{"content": {"parts": [{"text": "no sig"}]}}]}
        self.assertIsNone(_extract_event_thought_signature(parsed))

    def test_extract_returns_none_for_empty_or_invalid(self):
        self.assertIsNone(_extract_event_thought_signature({}))
        self.assertIsNone(_extract_event_thought_signature(None))  # type: ignore
        self.assertIsNone(_extract_event_thought_signature("invalid"))  # type: ignore
        self.assertIsNone(_extract_event_thought_signature({"candidates": []}))


if __name__ == "__main__":
    unittest.main()
