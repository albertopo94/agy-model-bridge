"""Unit tests for the OpenAI Responses API shim."""

import json
import unittest
from bridge.events import StreamEvent, ToolCallDelta, Usage
from bridge.responses import (
    ResponsesProtocolAdapter,
    responses_to_cloudcode_request,
    build_responses_completion,
    build_responses_sse_events,
    build_responses_error_response,
)
from bridge.transform import get_thought_signature, get_tool_name



class TestResponsesRequestTranslation(unittest.TestCase):
    def test_valid_request_with_instructions_and_input_strings(self):
        payload = {
            "model": "gemini-2.5-pro",
            "instructions": "Be concise.",
            "input": [
                "Hello world",
            ],
            "temperature": 0.2,
        }
        model, contents, system_inst, gen_config, tools = responses_to_cloudcode_request(
            payload, project="test-project"
        )
        self.assertEqual(model, "gemini-2.5-pro")
        self.assertEqual(system_inst, {"parts": [{"text": "Be concise."}]})
        self.assertEqual(contents, [{"role": "user", "parts": [{"text": "Hello world"}]}])
        self.assertIsNotNone(gen_config)
        self.assertEqual(gen_config["temperature"], 0.2)
        self.assertNotIn("thinkingConfig", gen_config)
        self.assertIsNone(tools)

    def test_input_with_typed_items_and_input_text_blocks(self):
        payload = {
            "model": "gemini-2.5-pro",
            "input": [
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": "What is Python?"}],
                },
                {
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "A programming language."}],
                },
                {
                    "role": "user",
                    "content": "Tell me more.",
                },
            ],
        }
        _, contents, _, _, tools = responses_to_cloudcode_request(payload, "test-project")
        self.assertEqual(len(contents), 3)
        self.assertEqual(contents[0]["role"], "user")
        self.assertEqual(contents[0]["parts"], [{"text": "What is Python?"}])
        self.assertEqual(contents[1]["role"], "model")
        self.assertEqual(contents[1]["parts"], [{"text": "A programming language."}])
        self.assertEqual(contents[2]["role"], "user")
        self.assertEqual(contents[2]["parts"], [{"text": "Tell me more."}])
        self.assertIsNone(tools)

    def test_input_as_string_normalized(self):
        payload = {
            "model": "gemini-2.5-pro",
            "input": "Single prompt string",
        }
        _, contents, _, _, tools = responses_to_cloudcode_request(payload, "test-project")
        self.assertEqual(len(contents), 1)
        self.assertEqual(contents[0]["role"], "user")
        self.assertEqual(contents[0]["parts"], [{"text": "Single prompt string"}])
        self.assertIsNone(tools)

    def test_input_with_system_and_developer_roles_extracted_to_system_instruction(self):
        payload = {
            "model": "gemini-2.5-pro",
            "input": [
                {"role": "system", "content": "System prompt."},
                {"role": "developer", "content": "Developer prompt."},
                {"role": "user", "content": "User question."},
            ],
        }
        _, contents, system_inst, _, tools = responses_to_cloudcode_request(payload, "test-project")
        self.assertEqual(
            system_inst,
            {"parts": [{"text": "System prompt.\nDeveloper prompt."}]},
        )
        self.assertEqual(len(contents), 1)
        self.assertEqual(contents[0]["role"], "user")
        self.assertEqual(contents[0]["parts"], [{"text": "User question."}])
        self.assertIsNone(tools)

    def test_input_with_function_call_output(self):
        payload = {
            "model": "gemini-2.5-pro",
            "input": [
                {
                    "type": "function_call_output",
                    "call_id": "call_123",
                    "output": "42",
                }
            ],
        }
        _, contents, _, _, tools = responses_to_cloudcode_request(payload, "test-project")
        self.assertEqual(len(contents), 1)
        self.assertEqual(contents[0]["role"], "user")
        self.assertEqual(
            contents[0]["parts"],
            [{"functionResponse": {"name": "tool", "response": {"output": "42"}}}],
        )
        self.assertIsNone(tools)

    def test_thinking_config_integration(self):
        payload_high = {
            "model": "gemini-3.1-pro-high",
            "input": ["Solve this riddle"],
        }
        _, _, _, gen_config_high, _ = responses_to_cloudcode_request(payload_high, "test-project")
        self.assertEqual(gen_config_high["thinkingConfig"], {"thinkingLevel": "HIGH"})

        payload_override = {
            "model": "gemini-3.1-pro-high",
            "input": ["Solve this riddle"],
            "reasoning_effort": "low",
        }
        _, _, _, gen_config_ovr, _ = responses_to_cloudcode_request(payload_override, "test-project")
        self.assertEqual(gen_config_ovr["thinkingConfig"], {"thinkingLevel": "LOW"})

    def test_input_as_dict_normalized(self):
        payload = {
            "model": "gemini-2.5-pro",
            "input": {"role": "user", "content": "Single dict input"},
        }
        _, contents, _, _, tools = responses_to_cloudcode_request(payload, "test-project")
        self.assertEqual(len(contents), 1)
        self.assertEqual(contents[0]["role"], "user")
        self.assertEqual(contents[0]["parts"], [{"text": "Single dict input"}])
        self.assertIsNone(tools)

    def test_input_function_call_with_dict_arguments_serialized(self):
        payload = {
            "model": "gemini-2.5-pro",
            "input": [
                {
                    "type": "function_call",
                    "name": "search",
                    "call_id": "call_search_1",
                    "arguments": {"query": "weather", "days": 3},
                }
            ],
        }
        _, contents, _, _, tools = responses_to_cloudcode_request(payload, "test-project")
        self.assertEqual(len(contents), 3)  # leading hello user turn + assistant turn + trailing continue user turn
        self.assertEqual(contents[0]["role"], "user")
        self.assertEqual(contents[1]["role"], "model")
        self.assertEqual(
            contents[1]["parts"],
            [
                {
                    "thoughtSignature": "context_engineering_is_the_way_to_go",
                    "functionCall": {"name": "search", "args": {"query": "weather", "days": 3}},
                }
            ],
        )
        self.assertEqual(contents[2]["role"], "user")
        self.assertIsNone(tools)

    def test_consecutive_function_calls_and_outputs_grouped_into_parts(self):
        payload = {
            "model": "gemini-2.5-pro",
            "input": [
                {"role": "user", "content": "Run checks"},
                {
                    "type": "function_call",
                    "call_id": "call_1",
                    "name": "exec_command",
                    "arguments": json.dumps({"cmd": "ls"}),
                },
                {
                    "type": "function_call",
                    "call_id": "call_2",
                    "name": "read_file",
                    "arguments": {"path": "a.txt"},
                },
                {
                    "type": "function_call_output",
                    "call_id": "call_1",
                    "output": "file1.txt\nfile2.txt",
                },
                {
                    "type": "function_call_output",
                    "call_id": "call_2",
                    "output": {"content": "hello world"},
                },
            ],
        }
        _, contents, _, _, _ = responses_to_cloudcode_request(payload, "test-project")
        self.assertEqual(len(contents), 3)
        # Turn 0: user message
        self.assertEqual(contents[0]["role"], "user")
        self.assertEqual(contents[0]["parts"], [{"text": "Run checks"}])
        # Turn 1: model tool calls grouped together
        self.assertEqual(contents[1]["role"], "model")
        self.assertEqual(
            contents[1]["parts"],
            [
                {
                    "thoughtSignature": "context_engineering_is_the_way_to_go",
                    "functionCall": {"name": "exec_command", "args": {"cmd": "ls"}},
                },
                {
                    "thoughtSignature": "context_engineering_is_the_way_to_go",
                    "functionCall": {"name": "read_file", "args": {"path": "a.txt"}},
                },
            ],
        )
        # Turn 2: user tool outputs grouped together with resolved function names
        self.assertEqual(contents[2]["role"], "user")
        self.assertEqual(
            contents[2]["parts"],
            [
                {
                    "functionResponse": {
                        "name": "exec_command",
                        "response": {"output": "file1.txt\nfile2.txt"},
                    }
                },
                {
                    "functionResponse": {
                        "name": "read_file",
                        "response": {"content": "hello world"},
                    }
                },
            ],
        )

    def test_assistant_message_with_content_and_function_call(self):
        payload = {
            "model": "gemini-2.5-pro",
            "input": [
                {"role": "user", "content": "Check status"},
                {
                    "role": "assistant",
                    "content": "Checking status now...",
                    "function_call": {
                        "name": "check_status",
                        "arguments": json.dumps({"service": "api"}),
                    },
                },
            ],
        }
        _, contents, _, _, _ = responses_to_cloudcode_request(payload, "test-project")
        # Leading user turn + model turn + trailing continue
        self.assertEqual(len(contents), 3)
        self.assertEqual(contents[1]["role"], "model")
        self.assertEqual(
            contents[1]["parts"],
            [
                {"text": "Checking status now..."},
                {
                    "thoughtSignature": "context_engineering_is_the_way_to_go",
                    "functionCall": {"name": "check_status", "args": {"service": "api"}},
                },
            ],
        )

    def test_thought_signature_preservation_in_function_call(self):
        sig = "dummy_signature_abc123"
        payload = {
            "model": "gemini-2.5-pro",
            "input": [
                {"role": "user", "content": "Find files"},
                {
                    "type": "function_call",
                    "call_id": "call_sig_1",
                    "name": "find",
                    "arguments": {"pattern": "*.py"},
                    "thoughtSignature": sig,
                },
                {
                    "type": "function_call_output",
                    "call_id": "call_sig_1",
                    "output": "main.py",
                },
            ],
        }
        _, contents, _, _, _ = responses_to_cloudcode_request(payload, "test-project")
        self.assertEqual(len(contents), 3)
        self.assertEqual(contents[1]["role"], "model")
        self.assertEqual(
            contents[1]["parts"][0],
            {
                "functionCall": {"name": "find", "args": {"pattern": "*.py"}},
                "thoughtSignature": sig,
            },
        )

    def test_stop_sequences_preserve_newlines_and_filter_whitespace(self):
        payload = {
            "model": "gemini-2.5-pro",
            "input": ["Hi"],
            "stop": ["", "  ", "\n", "STOP"],
        }
        _, _, _, gen_config, tools = responses_to_cloudcode_request(payload, "test-project")
        self.assertEqual(gen_config["stopSequences"], ["\n", "STOP"])
        self.assertIsNone(tools)

    def test_omitted_or_aliased_model_resolves_to_flash_tiered(self):
        # Omitted model defaults to flash-tiered with HIGH thinking
        model, _, _, gen_config, tools = responses_to_cloudcode_request(
            {"input": ["Hi"]}, "p"
        )
        self.assertEqual(model, "gemini-3.8-flash-tiered")
        self.assertEqual(gen_config.get("thinkingConfig"), {"thinkingLevel": "HIGH"})
        self.assertIsNone(tools)

        # "auto" model
        model_auto, _, _, gen_config_auto, _ = responses_to_cloudcode_request(
            {"model": "auto", "input": ["Hi"]}, "p"
        )
        self.assertEqual(model_auto, "gemini-3.8-flash-tiered")
        self.assertEqual(gen_config_auto.get("thinkingConfig"), {"thinkingLevel": "HIGH"})

        # "gemini-3.8-flash-high"
        model_fh, _, _, gen_config_fh, _ = responses_to_cloudcode_request(
            {"model": "gemini-3.8-flash-high", "input": ["Hi"]}, "p"
        )
        self.assertEqual(model_fh, "gemini-3.8-flash-tiered")
        self.assertEqual(gen_config_fh.get("thinkingConfig"), {"thinkingLevel": "HIGH"})

    def test_tools_flat_function_format_and_schema_sanitization(self):
        payload = {
            "model": "gemini-2.5-pro",
            "input": ["List files"],
            "tools": [
                {
                    "type": "function",
                    "name": "mem_current_project",
                    "description": "Get current project name and context",
                    "parameters": {
                        "$schema": "http://json-schema.org/draft-07/schema#",
                        "type": "object",
                        "properties": {
                            "detail": {
                                "type": "string",
                                "description": "Detail level",
                            }
                        },
                        "additionalProperties": False,
                    },
                }
            ],
        }
        _, _, _, _, tools = responses_to_cloudcode_request(payload)
        self.assertIsNotNone(tools)
        self.assertEqual(len(tools), 1)
        self.assertIn("functionDeclarations", tools[0])
        decls = tools[0]["functionDeclarations"]
        self.assertEqual(len(decls), 1)
        self.assertEqual(decls[0]["name"], "mem_current_project")
        self.assertEqual(decls[0]["description"], "Get current project name and context")
        params = decls[0]["parameters"]
        self.assertEqual(params["type"], "object")
        self.assertIn("detail", params["properties"])
        self.assertNotIn("$schema", params)
        self.assertNotIn("additionalProperties", params)

    def test_tools_nested_function_format(self):
        payload = {
            "model": "gemini-2.5-pro",
            "input": ["Run cmd"],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "exec_command",
                        "description": "Execute shell command",
                        "parameters": {
                            "type": "object",
                            "properties": {"cmd": {"type": "string"}},
                            "required": ["cmd"],
                        },
                    },
                }
            ],
        }
        _, _, _, _, tools = responses_to_cloudcode_request(payload)
        self.assertIsNotNone(tools)
        decls = tools[0]["functionDeclarations"]
        self.assertEqual(len(decls), 1)
        self.assertEqual(decls[0]["name"], "exec_command")
        self.assertEqual(decls[0]["description"], "Execute shell command")
        self.assertEqual(decls[0]["parameters"]["required"], ["cmd"])

    def test_tools_empty_or_invalid_returns_none(self):
        _, _, _, _, tools_empty = responses_to_cloudcode_request(
            {"model": "gemini-2.5-pro", "input": ["Hi"], "tools": []}
        )
        self.assertIsNone(tools_empty)

        _, _, _, _, tools_none = responses_to_cloudcode_request(
            {"model": "gemini-2.5-pro", "input": ["Hi"], "tools": None}
        )
        self.assertIsNone(tools_none)

        _, _, _, _, tools_noname = responses_to_cloudcode_request(
            {"model": "gemini-2.5-pro", "input": ["Hi"], "tools": [{"type": "function"}]}
        )
        self.assertIsNone(tools_noname)

    def test_invalid_model_type_raises_value_error(self):
        with self.assertRaises(ValueError):
            responses_to_cloudcode_request({"model": 12345, "input": ["Hi"]}, "p")

    def test_validation_missing_or_empty_input_raises_value_error(self):
        with self.assertRaises(ValueError):
            responses_to_cloudcode_request({"model": "gemini-2.5-pro"}, "p")
        with self.assertRaises(ValueError):
            responses_to_cloudcode_request({"model": "gemini-2.5-pro", "input": []}, "p")


class TestResponsesResponseBuilder(unittest.TestCase):
    def test_build_responses_completion_structure(self):
        resp = build_responses_completion(
            response_id="resp_123456",
            model="gemini-2.5-pro",
            text="Completed answer from Codex shim",
            usage={"prompt_tokens": 15, "completion_tokens": 25, "total_tokens": 40},
        )
        self.assertEqual(resp["id"], "resp_123456")
        self.assertEqual(resp["object"], "response")
        self.assertEqual(resp["status"], "completed")
        self.assertEqual(resp["model"], "gemini-2.5-pro")
        self.assertIsInstance(resp["created"], int)

        output = resp["output"]
        self.assertEqual(len(output), 1)
        item = output[0]
        self.assertTrue(item["id"].startswith("msg_"))
        self.assertEqual(item["type"], "message")
        self.assertEqual(item["role"], "assistant")
        self.assertEqual(
            item["content"],
            [{"type": "output_text", "text": "Completed answer from Codex shim"}],
        )

        self.assertEqual(
            resp["usage"],
            {"input_tokens": 15, "output_tokens": 25, "total_tokens": 40},
        )

    def test_build_responses_completion_with_tool_calls(self):
        tool_calls = [
            {
                "id": "call_abc123",
                "name": "mem_current_project",
                "args": {"detail": "summary"},
            }
        ]
        resp = build_responses_completion(
            response_id="resp_123456",
            model="gemini-2.5-pro",
            text="",
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            tool_calls=tool_calls,
        )
        output = resp["output"]
        self.assertEqual(len(output), 1)
        self.assertEqual(output[0]["type"], "function_call")
        self.assertEqual(output[0]["status"], "completed")
        self.assertEqual(output[0]["call_id"], "call_abc123")
        self.assertEqual(output[0]["name"], "mem_current_project")
        self.assertEqual(output[0]["arguments"], '{"detail": "summary"}')

    def test_build_responses_completion_with_text_and_tool_calls(self):
        tool_calls = [
            {
                "id": "call_xyz",
                "name": "exec_command",
                "args": {"cmd": "ls"},
            }
        ]
        resp = build_responses_completion(
            response_id="resp_123456",
            model="gemini-2.5-pro",
            text="Let me check the files.",
            tool_calls=tool_calls,
        )
        output = resp["output"]
        self.assertEqual(len(output), 2)
        self.assertEqual(output[0]["type"], "message")
        self.assertEqual(output[0]["content"][0]["text"], "Let me check the files.")
        self.assertEqual(output[1]["type"], "function_call")
        self.assertEqual(output[1]["call_id"], "call_xyz")
        self.assertEqual(output[1]["name"], "exec_command")
        self.assertEqual(output[1]["arguments"], '{"cmd": "ls"}')


class TestResponsesSSEEvents(unittest.TestCase):
    def test_build_responses_sse_events_sequence(self):
        mock_upstream_lines = [
            'data: {"candidates": [{"content": {"parts": [{"thought": true, "text": "internal thought"}]}}]}\n',
            'data: {"candidates": [{"content": {"parts": [{"text": "Hello "}]}}]}\n',
            'data: {"candidates": [{"content": {"parts": [{"text": "Codex!"}]}}], "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 10, "totalTokenCount": 15}}\n',
            'data: {"candidates": [{"finishReason": "STOP"}]}\n',
        ]

        events = list(build_responses_sse_events(iter(mock_upstream_lines), "gemini-2.5-pro"))
        self.assertGreater(len(events), 0)

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
        expected_sequence = [
            "response.created",
            "response.in_progress",
            "response.output_item.added",
            "response.content_part.added",
            "response.output_text.delta",
            "response.output_text.delta",
            "response.output_text.done",
            "response.content_part.done",
            "response.output_item.done",
            "response.completed",
        ]
        self.assertEqual(event_names, expected_sequence)

        # Check sequence numbers
        for idx, (_, data) in enumerate(parsed_events):
            self.assertEqual(data.get("sequence_number"), idx)

        # Check response.created
        created_event = parsed_events[0][1]
        self.assertEqual(created_event["response"]["status"], "in_progress")
        resp_id = created_event["response"]["id"]
        self.assertTrue(resp_id.startswith("resp_"))

        # Check deltas include type, response_id, and exclude thoughts
        delta_events = [e[1] for e in parsed_events if e[0] == "response.output_text.delta"]
        self.assertEqual(len(delta_events), 2)
        for d in delta_events:
            self.assertEqual(d.get("type"), "response.output_text.delta")
            self.assertEqual(d.get("response_id"), resp_id)
        deltas = [d["delta"] for d in delta_events]
        self.assertEqual(deltas, ["Hello ", "Codex!"])

        # Check response.output_text.done
        text_done_event = next(e[1] for e in parsed_events if e[0] == "response.output_text.done")
        self.assertEqual(text_done_event.get("type"), "response.output_text.done")
        self.assertEqual(text_done_event.get("response_id"), resp_id)
        self.assertEqual(text_done_event.get("text"), "Hello Codex!")
        self.assertEqual(text_done_event.get("output_index"), 0)
        self.assertEqual(text_done_event.get("content_index"), 0)

        # Check response.completed
        completed_event = parsed_events[-1][1]
        self.assertEqual(completed_event["response"]["status"], "completed")
        self.assertEqual(
            completed_event["response"]["output"][0]["content"][0]["text"],
            "Hello Codex!",
        )
        self.assertEqual(completed_event["response"]["usage"]["total_tokens"], 15)

    def test_build_responses_sse_events_lazy_text_opening_when_no_text(self):
        mock_upstream_lines = [
            'data: {"candidates": [{"content": {"parts": [{"thought": true, "text": "internal thought"}]}}]}\n',
            'data: {"candidates": [{"finishReason": "STOP"}]}\n',
        ]
        events = list(build_responses_sse_events(iter(mock_upstream_lines), "gemini-2.5-pro"))
        parsed_events = []
        for raw in events:
            for l in raw.strip().split("\n"):
                if l.startswith("data:"):
                    parsed_events.append(json.loads(l[5:].strip()))

        event_types = [p.get("type") for p in parsed_events]
        self.assertEqual(
            event_types,
            ["response.created", "response.in_progress", "response.completed"],
        )
        completed_event = parsed_events[-1]
        self.assertEqual(completed_event["response"]["output"], [])
        self.assertEqual(completed_event["response"]["output_text"], "")

    def test_build_responses_sse_events_function_call(self):
        mock_upstream_lines = [
            'data: {"candidates": [{"content": {"parts": [{"functionCall": {"name": "mem_current_project", "args": {"detail": "summary"}}}]}}]}\n',
            'data: {"candidates": [{"finishReason": "STOP"}]}\n',
        ]
        events = list(build_responses_sse_events(iter(mock_upstream_lines), "gemini-2.5-pro"))
        parsed_events = []
        for raw in events:
            for l in raw.strip().split("\n"):
                if l.startswith("data:"):
                    parsed_events.append(json.loads(l[5:].strip()))

        event_types = [p.get("type") for p in parsed_events]
        expected_types = [
            "response.created",
            "response.in_progress",
            "response.output_item.added",
            "response.function_call_arguments.delta",
            "response.function_call_arguments.done",
            "response.output_item.done",
            "response.completed",
        ]
        self.assertEqual(event_types, expected_types)

        # Check sequence numbers
        for idx, p in enumerate(parsed_events):
            self.assertEqual(p.get("sequence_number"), idx)

        # Check function call item added
        fc_item_added = parsed_events[2]
        self.assertEqual(fc_item_added["output_index"], 0)
        self.assertEqual(fc_item_added["item"]["type"], "function_call")
        self.assertEqual(fc_item_added["item"]["status"], "in_progress")
        self.assertEqual(fc_item_added["item"]["name"], "mem_current_project")
        self.assertEqual(fc_item_added["item"]["arguments"], "")

        # Check delta and done
        fc_delta = parsed_events[3]
        self.assertEqual(fc_delta["delta"], '{"detail": "summary"}')
        fc_done = parsed_events[4]
        self.assertEqual(fc_done["arguments"], '{"detail": "summary"}')

        # Check function call item done
        fc_item_done = parsed_events[5]
        self.assertEqual(fc_item_done["item"]["status"], "completed")
        self.assertEqual(fc_item_done["item"]["arguments"], '{"detail": "summary"}')

        # Check completed response output
        completed_resp = parsed_events[6]["response"]
        self.assertEqual(len(completed_resp["output"]), 1)
        self.assertEqual(completed_resp["output"][0]["type"], "function_call")
        self.assertEqual(completed_resp["output"][0]["name"], "mem_current_project")
        self.assertEqual(completed_resp["output"][0]["arguments"], '{"detail": "summary"}')

    def test_build_responses_sse_events_text_followed_by_function_call(self):
        mock_upstream_lines = [
            'data: {"candidates": [{"content": {"parts": [{"text": "Checking project:"}]}}]}\n',
            'data: {"candidates": [{"content": {"parts": [{"functionCall": {"name": "mem_current_project", "args": {}}}]}}]}\n',
            'data: {"candidates": [{"finishReason": "STOP"}]}\n',
        ]
        events = list(build_responses_sse_events(iter(mock_upstream_lines), "gemini-2.5-pro"))
        parsed_events = []
        for raw in events:
            for l in raw.strip().split("\n"):
                if l.startswith("data:"):
                    parsed_events.append(json.loads(l[5:].strip()))

        event_types = [p.get("type") for p in parsed_events]
        expected_types = [
            "response.created",
            "response.in_progress",
            "response.output_item.added",
            "response.content_part.added",
            "response.output_text.delta",
            "response.output_text.done",
            "response.content_part.done",
            "response.output_item.done",
            "response.output_item.added",
            "response.function_call_arguments.delta",
            "response.function_call_arguments.done",
            "response.output_item.done",
            "response.completed",
        ]
        self.assertEqual(event_types, expected_types)

        # Output index for text item should be 0, and for fc item should be 1
        self.assertEqual(parsed_events[2]["output_index"], 0)
        self.assertEqual(parsed_events[8]["output_index"], 1)

        completed_resp = parsed_events[-1]["response"]
        self.assertEqual(len(completed_resp["output"]), 2)
        self.assertEqual(completed_resp["output"][0]["type"], "message")
        self.assertEqual(completed_resp["output"][1]["type"], "function_call")

    def test_build_responses_sse_events_with_custom_response_id(self):
        chunks = [
            'data: {"response": {"candidates": [{"content": {"parts": [{"text": "Hi"}]}}]}}\n\n',
        ]
        custom_id = "resp_custom_9999"
        events = list(build_responses_sse_events(iter(chunks), "gemini-2.5-pro", response_id=custom_id))
        parsed = [json.loads(e.split("data: ")[1].strip()) for e in events if "data: " in e]
        self.assertEqual(parsed[0]["response"]["id"], custom_id)
        delta_event = next(p for p in parsed if p.get("type") == "response.output_text.delta")
        self.assertEqual(delta_event["response_id"], custom_id)


class TestResponsesErrorResponses(unittest.TestCase):
    def test_error_status_and_schema_mapping(self):
        code, err = build_responses_error_response(400, "Bad input format")
        self.assertEqual(code, 400)
        self.assertEqual(err["error"]["type"], "invalid_request_error")
        self.assertEqual(err["error"]["code"], 400)
        self.assertEqual(err["error"]["message"], "Bad input format")

        code, err = build_responses_error_response(503, "Capacity exhausted")
        self.assertEqual(code, 503)
        self.assertEqual(err["error"]["type"], "api_error")


class TestResponsesStreamEventAndAdapter(unittest.TestCase):
    def test_build_responses_sse_events_with_stream_events_text_and_usage(self):
        stream_events = [
            StreamEvent(delta_text="Hello "),
            StreamEvent(
                delta_text="world!",
                usage=Usage(prompt_tokens=8, completion_tokens=12, total_tokens=20),
            ),
        ]
        events = list(build_responses_sse_events(iter(stream_events), "gemini-2.5-pro"))
        parsed_events = []
        for raw in events:
            for line in raw.strip().split("\n"):
                if line.startswith("data:"):
                    parsed_events.append(json.loads(line[5:].strip()))

        event_types = [p.get("type") for p in parsed_events]
        expected_types = [
            "response.created",
            "response.in_progress",
            "response.output_item.added",
            "response.content_part.added",
            "response.output_text.delta",
            "response.output_text.delta",
            "response.output_text.done",
            "response.content_part.done",
            "response.output_item.done",
            "response.completed",
        ]
        self.assertEqual(event_types, expected_types)

        deltas = [p.get("delta") for p in parsed_events if p.get("type") == "response.output_text.delta"]
        self.assertEqual(deltas, ["Hello ", "world!"])

        completed = parsed_events[-1]["response"]
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["output_text"], "Hello world!")
        self.assertEqual(completed["usage"]["total_tokens"], 20)
        self.assertEqual(completed["usage"]["input_tokens"], 8)
        self.assertEqual(completed["usage"]["output_tokens"], 12)

    def test_build_responses_sse_events_with_stream_events_tool_calls(self):
        stream_events = [
            StreamEvent(delta_text="Running tool: "),
            StreamEvent(
                tool_calls=[
                    ToolCallDelta(
                        id="call_evt_123",
                        name="get_weather",
                        args={"city": "Madrid"},
                        thought_signature="sig_direct_tc",
                    )
                ]
            ),
        ]
        events = list(build_responses_sse_events(iter(stream_events), "gemini-2.5-pro"))
        parsed_events = []
        for raw in events:
            for line in raw.strip().split("\n"):
                if line.startswith("data:"):
                    parsed_events.append(json.loads(line[5:].strip()))

        event_types = [p.get("type") for p in parsed_events]
        self.assertIn("response.output_item.added", event_types)
        self.assertIn("response.function_call_arguments.delta", event_types)
        self.assertIn("response.function_call_arguments.done", event_types)

        fc_items = [
            p["item"]
            for p in parsed_events
            if p.get("type") == "response.output_item.done" and p.get("item", {}).get("type") == "function_call"
        ]
        self.assertEqual(len(fc_items), 1)
        self.assertEqual(fc_items[0]["call_id"], "call_evt_123")
        self.assertEqual(fc_items[0]["name"], "get_weather")
        self.assertEqual(json.loads(fc_items[0]["arguments"]), {"city": "Madrid"})

        # Thought signature and tool name should be cached
        self.assertEqual(get_thought_signature("call_evt_123"), "sig_direct_tc")
        self.assertEqual(get_tool_name("call_evt_123"), "get_weather")

    def test_build_responses_sse_events_thought_signature_preserved_across_events(self):
        stream_events = [
            StreamEvent(thought_signature="sig_stream_level_preservation"),
            StreamEvent(
                tool_calls=[
                    ToolCallDelta(
                        id="call_inherited_sig",
                        name="do_action",
                        args={"action": "test"},
                    )
                ]
            ),
        ]
        list(build_responses_sse_events(iter(stream_events), "gemini-2.5-pro"))
        self.assertEqual(get_thought_signature("call_inherited_sig"), "sig_stream_level_preservation")

    def test_build_responses_sse_events_tool_call_signature_overrides_event_signature(self):
        stream_events = [
            StreamEvent(
                thought_signature="sig_fallback",
                tool_calls=[
                    ToolCallDelta(
                        id="call_overridden_sig",
                        name="do_action",
                        args={},
                        thought_signature="sig_specific",
                    )
                ],
            ),
        ]
        list(build_responses_sse_events(iter(stream_events), "gemini-2.5-pro"))
        self.assertEqual(get_thought_signature("call_overridden_sig"), "sig_specific")

    def test_responses_protocol_adapter_methods(self):
        payload = {"model": "gemini-2.5-pro", "input": "Hello"}
        model, contents, sys_inst, gen_cfg, tools = ResponsesProtocolAdapter.transform_request(payload, "proj-1")
        self.assertEqual(model, "gemini-2.5-pro")
        self.assertEqual(len(contents), 1)

        resp = ResponsesProtocolAdapter.build_response(
            "resp_adapter_test",
            "gemini-2.5-pro",
            "Hi there!",
            usage={"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
        )
        self.assertEqual(resp["id"], "resp_adapter_test")
        self.assertEqual(resp["output"][0]["content"][0]["text"], "Hi there!")
        self.assertEqual(resp["usage"]["total_tokens"], 7)

        stream_gen = ResponsesProtocolAdapter.build_stream(
            iter([StreamEvent(delta_text="Stream from adapter")]),
            "gemini-2.5-pro",
            response_id="resp_stream_test",
        )
        events = list(stream_gen)
        self.assertGreater(len(events), 0)
        self.assertTrue(any("Stream from adapter" in e for e in events))


if __name__ == "__main__":
    unittest.main()

