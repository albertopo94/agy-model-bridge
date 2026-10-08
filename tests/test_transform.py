import unittest
import json
import uuid
from bridge.transform import (
    openai_to_cloudcode_request,
    parse_cloudcode_sse_event,
    extract_text_delta,
    extract_thought_delta,
    extract_function_calls,
    extract_finish_reason,
    extract_usage,
    build_openai_chunk,
    build_openai_completion,
    build_openai_model_list,
    build_openai_error_response,
    check_sse_error,
    build_thinking_config,
    resolve_model_and_thinking,
    sanitize_schema_for_gemini,
)
from bridge.client import (
    BridgeError,
    RateLimitError,
    CapacityExhaustedError,
    AuthenticationError,
    ForbiddenError,
)


class TestOpenAIToCloudCodeRequest(unittest.TestCase):
    def test_valid_request_with_system_and_user_messages(self):
        payload = {
            "model": "gemini-2.5-pro",
            "messages": [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Hello world"},
            ],
        }
        model, contents, system_instruction, gen_config, tools = openai_to_cloudcode_request(
            payload, project="aicode-consumers"
        )
        self.assertEqual(model, "gemini-2.5-pro")
        self.assertEqual(
            system_instruction,
            {"parts": [{"text": "You are a helpful assistant."}]},
        )
        self.assertEqual(
            contents,
            [{"role": "user", "parts": [{"text": "Hello world"}]}],
        )
        self.assertIsNone(gen_config)
        self.assertIsNone(tools)

    def test_valid_request_multi_turn_conversation(self):
        payload = {
            "model": "gemini-2.5-flash",
            "messages": [
                {"role": "user", "content": "Hi"},
                {"role": "assistant", "content": "Hello! How can I help you?"},
                {"role": "user", "content": "Tell me a joke"},
            ],
        }
        model, contents, system_instruction, gen_config, tools = openai_to_cloudcode_request(
            payload, project="test-project"
        )
        self.assertEqual(model, "gemini-2.5-flash")
        self.assertIsNone(system_instruction)
        self.assertEqual(
            contents,
            [
                {"role": "user", "parts": [{"text": "Hi"}]},
                {"role": "model", "parts": [{"text": "Hello! How can I help you?"}]},
                {"role": "user", "parts": [{"text": "Tell me a joke"}]},
            ],
        )
        self.assertIsNone(gen_config)
        self.assertIsNone(tools)

    def test_multiple_system_messages_concatenated(self):
        payload = {
            "model": "gemini-2.5-pro",
            "messages": [
                {"role": "system", "content": "Instruction 1."},
                {"role": "system", "content": "Instruction 2."},
                {"role": "user", "content": "Action"},
            ],
        }
        _, _, system_instruction, _, _ = openai_to_cloudcode_request(
            payload, project="test-project"
        )
        self.assertIsNotNone(system_instruction)
        self.assertEqual(
            system_instruction["parts"],
            [{"text": "Instruction 1.\nInstruction 2."}],
        )

    def test_developer_role_treated_as_system(self):
        payload = {
            "model": "gemini-2.5-pro",
            "messages": [
                {"role": "developer", "content": "Developer instructions."},
                {"role": "user", "content": "Hello"},
            ],
        }
        _, _, system_instruction, _, _ = openai_to_cloudcode_request(
            payload, project="test-project"
        )
        self.assertIsNotNone(system_instruction)
        self.assertEqual(
            system_instruction["parts"],
            [{"text": "Developer instructions."}],
        )

    def test_content_none_handled_safely(self):
        payload = {
            "model": "gemini-2.5-pro",
            "messages": [
                {"role": "user", "content": None},
            ],
        }
        _, contents, _, _, _ = openai_to_cloudcode_request(payload, project="test-project")
        self.assertEqual(
            contents,
            [{"role": "user", "parts": [{"text": " "}]}],
        )

    def test_conversation_starting_with_model_prepends_hello_user_turn(self):
        payload = {
            "model": "gemini-2.5-flash",
            "messages": [
                {"role": "assistant", "content": "How can I help you today?"},
                {"role": "user", "content": "Tell me a joke"},
            ],
        }
        _, contents, _, _, _ = openai_to_cloudcode_request(payload, project="test-project")
        self.assertEqual(
            contents,
            [
                {"role": "user", "parts": [{"text": "Hello"}]},
                {"role": "model", "parts": [{"text": "How can I help you today?"}]},
                {"role": "user", "parts": [{"text": "Tell me a joke"}]},
            ],
        )

    def test_single_assistant_message_prepends_hello_and_appends_continue(self):
        payload = {
            "model": "gemini-2.5-flash",
            "messages": [
                {"role": "assistant", "content": "How can I help you today?"},
            ],
        }
        _, contents, _, _, _ = openai_to_cloudcode_request(payload, project="test-project")
        self.assertEqual(
            contents,
            [
                {"role": "user", "parts": [{"text": "Hello"}]},
                {"role": "model", "parts": [{"text": "How can I help you today?"}]},
                {"role": "user", "parts": [{"text": "Continue"}]},
            ],
        )

    def test_empty_and_whitespace_content_prevented_in_parts(self):
        payload = {
            "model": "gemini-2.5-pro",
            "messages": [
                {"role": "user", "content": ""},
                {"role": "assistant", "content": "   "},
                {"role": "user", "content": "\t\n "},
            ],
        }
        _, contents, _, _, _ = openai_to_cloudcode_request(payload, project="test-project")
        self.assertEqual(
            contents,
            [
                {"role": "user", "parts": [{"text": " "}]},
                {"role": "model", "parts": [{"text": " "}]},
                {"role": "user", "parts": [{"text": " "}]},
            ],
        )

    def test_invalid_model_type_raises_value_error(self):
        payload = {
            "model": 12345,
            "messages": [{"role": "user", "content": "Hello"}],
        }
        with self.assertRaises(ValueError) as ctx:
            openai_to_cloudcode_request(payload, project="test-project")
        self.assertIn("model", str(ctx.exception).lower())

    def test_empty_or_missing_messages_raises_value_error(self):
        with self.assertRaises(ValueError) as ctx1:
            openai_to_cloudcode_request({"model": "test"}, project="test-project")
        self.assertIn("messages", str(ctx1.exception).lower())

        with self.assertRaises(ValueError) as ctx2:
            openai_to_cloudcode_request(
                {"model": "test", "messages": []}, project="test-project"
            )
        self.assertIn("messages", str(ctx2.exception).lower())

    def test_invalid_role_raises_value_error(self):
        payload = {
            "model": "gemini-2.5-pro",
            "messages": [{"role": "unknown_role", "content": "Hello"}],
        }
        with self.assertRaises(ValueError) as ctx:
            openai_to_cloudcode_request(payload, project="test-project")
        self.assertIn("role", str(ctx.exception).lower())

    def test_multimodal_content_list_text_extraction(self):
        payload = {
            "model": "gemini-2.5-pro",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Hello "},
                        {"type": "text", "text": "world!"},
                    ],
                }
            ],
        }
        _, contents, _, _, _ = openai_to_cloudcode_request(payload, project="test-project")
        self.assertEqual(
            contents,
            [{"role": "user", "parts": [{"text": "Hello world!"}]}],
        )

    def test_multimodal_content_list_with_image_dropped_safely(self):
        payload = {
            "model": "gemini-2.5-pro",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": "https://example.com/img.png"}},
                        {"type": "text", "text": "Describe this image."},
                    ],
                }
            ],
        }
        _, contents, _, _, _ = openai_to_cloudcode_request(payload, project="test-project")
        self.assertEqual(
            contents,
            [{"role": "user", "parts": [{"text": "Describe this image."}]}],
        )

    def test_multimodal_content_dict_with_only_text_key(self):
        payload = {
            "model": "gemini-2.5-pro",
            "messages": [
                {
                    "role": "user",
                    "content": [{"text": "Just text item"}],
                }
            ],
        }
        _, contents, _, _, _ = openai_to_cloudcode_request(payload, project="test-project")
        self.assertEqual(
            contents,
            [{"role": "user", "parts": [{"text": "Just text item"}]}],
        )

    def test_multimodal_content_list_with_strings(self):
        payload = {
            "model": "gemini-2.5-pro",
            "messages": [
                {
                    "role": "user",
                    "content": ["First paragraph.\n", "Second paragraph."],
                }
            ],
        }
        _, contents, _, _, _ = openai_to_cloudcode_request(payload, project="test-project")
        self.assertEqual(
            contents,
            [{"role": "user", "parts": [{"text": "First paragraph.\nSecond paragraph."}]}],
        )

    def test_assistant_tool_calls_extracted_when_content_empty(self):
        payload = {
            "model": "gemini-2.5-pro",
            "messages": [
                {"role": "user", "content": "What is the weather?"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_123",
                            "type": "function",
                            "function": {"name": "get_weather", "arguments": '{"location": "Tokyo"}'},
                        }
                    ],
                },
            ],
        }
        _, contents, _, _, _ = openai_to_cloudcode_request(payload, project="test-project")
        # Conversation ends with model, so helper appends a user "Continue" turn
        self.assertEqual(contents[0]["role"], "user")
        self.assertEqual(contents[1]["role"], "model")
        self.assertEqual(
            contents[1]["parts"],
            [
                {
                    "thoughtSignature": "context_engineering_is_the_way_to_go",
                    "functionCall": {"name": "get_weather", "args": {"location": "Tokyo"}},
                }
            ],
        )

    def test_only_system_messages_raises_value_error(self):
        payload = {
            "model": "gemini-2.5-pro",
            "messages": [{"role": "system", "content": "You are a helpful assistant."}],
        }
        with self.assertRaises(ValueError) as ctx:
            openai_to_cloudcode_request(payload, project="test-project")
        self.assertIn("at least one message is required", str(ctx.exception))

    def test_only_developer_messages_raises_value_error(self):
        payload = {
            "model": "gemini-2.5-pro",
            "messages": [{"role": "developer", "content": "System prompt"}],
        }
        with self.assertRaises(ValueError) as ctx:
            openai_to_cloudcode_request(payload, project="test-project")
        self.assertIn("at least one message is required", str(ctx.exception))

    def test_multimodal_content_list_with_none_text(self):
        payload = {
            "model": "gemini-2.5-pro",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": None},
                        {"type": "text", "text": "hello"},
                    ],
                }
            ],
        }
        _, contents, _, _, _ = openai_to_cloudcode_request(payload, project="test-project")
        self.assertEqual(contents, [{"role": "user", "parts": [{"text": "hello"}]}])

    def test_empty_system_instruction_returns_none(self):
        payload = {
            "model": "gemini-2.5-pro",
            "messages": [
                {"role": "system", "content": ""},
                {"role": "user", "content": "hello"},
            ],
        }
        _, _, system_instruction, _, _ = openai_to_cloudcode_request(payload, project="test-project")
        self.assertIsNone(system_instruction)

    def test_whitespace_system_instruction_returns_none(self):
        payload = {
            "model": "gemini-2.5-pro",
            "messages": [
                {"role": "system", "content": "   \n\t  "},
                {"role": "user", "content": "hello"},
            ],
        }
        _, _, system_instruction, _, _ = openai_to_cloudcode_request(payload, project="test-project")
        self.assertIsNone(system_instruction)

    def test_generation_config_mapping_sampling_params(self):
        payload = {
            "model": "gemini-2.5-pro",
            "messages": [{"role": "user", "content": "hello"}],
            "temperature": 0.7,
            "max_tokens": 100,
            "top_p": 0.95,
            "stop": ["END", "STOP"],
        }
        _, _, _, gen_config, _ = openai_to_cloudcode_request(payload, project="test-project")
        self.assertEqual(
            gen_config,
            {
                "temperature": 0.7,
                "maxOutputTokens": 100,
                "topP": 0.95,
                "stopSequences": ["END", "STOP"],
            },
        )

    def test_generation_config_max_completion_tokens_and_string_stop(self):
        payload = {
            "model": "gemini-2.5-pro",
            "messages": [{"role": "user", "content": "hello"}],
            "max_completion_tokens": 256,
            "stop": "STOP_TOKEN",
        }
        _, _, _, gen_config, _ = openai_to_cloudcode_request(payload, project="test-project")
        self.assertEqual(
            gen_config,
            {
                "maxOutputTokens": 256,
                "stopSequences": ["STOP_TOKEN"],
            },
        )

    def test_generation_config_absent_returns_none(self):
        payload = {
            "model": "custom-model",
            "messages": [{"role": "user", "content": "hello"}],
        }
        _, _, _, gen_config, _ = openai_to_cloudcode_request(payload, project="test-project")
        self.assertIsNone(gen_config)

    def test_generation_config_stop_empty_sequences_omitted(self):
        for empty_stop in ("", [], ["", "   "]):
            with self.subTest(empty_stop=empty_stop):
                payload = {
                    "model": "custom-model",
                    "messages": [{"role": "user", "content": "hello"}],
                    "stop": empty_stop,
                }
                _, _, _, gen_config, _ = openai_to_cloudcode_request(payload, project="test-project")
                self.assertIsNone(gen_config)

    def test_generation_config_stop_filters_empty_strings(self):
        payload = {
            "model": "gemini-2.5-pro",
            "messages": [{"role": "user", "content": "hello"}],
            "stop": ["", "STOP_TOKEN", "   ", "END"],
        }
        _, _, _, gen_config, _ = openai_to_cloudcode_request(payload, project="test-project")
        self.assertEqual(
            gen_config,
            {
                "stopSequences": ["STOP_TOKEN", "END"],
            },
        )

    def test_tool_and_function_roles_mapped_to_user_with_prefix(self):
        payload = {
            "model": "gemini-2.5-pro",
            "messages": [
                {"role": "user", "content": "Call tool"},
                {"role": "assistant", "content": "Calling tool..."},
                {"role": "tool", "content": "Result from tool"},
                {"role": "assistant", "content": "Calling function..."},
                {"role": "function", "content": "Result from func"},
            ],
        }
        _, contents, _, _, _ = openai_to_cloudcode_request(payload, project="test-project")
        self.assertEqual(
            contents,
            [
                {"role": "user", "parts": [{"text": "Call tool"}]},
                {"role": "model", "parts": [{"text": "Calling tool..."}]},
                {"role": "user", "parts": [{"functionResponse": {"name": "tool", "response": {"output": "Result from tool"}}}]},
                {"role": "model", "parts": [{"text": "Calling function..."}]},
                {"role": "user", "parts": [{"functionResponse": {"name": "tool", "response": {"output": "Result from func"}}}]},
            ],
        )

    def test_consecutive_same_role_messages_merged(self):
        payload = {
            "model": "gemini-2.5-pro",
            "messages": [
                {"role": "user", "content": "Question 1"},
                {"role": "user", "content": "Question 2"},
                {"role": "assistant", "content": "Answer 1"},
                {"role": "assistant", "content": "Answer 2"},
                {"role": "user", "content": "Followup"},
                {"role": "tool", "content": "Tool output"},
            ],
        }
        _, contents, _, _, _ = openai_to_cloudcode_request(payload, project="test-project")
        self.assertEqual(
            contents,
            [
                {"role": "user", "parts": [{"text": "Question 1"}, {"text": "Question 2"}]},
                {"role": "model", "parts": [{"text": "Answer 1"}, {"text": "Answer 2"}]},
                {"role": "user", "parts": [{"text": "Followup"}, {"functionResponse": {"name": "tool", "response": {"output": "Tool output"}}}]},
            ],
        )

    def test_conversation_ending_with_assistant_appends_continue_user_turn(self):
        payload = {
            "model": "gemini-2.5-pro",
            "messages": [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "How can I help you?"},
            ],
        }
        _, contents, _, _, _ = openai_to_cloudcode_request(payload, project="test-project")
        self.assertEqual(
            contents,
            [
                {"role": "user", "parts": [{"text": "Hello"}]},
                {"role": "model", "parts": [{"text": "How can I help you?"}]},
                {"role": "user", "parts": [{"text": "Continue"}]},
            ],
        )


class TestParseCloudCodeSSEEvent(unittest.TestCase):
    def test_parse_valid_sse_data_line(self):
        line = 'data: {"candidates": [{"content": {"parts": [{"text": "hello"}]}}]}\n'
        parsed = parse_cloudcode_sse_event(line)
        self.assertIsInstance(parsed, dict)
        self.assertIn("candidates", parsed)

    def test_parse_done_returns_none(self):
        self.assertIsNone(parse_cloudcode_sse_event("data: [DONE]"))
        self.assertIsNone(parse_cloudcode_sse_event("data: [DONE]\n"))

    def test_parse_empty_or_heartbeat_returns_none(self):
        self.assertIsNone(parse_cloudcode_sse_event(""))
        self.assertIsNone(parse_cloudcode_sse_event("\n"))
        self.assertIsNone(parse_cloudcode_sse_event(":ping\n"))
        self.assertIsNone(parse_cloudcode_sse_event("   "))

    def test_parse_invalid_json_returns_none(self):
        self.assertIsNone(parse_cloudcode_sse_event("data: {invalid json}"))


class TestExtractTextDeltaAndFiltering(unittest.TestCase):
    def test_extract_standard_text_delta(self):
        event = {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": "Hello world!"}],
                        "role": "model",
                    }
                }
            ]
        }
        delta = extract_text_delta(event)
        self.assertEqual(delta, "Hello world!")

    def test_filter_thought_block(self):
        event = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"thought": True, "text": "Let me think about this."},
                        ],
                        "role": "model",
                    }
                }
            ]
        }
        delta = extract_text_delta(event)
        self.assertIsNone(delta)

    def test_filter_thought_signature(self):
        event = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"thoughtSignature": "xyz123", "text": "Internal CoT"},
                        ],
                        "role": "model",
                    }
                }
            ]
        }
        delta = extract_text_delta(event)
        self.assertEqual(delta, "Internal CoT")

    def test_extract_text_delta_with_response_wrapper(self):
        event = {
            "response": {
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": "Wrapped delta"}],
                            "role": "model",
                        }
                    }
                ]
            }
        }
        delta = extract_text_delta(event)
        self.assertEqual(delta, "Wrapped delta")

    def test_mixed_parts_extracts_only_clean_text(self):
        event = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"thought": True, "text": "Thinking..."},
                            {"text": "The answer is 42."},
                        ],
                        "role": "model",
                    }
                }
            ]
        }
        delta = extract_text_delta(event)
        self.assertEqual(delta, "The answer is 42.")

    def test_empty_candidates_or_parts_returns_none(self):
        self.assertIsNone(extract_text_delta({}))
        self.assertIsNone(extract_text_delta({"candidates": []}))
        self.assertIsNone(extract_text_delta({"candidates": [{}]}))
        self.assertIsNone(extract_text_delta({"candidates": [{"content": {}}]}))
        self.assertIsNone(
            extract_text_delta({"candidates": [{"content": {"parts": []}}]})
        )


class TestExtractThoughtDelta(unittest.TestCase):
    def test_extract_standard_thought_delta(self):
        event = {
            "candidates": [
                {
                    "content": {
                        "parts": [{"thought": True, "text": "Analyzing the codebase..."}],
                        "role": "model",
                    }
                }
            ]
        }
        delta = extract_thought_delta(event)
        self.assertEqual(delta, "Analyzing the codebase...")

    def test_non_thought_parts_return_none(self):
        event = {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": "Hello world!"}],
                        "role": "model",
                    }
                }
            ]
        }
        self.assertIsNone(extract_thought_delta(event))

    def test_extract_thought_delta_with_response_wrapper(self):
        event = {
            "response": {
                "candidates": [
                    {
                        "content": {
                            "parts": [{"thought": True, "text": "Wrapped thought"}],
                            "role": "model",
                        }
                    }
                ]
            }
        }
        self.assertEqual(extract_thought_delta(event), "Wrapped thought")

    def test_multiple_thought_parts_concatenated(self):
        event = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"thought": True, "text": "Part 1. "},
                            {"thought": True, "text": "Part 2."},
                        ],
                        "role": "model",
                    }
                }
            ]
        }
        self.assertEqual(extract_thought_delta(event), "Part 1. Part 2.")

    def test_mixed_parts_extracts_only_thoughts(self):
        event = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"thought": True, "text": "Deep thinking"},
                            {"text": "Answer"},
                        ],
                        "role": "model",
                    }
                }
            ]
        }
        self.assertEqual(extract_thought_delta(event), "Deep thinking")

    def test_empty_candidates_or_parts_returns_none(self):
        self.assertIsNone(extract_thought_delta({}))
        self.assertIsNone(extract_thought_delta({"candidates": []}))
        self.assertIsNone(extract_thought_delta({"candidates": [{}]}))
        self.assertIsNone(extract_thought_delta(None))


class TestExtractFunctionCalls(unittest.TestCase):
    def test_extract_standard_function_call(self):
        event = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "functionCall": {
                                    "name": "run_command",
                                    "args": {"command": "ls -la"},
                                }
                            }
                        ],
                        "role": "model",
                    }
                }
            ]
        }
        calls = extract_function_calls(event)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "run_command")
        self.assertEqual(calls[0]["args"], {"command": "ls -la"})
        self.assertTrue(calls[0]["id"].startswith("toolu_"))

    def test_extract_function_call_preserving_explicit_id(self):
        event = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "functionCall": {
                                    "id": "call_custom_999",
                                    "name": "read_file",
                                    "args": {"path": "test.txt"},
                                }
                            }
                        ]
                    }
                }
            ]
        }
        calls = extract_function_calls(event)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["id"], "call_custom_999")
        self.assertEqual(calls[0]["name"], "read_file")
        self.assertEqual(calls[0]["args"], {"path": "test.txt"})

    def test_extract_function_call_with_json_string_args(self):
        event = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "functionCall": {
                                    "name": "parse_data",
                                    "args": '{"key": "value"}',
                                }
                            }
                        ]
                    }
                }
            ]
        }
        calls = extract_function_calls(event)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "parse_data")
        self.assertEqual(calls[0]["args"], {"key": "value"})

    def test_extract_multiple_function_calls(self):
        event = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"functionCall": {"name": "tool_a", "args": {}}},
                            {"functionCall": {"name": "tool_b", "args": {"x": 1}}},
                        ]
                    }
                }
            ]
        }
        calls = extract_function_calls(event)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["name"], "tool_a")
        self.assertEqual(calls[1]["name"], "tool_b")
        self.assertEqual(calls[1]["args"], {"x": 1})

    def test_extract_function_calls_with_response_wrapper(self):
        event = {
            "response": {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"functionCall": {"name": "wrapped_tool", "args": {}}}
                            ]
                        }
                    }
                ]
            }
        }
        calls = extract_function_calls(event)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "wrapped_tool")

    def test_extract_function_call_with_thought_signature(self):
        event = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "thoughtSignature": "sig_xyz_123",
                                "functionCall": {
                                    "name": "calc",
                                    "args": {"expr": "1+1"},
                                },
                            }
                        ]
                    }
                }
            ]
        }
        calls = extract_function_calls(event)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "calc")
        self.assertEqual(calls[0]["thought_signature"], "sig_xyz_123")

    def test_no_function_calls_returns_empty_list(self):
        self.assertEqual(extract_function_calls({}), [])
        self.assertEqual(extract_function_calls({"candidates": []}), [])
        self.assertEqual(
            extract_function_calls({"candidates": [{"content": {"parts": [{"text": "no tools"}]}}]}),
            [],
        )
        self.assertEqual(extract_function_calls(None), [])


class TestExtractFinishReasonAndUsage(unittest.TestCase):
    def test_extract_finish_reason_stop(self):
        event = {"candidates": [{"finishReason": "STOP"}]}
        self.assertEqual(extract_finish_reason(event), "stop")

    def test_extract_finish_reason_max_tokens(self):
        event = {"candidates": [{"finishReason": "MAX_TOKENS"}]}
        self.assertEqual(extract_finish_reason(event), "length")

    def test_extract_finish_reason_safety(self):
        event = {"candidates": [{"finishReason": "SAFETY"}]}
        self.assertEqual(extract_finish_reason(event), "content_filter")

    def test_extract_finish_reason_candidate_content_filter_types(self):
        for reason in ("RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII"):
            with self.subTest(reason=reason):
                event = {"candidates": [{"finishReason": reason}]}
                self.assertEqual(extract_finish_reason(event), "content_filter")

    def test_extract_finish_reason_prompt_feedback_blocks(self):
        for reason in ("SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII"):
            with self.subTest(block_reason=reason):
                event = {"promptFeedback": {"blockReason": reason}}
                self.assertEqual(extract_finish_reason(event), "content_filter")

    def test_extract_finish_reason_prompt_feedback_wrapped_in_response(self):
        event = {"response": {"promptFeedback": {"blockReason": "SAFETY"}}}
        self.assertEqual(extract_finish_reason(event), "content_filter")

    def test_extract_finish_reason_default_to_stop(self):
        event = {"candidates": [{"finishReason": "UNKNOWN_REASON"}]}
        self.assertEqual(extract_finish_reason(event), "stop")

    def test_extract_finish_reason_with_response_wrapper(self):
        event = {"response": {"candidates": [{"finishReason": "STOP"}]}}
        self.assertEqual(extract_finish_reason(event), "stop")

    def test_extract_finish_reason_missing_returns_none(self):
        self.assertIsNone(extract_finish_reason({}))
        self.assertIsNone(extract_finish_reason({"candidates": [{}]}))

    def test_extract_finish_reason_unspecified_returns_none(self):
        for val in ("FINISH_REASON_UNSPECIFIED", "0", "UNSPECIFIED", "", "   "):
            with self.subTest(val=val):
                event = {"candidates": [{"finishReason": val}]}
                self.assertIsNone(extract_finish_reason(event))

    def test_extract_finish_reason_block_reason_unspecified_ignored(self):
        for val in ("BLOCK_REASON_UNSPECIFIED", "0", "UNSPECIFIED"):
            with self.subTest(val=val):
                event = {
                    "promptFeedback": {"blockReason": val},
                    "candidates": [{"finishReason": "STOP"}],
                }
                self.assertEqual(extract_finish_reason(event), "stop")

    def test_extract_finish_reason_malicious(self):
        event = {"candidates": [{"finishReason": "MALICIOUS"}]}
        self.assertEqual(extract_finish_reason(event), "content_filter")
        feedback_event = {"promptFeedback": {"blockReason": "MALICIOUS"}}
        self.assertEqual(extract_finish_reason(feedback_event), "content_filter")

    def test_extract_finish_reason_numeric_enums(self):
        # 1 -> stop
        self.assertEqual(extract_finish_reason({"candidates": [{"finishReason": "1"}]}), "stop")
        self.assertEqual(extract_finish_reason({"candidates": [{"finishReason": 1}]}), "stop")

        # 2 -> length
        self.assertEqual(extract_finish_reason({"candidates": [{"finishReason": "2"}]}), "length")
        self.assertEqual(extract_finish_reason({"candidates": [{"finishReason": 2}]}), "length")

        # 3..9 -> content_filter
        for code in range(3, 10):
            with self.subTest(code=code):
                self.assertEqual(
                    extract_finish_reason({"candidates": [{"finishReason": str(code)}]}),
                    "content_filter",
                )
                self.assertEqual(
                    extract_finish_reason({"candidates": [{"finishReason": code}]}),
                    "content_filter",
                )


    def test_extract_usage_metadata(self):
        event = {
            "usageMetadata": {
                "promptTokenCount": 15,
                "candidatesTokenCount": 35,
                "totalTokenCount": 50,
            }
        }
        usage = extract_usage(event)
        self.assertEqual(
            usage,
            {
                "prompt_tokens": 15,
                "completion_tokens": 35,
                "total_tokens": 50,
            },
        )

    def test_extract_usage_with_response_wrapper(self):
        event = {
            "response": {
                "usageMetadata": {
                    "promptTokenCount": 10,
                    "candidatesTokenCount": 20,
                    "totalTokenCount": 30,
                }
            }
        }
        usage = extract_usage(event)
        self.assertEqual(
            usage,
            {
                "prompt_tokens": 10,
                "completion_tokens": 20,
                "total_tokens": 30,
            },
        )

    def test_extract_usage_missing_returns_none(self):
        self.assertIsNone(extract_usage({}))
        self.assertIsNone(extract_usage({"candidates": []}))

    def test_extract_usage_null_token_counts(self):
        event = {
            "usageMetadata": {
                "promptTokenCount": None,
                "candidatesTokenCount": None,
                "totalTokenCount": None,
            }
        }
        usage = extract_usage(event)
        self.assertEqual(
            usage,
            {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
        )


class TestBuildOpenAIResponses(unittest.TestCase):
    def test_build_openai_chunk_with_delta(self):
        chunk_str = build_openai_chunk(
            completion_id="chatcmpl-123",
            model="gemini-2.5-pro",
            delta_text="Hello",
        )
        self.assertTrue(chunk_str.startswith("data: "))
        self.assertTrue(chunk_str.endswith("\n\n"))
        chunk_json = json.loads(chunk_str[6:].strip())
        self.assertEqual(chunk_json["id"], "chatcmpl-123")
        self.assertEqual(chunk_json["object"], "chat.completion.chunk")
        self.assertEqual(chunk_json["model"], "gemini-2.5-pro")
        self.assertEqual(chunk_json["choices"][0]["delta"]["content"], "Hello")
        self.assertIsNone(chunk_json["choices"][0]["finish_reason"])

    def test_build_openai_chunk_with_finish_reason(self):
        chunk_str = build_openai_chunk(
            completion_id="chatcmpl-123",
            model="gemini-2.5-pro",
            finish_reason="stop",
        )
        chunk_json = json.loads(chunk_str[6:].strip())
        self.assertEqual(chunk_json["choices"][0]["finish_reason"], "stop")
        self.assertEqual(chunk_json["choices"][0]["delta"], {})

    def test_build_openai_chunk_with_role(self):
        chunk_str = build_openai_chunk(
            completion_id="chatcmpl-123",
            model="gemini-2.5-pro",
            delta_text="Hello",
            role="assistant",
        )
        chunk_json = json.loads(chunk_str[6:].strip())
        self.assertEqual(chunk_json["choices"][0]["delta"]["role"], "assistant")
        self.assertEqual(chunk_json["choices"][0]["delta"]["content"], "Hello")

    def test_build_openai_chunk_with_role_only(self):
        chunk_str = build_openai_chunk(
            completion_id="chatcmpl-123",
            model="gemini-2.5-pro",
            role="assistant",
        )
        chunk_json = json.loads(chunk_str[6:].strip())
        self.assertEqual(chunk_json["choices"][0]["delta"]["role"], "assistant")
        self.assertNotIn("content", chunk_json["choices"][0]["delta"])

    def test_build_openai_completion_non_streaming(self):
        usage = {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
        resp = build_openai_completion(
            completion_id="chatcmpl-999",
            model="gemini-2.5-pro",
            full_text="Complete answer.",
            usage=usage,
            finish_reason="length",
        )
        self.assertEqual(resp["id"], "chatcmpl-999")
        self.assertEqual(resp["object"], "chat.completion")
        self.assertEqual(resp["model"], "gemini-2.5-pro")
        self.assertEqual(resp["choices"][0]["message"]["role"], "assistant")
        self.assertEqual(resp["choices"][0]["message"]["content"], "Complete answer.")
        self.assertEqual(resp["choices"][0]["finish_reason"], "length")
        self.assertEqual(resp["usage"], usage)

    def test_build_openai_chunk_with_delta_tool_calls(self):
        tool_calls = [
            {
                "index": 0,
                "id": "call_abc123",
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "arguments": '{"location": "Tokyo"}',
                },
            }
        ]
        chunk_str = build_openai_chunk(
            completion_id="chatcmpl-123",
            model="gemini-2.5-pro",
            delta_tool_calls=tool_calls,
        )
        chunk_json = json.loads(chunk_str[6:].strip())
        self.assertEqual(chunk_json["choices"][0]["delta"]["tool_calls"], tool_calls)

    def test_build_openai_completion_with_tool_calls(self):
        tool_calls = [
            {
                "id": "call_abc123",
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "arguments": '{"location": "Tokyo"}',
                },
            }
        ]
        resp = build_openai_completion(
            completion_id="chatcmpl-999",
            model="gemini-2.5-pro",
            full_text="",
            tool_calls=tool_calls,
            finish_reason="tool_calls",
        )
        self.assertEqual(resp["choices"][0]["message"]["tool_calls"], tool_calls)
        self.assertIsNone(resp["choices"][0]["message"]["content"])
        self.assertEqual(resp["choices"][0]["finish_reason"], "tool_calls")

    def test_build_openai_model_list(self):
        upstream = [
            {"name": "models/gemini-2.5-pro"},
            {"id": "gemini-2.5-flash"},
            "models/gemini-1.5-flash",
            "gemini-ultra",
        ]
        result = build_openai_model_list(upstream)
        self.assertEqual(result["object"], "list")
        self.assertEqual(len(result["data"]), 4)
        self.assertEqual(result["data"][0]["id"], "gemini-2.5-pro")
        self.assertEqual(result["data"][0]["slug"], "gemini-2.5-pro")
        self.assertEqual(result["data"][0]["display_name"], "gemini-2.5-pro")
        self.assertEqual(result["data"][0]["object"], "model")
        self.assertEqual(result["data"][0]["owned_by"], "google")
        self.assertEqual(result["models"], result["data"])
        self.assertEqual(result["data"][1]["id"], "gemini-2.5-flash")
        self.assertEqual(result["data"][2]["id"], "gemini-1.5-flash")
        self.assertEqual(result["data"][3]["id"], "gemini-ultra")

    def test_build_openai_model_list_deduplicates_ids(self):
        upstream = [
            {"name": "models/gemini-2.5-pro"},
            {"id": "gemini-2.5-pro"},
            "gemini-2.5-pro",
        ]
        result = build_openai_model_list(upstream)
        self.assertEqual(len(result["data"]), 1)
        self.assertEqual(result["data"][0]["id"], "gemini-2.5-pro")

    def test_build_openai_error_response(self):
        status_code, err = build_openai_error_response(
            status_code=400,
            message="Invalid model specified",
            error_type="invalid_request_error",
        )
        self.assertEqual(status_code, 400)
        self.assertEqual(
            err,
            {
                "error": {
                    "message": "Invalid model specified",
                    "type": "invalid_request_error",
                    "code": 400,
                }
            },
        )


class TestCheckSSEError(unittest.TestCase):
    def test_check_sse_error_none_when_no_error(self):
        # Should not raise for normal events
        check_sse_error({})
        check_sse_error({"candidates": []})
        check_sse_error({"response": {"candidates": []}})

    def test_check_sse_error_rate_limit_429(self):
        event = {
            "error": {
                "code": 429,
                "message": "Resource exhausted: quota exceeded",
                "status": "RESOURCE_EXHAUSTED",
            }
        }
        with self.assertRaises(RateLimitError) as ctx:
            check_sse_error(event)
        self.assertIn("quota exceeded", str(ctx.exception))

    def test_check_sse_error_capacity_exhausted_503(self):
        event = {
            "error": {
                "code": 503,
                "message": "Service temporarily unavailable",
                "status": "UNAVAILABLE",
            }
        }
        with self.assertRaises(CapacityExhaustedError) as ctx:
            check_sse_error(event)
        self.assertIn("unavailable", str(ctx.exception).lower())

    def test_check_sse_error_auth_error_401(self):
        event = {
            "error": {
                "code": 401,
                "message": "Request had invalid authentication credentials",
                "status": "UNAUTHENTICATED",
            }
        }
        with self.assertRaises(AuthenticationError) as ctx:
            check_sse_error(event)
        self.assertIn("authentication", str(ctx.exception).lower())

    def test_check_sse_error_forbidden_403(self):
        event = {
            "error": {
                "code": 403,
                "message": "The caller does not have permission",
                "status": "PERMISSION_DENIED",
            }
        }
        with self.assertRaises(ForbiddenError) as ctx:
            check_sse_error(event)
        self.assertIn("forbidden", str(ctx.exception).lower())

    def test_check_sse_error_generic_bridge_error(self):
        event = {
            "error": {
                "code": 500,
                "message": "Internal server error occurred",
            }
        }
        with self.assertRaises(BridgeError) as ctx:
            check_sse_error(event)
        self.assertIn("Internal server error", str(ctx.exception))

    def test_check_sse_error_wrapped_in_response(self):
        event = {
            "response": {
                "error": {
                    "code": 429,
                    "message": "Quota limit reached",
                    "status": "RESOURCE_EXHAUSTED",
                }
            }
        }
        with self.assertRaises(RateLimitError):
            check_sse_error(event)


class TestBuildThinkingConfig(unittest.TestCase):
    def test_suffix_high_sets_thinking_level_high(self):
        config = build_thinking_config("gemini-3.1-pro-high", {})
        self.assertEqual(config, {"thinkingLevel": "HIGH"})

    def test_suffix_medium_sets_thinking_level_medium(self):
        config = build_thinking_config("gemini-3.1-pro-medium", {})
        self.assertEqual(config, {"thinkingLevel": "MEDIUM"})

    def test_suffix_low_sets_thinking_level_low(self):
        config = build_thinking_config("gemini-3.1-pro-low", {})
        self.assertEqual(config, {"thinkingLevel": "LOW"})

    def test_suffix_thinking_sets_thinking_budget(self):
        config = build_thinking_config("claude-opus-4-6-thinking", {})
        self.assertEqual(config, {"thinkingBudget": 2048})

    def test_standard_gemini_model_defaults_to_none(self):
        for model in ("gemini-2.5-pro", "gemini-2.5-flash", "gemini-1.5-pro"):
            with self.subTest(model=model):
                config = build_thinking_config(model, {})
                self.assertIsNone(config)

    def test_payload_override_thinking_level(self):
        payload = {"thinking": {"thinkingLevel": "LOW"}}
        config = build_thinking_config("gemini-3.1-pro-high", payload)
        self.assertEqual(config, {"thinkingLevel": "LOW"})

    def test_payload_override_budget_tokens(self):
        payload = {"thinking": {"budget_tokens": 4096}}
        config = build_thinking_config("gemini-2.5-pro", payload)
        self.assertEqual(config, {"thinkingBudget": 4096})

    def test_payload_override_thinking_type_disabled(self):
        payload = {"thinking": {"type": "disabled"}}
        config = build_thinking_config("gemini-3.1-pro-high", payload)
        self.assertIsNone(config)

    def test_thinking_disabled_claude_returns_low(self):
        payload = {"thinking": {"type": "disabled"}}
        config = build_thinking_config("claude-sonnet-5-5", payload)
        self.assertEqual(config, {"thinkingLevel": "LOW"})

    def test_thinking_disabled_gemini_returns_none(self):
        payload = {"thinking": {"type": "disabled"}}
        config = build_thinking_config("gemini-2.5-pro", payload)
        self.assertIsNone(config)

    def test_payload_override_thinking_type_enabled(self):
        payload = {"thinking": {"type": "enabled", "budget_tokens": 1024}}
        config = build_thinking_config("gemini-2.5-pro", payload)
        self.assertEqual(config, {"thinkingBudget": 1024})

    def test_payload_override_thinking_type_adaptive(self):
        # Tiered / high model maps to thinkingLevel HIGH without 'type' field
        payload = {"thinking": {"type": "adaptive"}}
        config = build_thinking_config("gemini-3.8-flash-tiered", payload)
        self.assertEqual(config, {"thinkingLevel": "HIGH"})
        self.assertNotIn("type", config)

        # Medium / low model suffixes
        config_med = build_thinking_config("gemini-3.8-flash-medium", payload)
        self.assertEqual(config_med, {"thinkingLevel": "MEDIUM"})
        self.assertNotIn("type", config_med)

        config_low = build_thinking_config("gemini-3.8-flash-low", payload)
        self.assertEqual(config_low, {"thinkingLevel": "LOW"})
        self.assertNotIn("type", config_low)

        # Standard non-tiered model defaults to thinkingBudget
        config_std = build_thinking_config("gemini-2.5-pro", payload)
        self.assertEqual(config_std, {"thinkingBudget": 2048})
        self.assertNotIn("type", config_std)

    def test_payload_override_thinking_unknown_fields_stripped(self):
        payload = {"thinking": {"type": "unknown_mode", "custom": "value"}}
        config = build_thinking_config("gemini-2.5-pro", payload)
        self.assertIsNone(config)

    def test_payload_override_thinking_config_direct_sanitized(self):
        payload = {"thinkingConfig": {"type": "adaptive", "thinkingLevel": "HIGH", "invalid": 123}}
        config = build_thinking_config("gemini-3.8-flash-tiered", payload)
        self.assertEqual(config, {"thinkingLevel": "HIGH"})
        self.assertNotIn("type", config)
        self.assertNotIn("invalid", config)

    def test_payload_override_thinking_config_direct(self):
        payload = {"thinkingConfig": {"thinkingBudget": 500}}
        config = build_thinking_config("gemini-2.5-pro", payload)
        self.assertEqual(config, {"thinkingBudget": 500})

    def test_payload_override_reasoning_effort(self):
        for effort, expected in (("low", "LOW"), ("medium", "MEDIUM"), ("high", "HIGH")):
            with self.subTest(effort=effort):
                payload = {"reasoning_effort": effort}
                config = build_thinking_config("gemini-2.5-pro", payload)
                self.assertEqual(config, {"thinkingLevel": expected})

    def test_payload_override_reasoning_effort_disabled_or_none(self):
        for effort in ("none", "disabled", "off"):
            with self.subTest(effort=effort):
                payload = {"reasoning_effort": effort}
                config = build_thinking_config("gemini-3.1-pro-high", payload)
                self.assertIsNone(config)

    def test_payload_override_output_config_effort(self):
        for effort, expected in (
            ("high", "HIGH"),
            ("xhigh", "HIGH"),
            ("max", "HIGH"),
            ("medium", "MEDIUM"),
            ("low", "LOW"),
        ):
            with self.subTest(effort=effort):
                payload = {"output_config": {"effort": effort}}
                config = build_thinking_config("claude-sonnet-5-5", payload)
                self.assertEqual(config, {"thinkingLevel": expected})

    def test_output_config_effort_xhigh(self):
        payload = {"output_config": {"effort": "xhigh"}}
        config = build_thinking_config("claude-sonnet-5-5", payload)
        self.assertEqual(config, {"thinkingLevel": "HIGH"})

    def test_output_config_effort_max(self):
        payload = {"output_config": {"effort": "max"}}
        config = build_thinking_config("claude-sonnet-5-5", payload)
        self.assertEqual(config, {"thinkingLevel": "HIGH"})

    def test_payload_override_output_config_camel_case(self):
        payload = {"outputConfig": {"effort": "medium"}}
        config = build_thinking_config("claude-sonnet-5-5", payload)
        self.assertEqual(config, {"thinkingLevel": "MEDIUM"})

    def test_payload_override_thinking_type_between_tools(self):
        # Without output_config effort, between_tools defaults to LOW
        payload = {"thinking": {"type": "between_tools"}}
        config = build_thinking_config("claude-sonnet-5-5", payload)
        self.assertEqual(config, {"thinkingLevel": "LOW"})

        # With output_config effort, effort determines thinkingLevel
        payload_med = {
            "thinking": {"type": "between_tools"},
            "output_config": {"effort": "medium"},
        }
        config_med = build_thinking_config("claude-sonnet-5-5", payload_med)
        self.assertEqual(config_med, {"thinkingLevel": "MEDIUM"})

        payload_high = {
            "thinking": {"type": "between_tools"},
            "output_config": {"effort": "high"},
        }
        config_high = build_thinking_config("claude-sonnet-5-5", payload_high)
        self.assertEqual(config_high, {"thinkingLevel": "HIGH"})

        payload_low = {
            "thinking": {"type": "between_tools"},
            "output_config": {"effort": "low"},
        }
        config_low = build_thinking_config("claude-sonnet-5-5", payload_low)
        self.assertEqual(config_low, {"thinkingLevel": "LOW"})

    def test_payload_override_thinking_type_adaptive_with_output_config(self):
        payload = {
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": "high"},
        }
        config = build_thinking_config("claude-sonnet-5-5", payload)
        self.assertEqual(config, {"thinkingLevel": "HIGH"})

    def test_payload_thinking_config_precedence_over_output_config(self):
        payload = {
            "thinkingConfig": {"thinkingLevel": "LOW"},
            "output_config": {"effort": "high"},
        }
        config = build_thinking_config("claude-sonnet-5-5", payload)
        self.assertEqual(config, {"thinkingLevel": "LOW"})

    def test_default_thinking_budget_clamped_with_max_tokens(self):
        # Default budget 2048 clamped to max(0, max_tokens - 128)
        config1 = build_thinking_config("claude-opus-4-6-thinking", {"max_tokens": 256})
        self.assertEqual(config1, {"thinkingBudget": 128})

        config2 = build_thinking_config("claude-opus-4-6-thinking", {"max_tokens": 100})
        self.assertIsNone(config2)

        config3 = build_thinking_config("gemini-2.5-pro", {"thinking": {"type": "enabled"}, "max_tokens": 300})
        self.assertEqual(config3, {"thinkingBudget": 172})

        config4 = build_thinking_config("gemini-2.5-pro", {"thinking": True, "maxOutputTokens": 500})
        self.assertEqual(config4, {"thinkingBudget": 372})

        config5 = build_thinking_config("claude-opus-4-6-thinking", {"max_tokens": 4096})
        self.assertEqual(config5, {"thinkingBudget": 2048})

    def test_openai_to_cloudcode_request_wires_adaptive_thinking(self):
        # Reasoning model sets thinkingLevel
        payload_high = {
            "model": "gemini-3.1-pro-high",
            "messages": [{"role": "user", "content": "hello"}],
        }
        _, _, _, gen_config_high, _ = openai_to_cloudcode_request(payload_high, "test-project")
        self.assertIsNotNone(gen_config_high)
        self.assertEqual(gen_config_high.get("thinkingConfig"), {"thinkingLevel": "HIGH"})

        # Standard model omits thinkingConfig
        payload_std = {
            "model": "gemini-2.5-pro",
            "messages": [{"role": "user", "content": "hello"}],
        }
        _, _, _, gen_config_std, _ = openai_to_cloudcode_request(payload_std, "test-project")
        self.assertIsNone(gen_config_std)

        # Payload override takes precedence
        payload_override = {
            "model": "gemini-3.1-pro-high",
            "messages": [{"role": "user", "content": "hello"}],
            "thinking": {"thinkingBudget": 1024},
        }
        _, _, _, gen_config_ovr, _ = openai_to_cloudcode_request(payload_override, "test-project")
        self.assertIsNotNone(gen_config_ovr)
        self.assertEqual(gen_config_ovr.get("thinkingConfig"), {"thinkingBudget": 1024})

    def test_openai_to_cloudcode_request_resolves_claude_5_5_models(self):
        # Sonnet 5.5 High
        p1 = {"model": "claude-sonnet-5-5-high", "messages": [{"role": "user", "content": "hi"}]}
        m1, _, _, g1, _ = openai_to_cloudcode_request(p1, "p")
        self.assertEqual(m1, "claude-sonnet-5-5")
        self.assertEqual(g1["thinkingConfig"], {"thinkingLevel": "HIGH"})

        # Opus 5.5 Low
        p2 = {"model": "claude-opus-5-5-low", "messages": [{"role": "user", "content": "hi"}]}
        m2, _, _, g2, _ = openai_to_cloudcode_request(p2, "p")
        self.assertEqual(m2, "claude-opus-5-5")
        self.assertEqual(g2["thinkingConfig"], {"thinkingLevel": "LOW"})

        # Sonnet 5.5 base without thinking
        p3 = {"model": "claude-sonnet-5-5", "messages": [{"role": "user", "content": "hi"}]}
        m3, _, _, g3, _ = openai_to_cloudcode_request(p3, "p")
        self.assertEqual(m3, "claude-sonnet-5-5")
        self.assertNotIn("thinkingConfig", g3 or {})


class TestResolveModelAndThinking(unittest.TestCase):
    def test_none_model_resolves_to_tiered_high(self):
        model, thinking = resolve_model_and_thinking(None, {})
        self.assertEqual(model, "gemini-3.8-flash-tiered")
        self.assertEqual(thinking, {"thinkingLevel": "HIGH"})

    def test_empty_model_resolves_to_tiered_high(self):
        model, thinking = resolve_model_and_thinking("", {})
        self.assertEqual(model, "gemini-3.8-flash-tiered")
        self.assertEqual(thinking, {"thinkingLevel": "HIGH"})

        model_ws, thinking_ws = resolve_model_and_thinking("   ", {})
        self.assertEqual(model_ws, "gemini-3.8-flash-tiered")
        self.assertEqual(thinking_ws, {"thinkingLevel": "HIGH"})

    def test_auto_model_resolves_to_tiered_high(self):
        model, thinking = resolve_model_and_thinking("auto", {})
        self.assertEqual(model, "gemini-3.8-flash-tiered")
        self.assertEqual(thinking, {"thinkingLevel": "HIGH"})

        model_upper, thinking_upper = resolve_model_and_thinking("AUTO", {})
        self.assertEqual(model_upper, "gemini-3.8-flash-tiered")
        self.assertEqual(thinking_upper, {"thinkingLevel": "HIGH"})

    def test_flash_high_model_resolves_to_tiered_high(self):
        model, thinking = resolve_model_and_thinking("gemini-3.8-flash-high", {})
        self.assertEqual(model, "gemini-3.8-flash-tiered")
        self.assertEqual(thinking, {"thinkingLevel": "HIGH"})

    def test_flash_model_resolves_to_tiered_high(self):
        model, thinking = resolve_model_and_thinking("gemini-3.8-flash", {})
        self.assertEqual(model, "gemini-3.8-flash-tiered")
        self.assertEqual(thinking, {"thinkingLevel": "HIGH"})

    def test_gemini_3_8_model_resolves_to_tiered_high(self):
        model, thinking = resolve_model_and_thinking("gemini-3.8", {})
        self.assertEqual(model, "gemini-3.8-flash-tiered")
        self.assertEqual(thinking, {"thinkingLevel": "HIGH"})

    def test_flash_medium_model_resolves_to_tiered_medium(self):
        model, thinking = resolve_model_and_thinking("gemini-3.8-flash-medium", {})
        self.assertEqual(model, "gemini-3.8-flash-tiered")
        self.assertEqual(thinking, {"thinkingLevel": "MEDIUM"})

    def test_flash_low_model_resolves_to_tiered_low(self):
        model, thinking = resolve_model_and_thinking("gemini-3.8-flash-low", {})
        self.assertEqual(model, "gemini-3.8-flash-tiered")
        self.assertEqual(thinking, {"thinkingLevel": "LOW"})

    def test_explicit_thinking_config_overrides(self):
        # Explicit thinkingConfig in payload overrides default HIGH
        model, thinking = resolve_model_and_thinking(
            "gemini-3.8-flash-high", {"thinkingConfig": {"thinkingLevel": "LOW"}}
        )
        self.assertEqual(model, "gemini-3.8-flash-tiered")
        self.assertEqual(thinking, {"thinkingLevel": "LOW"})

        # Disabled thinking override
        model2, thinking2 = resolve_model_and_thinking(
            "auto", {"thinking": {"type": "disabled"}}
        )
        self.assertEqual(model2, "gemini-3.8-flash-tiered")
        self.assertIsNone(thinking2)

        # Reasoning effort override
        model3, thinking3 = resolve_model_and_thinking(
            "gemini-3.8-flash", {"reasoning_effort": "low"}
        )
        self.assertEqual(model3, "gemini-3.8-flash-tiered")
        self.assertEqual(thinking3, {"thinkingLevel": "LOW"})

    def test_claude_5_5_sonnet_and_opus_tiers_aliasing(self):
        cases = [
            ("claude-sonnet-5-5-high", "claude-sonnet-5-5", {"thinkingLevel": "HIGH"}),
            ("claude-sonnet-5-5-medium", "claude-sonnet-5-5", {"thinkingLevel": "MEDIUM"}),
            ("claude-sonnet-5-5-low", "claude-sonnet-5-5", {"thinkingLevel": "LOW"}),
            ("claude-opus-5-5-high", "claude-opus-5-5", {"thinkingLevel": "HIGH"}),
            ("claude-opus-5-5-medium", "claude-opus-5-5", {"thinkingLevel": "MEDIUM"}),
            ("claude-opus-5-5-low", "claude-opus-5-5", {"thinkingLevel": "LOW"}),
            ("claude-sonnet-5-5", "claude-sonnet-5-5", None),
            ("claude-opus-5-5", "claude-opus-5-5", None),
            ("CLAUDE-SONNET-5-5-HIGH", "claude-sonnet-5-5", {"thinkingLevel": "HIGH"}),
            ("CLAUDE-OPUS-5-5", "claude-opus-5-5", None),
        ]
        for raw_model, exp_model, exp_thinking in cases:
            model, thinking = resolve_model_and_thinking(raw_model, {})
            self.assertEqual(model, exp_model, f"Failed model resolution for {raw_model}")
            self.assertEqual(thinking, exp_thinking, f"Failed thinking resolution for {raw_model}")

    def test_claude_5_5_explicit_thinking_overrides(self):
        model, thinking = resolve_model_and_thinking(
            "claude-sonnet-5-5-high", {"thinkingConfig": {"thinkingLevel": "LOW"}}
        )
        self.assertEqual(model, "claude-sonnet-5-5")
        self.assertEqual(thinking, {"thinkingLevel": "LOW"})

        model2, thinking2 = resolve_model_and_thinking(
            "claude-opus-5-5-high", {"reasoning_effort": "low"}
        )
        self.assertEqual(model2, "claude-opus-5-5")
        self.assertEqual(thinking2, {"thinkingLevel": "LOW"})

        model3, thinking3 = resolve_model_and_thinking(
            "claude-sonnet-5-5", {"thinking": {"type": "enabled", "budget_tokens": 1024}}
        )
        self.assertEqual(model3, "claude-sonnet-5-5")
        self.assertEqual(thinking3, {"thinkingBudget": 1024})

    def test_claude_5_5_haiku_tiers_aliasing(self):
        cases = [
            ("claude-haiku-5-5-high", "claude-haiku-5-5", {"thinkingLevel": "HIGH"}),
            ("claude-haiku-5-5-medium", "claude-haiku-5-5", {"thinkingLevel": "MEDIUM"}),
            ("claude-haiku-5-5-low", "claude-haiku-5-5", {"thinkingLevel": "LOW"}),
            ("claude-haiku-5-5", "claude-haiku-5-5", None),
            ("CLAUDE-HAIKU-5-5-HIGH", "claude-haiku-5-5", {"thinkingLevel": "HIGH"}),
            ("CLAUDE-HAIKU-5-5", "claude-haiku-5-5", None),
        ]
        for raw_model, exp_model, exp_thinking in cases:
            model, thinking = resolve_model_and_thinking(raw_model, {})
            self.assertEqual(model, exp_model, f"Failed model resolution for {raw_model}")
            self.assertEqual(thinking, exp_thinking, f"Failed thinking resolution for {raw_model}")

    def test_claude_5_5_haiku_output_config_and_thinking_overrides(self):
        model, thinking = resolve_model_and_thinking(
            "claude-haiku-5-5", {"output_config": {"effort": "high"}}
        )
        self.assertEqual(model, "claude-haiku-5-5")
        self.assertEqual(thinking, {"thinkingLevel": "HIGH"})

        model2, thinking2 = resolve_model_and_thinking(
            "claude-haiku-5-5-high", {"output_config": {"effort": "low"}}
        )
        self.assertEqual(model2, "claude-haiku-5-5")
        self.assertEqual(thinking2, {"thinkingLevel": "LOW"})

        model3, thinking3 = resolve_model_and_thinking(
            "claude-haiku-5-5", {"thinking": {"type": "between_tools"}}
        )
        self.assertEqual(model3, "claude-haiku-5-5")
        self.assertEqual(thinking3, {"thinkingLevel": "LOW"})

        model4, thinking4 = resolve_model_and_thinking(
            "claude-haiku-5-5",
            {"thinking": {"type": "between_tools"}, "output_config": {"effort": "medium"}},
        )
        self.assertEqual(model4, "claude-haiku-5-5")
        self.assertEqual(thinking4, {"thinkingLevel": "MEDIUM"})

    def test_unaliased_model_preserved(self):
        model, thinking = resolve_model_and_thinking("gemini-2.5-pro", {})
        self.assertEqual(model, "gemini-2.5-pro")
        self.assertIsNone(thinking)

        model2, thinking2 = resolve_model_and_thinking("gemini-2.5-pro-high", {})
        self.assertEqual(model2, "gemini-2.5-pro-high")
        self.assertEqual(thinking2, {"thinkingLevel": "HIGH"})


class TestSanitizeSchemaForGemini(unittest.TestCase):
    def test_strips_unsupported_json_schema_root_keywords(self):
        schema = {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "$id": "http://example.com/schema",
            "title": "BashTool",
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "command": {"type": "string", "description": "Command"},
            },
            "required": ["command"],
        }
        sanitized = sanitize_schema_for_gemini(schema)
        self.assertNotIn("$schema", sanitized)
        self.assertNotIn("$id", sanitized)
        self.assertNotIn("additionalProperties", sanitized)
        self.assertEqual(sanitized["type"], "object")
        self.assertEqual(sanitized["required"], ["command"])
        self.assertEqual(sanitized["properties"]["command"], {"type": "string", "description": "Command"})

    def test_strips_nested_property_names_and_const(self):
        schema = {
            "type": "object",
            "properties": {
                "env": {
                    "type": "object",
                    "propertyNames": {"pattern": "^[A-Z_]+$"},
                    "anyOf": [
                        {"const": "val", "type": "string"},
                        {"type": "string", "propertyNames": {"pattern": "^[a-z]+$"}},
                    ],
                }
            },
        }
        sanitized = sanitize_schema_for_gemini(schema)
        env_prop = sanitized["properties"]["env"]
        self.assertNotIn("propertyNames", env_prop)
        self.assertNotIn("const", env_prop["anyOf"][0])
        self.assertNotIn("propertyNames", env_prop["anyOf"][1])

    def test_collapses_type_union_with_null(self):
        schema = {
            "type": ["string", "null"],
            "description": "Optional string",
        }
        sanitized = sanitize_schema_for_gemini(schema)
        self.assertEqual(sanitized["type"], "string")
        self.assertTrue(sanitized["nullable"])

    def test_preserves_custom_property_names_under_properties_map(self):
        # A property named "const" or "not" inside the properties map must not be deleted
        schema = {
            "type": "object",
            "properties": {
                "const": {"type": "string"},
                "not": {"type": "boolean"},
            },
        }
        sanitized = sanitize_schema_for_gemini(schema)
        self.assertIn("const", sanitized["properties"])
        self.assertIn("not", sanitized["properties"])

    def test_array_without_items_gets_empty_items_schema(self):
        schema = {
            "type": "array",
            "description": "A list of tags",
        }
        sanitized = sanitize_schema_for_gemini(schema)
        self.assertEqual(sanitized["type"], "array")
        self.assertEqual(sanitized["items"], {})

    def test_array_prefix_items_converted_to_items(self):
        schema = {
            "type": "array",
            "prefixItems": [
                {"type": "string"},
                {"type": "number"},
            ],
        }
        sanitized = sanitize_schema_for_gemini(schema)
        self.assertEqual(sanitized["type"], "array")
        self.assertIn("anyOf", sanitized["items"])
        self.assertEqual(len(sanitized["items"]["anyOf"]), 2)

    def test_inlines_internal_ref_pointers(self):
        schema = {
            "$defs": {
                "User": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                }
            },
            "type": "object",
            "properties": {
                "author": {"$ref": "#/$defs/User"},
            },
        }
        sanitized = sanitize_schema_for_gemini(schema)
        author = sanitized["properties"]["author"]
        self.assertEqual(author["type"], "object")
        self.assertEqual(author["properties"]["name"]["type"], "string")
        self.assertNotIn("$ref", author)

    def test_collapses_untyped_anyof_to_first_concrete_subschema(self):
        schema = {
            "type": "object",
            "properties": {
                "provider": {
                    "anyOf": [
                        {"type": "string", "description": "Provider name"},
                        {"type": "array", "items": {"type": "string"}},
                        {"type": "null"},
                    ],
                },
            },
        }
        sanitized = sanitize_schema_for_gemini(schema)
        prop = sanitized["properties"]["provider"]
        self.assertEqual(prop.get("type"), "string")
        self.assertEqual(prop.get("description"), "Provider name")
        self.assertTrue(prop.get("nullable"))
        self.assertNotIn("anyOf", prop)


class TestOpenAIToolCallingAndAliasing(unittest.TestCase):
    def test_openai_to_cloudcode_request_resolves_auto_model(self):
        payload = {
            "model": "auto",
            "messages": [{"role": "user", "content": "Hello"}],
        }
        model, contents, system_inst, gen_config, tools = openai_to_cloudcode_request(
            payload, "test-project"
        )
        self.assertEqual(model, "gemini-3.8-flash-tiered")
        self.assertIsNotNone(gen_config)
        self.assertEqual(gen_config.get("thinkingConfig"), {"thinkingLevel": "HIGH"})
        self.assertIsNone(tools)

    def test_openai_to_cloudcode_request_resolves_none_or_missing_model(self):
        # Missing model
        payload1 = {"messages": [{"role": "user", "content": "Hello"}]}
        model1, _, _, gen_config1, _ = openai_to_cloudcode_request(payload1, "test-project")
        self.assertEqual(model1, "gemini-3.8-flash-tiered")
        self.assertEqual(gen_config1.get("thinkingConfig"), {"thinkingLevel": "HIGH"})

        # None model
        payload2 = {"model": None, "messages": [{"role": "user", "content": "Hello"}]}
        model2, _, _, gen_config2, _ = openai_to_cloudcode_request(payload2, "test-project")
        self.assertEqual(model2, "gemini-3.8-flash-tiered")
        self.assertEqual(gen_config2.get("thinkingConfig"), {"thinkingLevel": "HIGH"})

        # Empty string model
        payload3 = {"model": "   ", "messages": [{"role": "user", "content": "Hello"}]}
        model3, _, _, gen_config3, _ = openai_to_cloudcode_request(payload3, "test-project")
        self.assertEqual(model3, "gemini-3.8-flash-tiered")
        self.assertEqual(gen_config3.get("thinkingConfig"), {"thinkingLevel": "HIGH"})

    def test_openai_to_cloudcode_request_resolves_flash_high_model(self):
        payload = {
            "model": "gemini-3.8-flash-high",
            "messages": [{"role": "user", "content": "Hello"}],
        }
        model, _, _, gen_config, _ = openai_to_cloudcode_request(payload, "test-project")
        self.assertEqual(model, "gemini-3.8-flash-tiered")
        self.assertEqual(gen_config.get("thinkingConfig"), {"thinkingLevel": "HIGH"})

    def test_openai_to_cloudcode_request_invalid_model_type_raises_value_error(self):
        payload = {
            "model": 12345,
            "messages": [{"role": "user", "content": "Hello"}],
        }
        with self.assertRaises(ValueError) as ctx:
            openai_to_cloudcode_request(payload, "test-project")
        self.assertIn("model", str(ctx.exception).lower())

    def test_openai_to_cloudcode_request_extracts_and_converts_tools(self):
        payload = {
            "model": "gemini-2.5-pro",
            "messages": [{"role": "user", "content": "What is the weather?"}],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "description": "Get current temperature",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "location": {"type": "string"},
                            },
                            "required": ["location"],
                        },
                    },
                }
            ],
        }
        _, _, _, _, tools = openai_to_cloudcode_request(payload, "test-project")
        self.assertIsNotNone(tools)
        self.assertEqual(len(tools), 1)
        self.assertIn("functionDeclarations", tools[0])
        decls = tools[0]["functionDeclarations"]
        self.assertEqual(len(decls), 1)
        self.assertEqual(decls[0]["name"], "get_weather")
        self.assertEqual(decls[0]["description"], "Get current temperature")
        self.assertEqual(
            decls[0]["parameters"],
            {
                "type": "object",
                "properties": {"location": {"type": "string"}},
                "required": ["location"],
            },
        )

    def test_openai_to_cloudcode_request_extracts_flat_tools(self):
        payload = {
            "model": "gemini-2.5-pro",
            "messages": [{"role": "user", "content": "What is the weather?"}],
            "tools": [
                {
                    "type": "function",
                    "name": "lookup",
                    "description": "Lookup entity",
                    "parameters": {"type": "object", "properties": {}},
                }
            ],
        }
        _, _, _, _, tools = openai_to_cloudcode_request(payload, "test-project")
        self.assertIsNotNone(tools)
        decls = tools[0]["functionDeclarations"]
        self.assertEqual(decls[0]["name"], "lookup")
        self.assertEqual(decls[0]["description"], "Lookup entity")

    def test_openai_to_cloudcode_request_sanitizes_tool_schema(self):
        payload = {
            "model": "gemini-2.5-pro",
            "messages": [{"role": "user", "content": "Run tool"}],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "custom_fn",
                        "parameters": {
                            "$schema": "http://json-schema.org/draft-07/schema#",
                            "type": "object",
                            "properties": {
                                "tags": {
                                    "type": "array",
                                },
                            },
                        },
                    },
                }
            ],
        }
        _, _, _, _, tools = openai_to_cloudcode_request(payload, "test-project")
        self.assertIsNotNone(tools)
        params = tools[0]["functionDeclarations"][0]["parameters"]
        self.assertNotIn("$schema", params)
        self.assertEqual(params["properties"]["tags"]["items"], {})

    def test_openai_to_cloudcode_request_assistant_tool_calls_and_tool_response(self):
        payload = {
            "model": "gemini-2.5-pro",
            "messages": [
                {"role": "user", "content": "What is the weather?"},
                {
                    "role": "assistant",
                    "content": "Checking the weather now.",
                    "tool_calls": [
                        {
                            "id": "call_weather_1",
                            "type": "function",
                            "function": {
                                "name": "get_weather",
                                "arguments": '{"location": "Tokyo"}',
                            },
                        }
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": "call_weather_1",
                    "content": "Sunny, 25C",
                },
            ],
        }
        _, contents, _, _, _ = openai_to_cloudcode_request(payload, "test-project")
        self.assertEqual(len(contents), 3)
        self.assertEqual(contents[0]["role"], "user")
        self.assertEqual(contents[0]["parts"], [{"text": "What is the weather?"}])

        self.assertEqual(contents[1]["role"], "model")
        self.assertEqual(
            contents[1]["parts"],
            [
                {"text": "Checking the weather now."},
                {
                    "thoughtSignature": "context_engineering_is_the_way_to_go",
                    "functionCall": {
                        "name": "get_weather",
                        "args": {"location": "Tokyo"},
                    },
                },
            ],
        )

        self.assertEqual(contents[2]["role"], "user")
        self.assertEqual(
            contents[2]["parts"],
            [
                {
                    "functionResponse": {
                        "name": "get_weather",
                        "response": {"output": "Sunny, 25C"},
                    }
                }
            ],
        )

    def test_openai_to_cloudcode_request_function_role_response(self):
        payload = {
            "model": "gemini-2.5-pro",
            "messages": [
                {"role": "user", "content": "Hi"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_fn_99",
                            "type": "function",
                            "function": {"name": "my_calc", "arguments": {"x": 5}},
                        }
                    ],
                },
                {
                    "role": "function",
                    "name": "my_calc",
                    "content": "Result: 10",
                },
            ],
        }
        _, contents, _, _, _ = openai_to_cloudcode_request(payload, "test-project")
        self.assertEqual(contents[1]["role"], "model")
        self.assertEqual(
            contents[1]["parts"],
            [
                {
                    "thoughtSignature": "context_engineering_is_the_way_to_go",
                    "functionCall": {"name": "my_calc", "args": {"x": 5}},
                }
            ],
        )
        self.assertEqual(contents[2]["role"], "user")
        self.assertEqual(
            contents[2]["parts"],
            [
                {
                    "functionResponse": {
                        "name": "my_calc",
                        "response": {"output": "Result: 10"},
                    }
                }
            ],
        )


class TestThoughtSignatureManagement(unittest.TestCase):
    def test_default_sentinel_fallback(self):
        from bridge.transform import get_thought_signature, DUMMY_THOUGHT_SIGNATURE

        self.assertEqual(
            get_thought_signature("nonexistent_call_id"),
            DUMMY_THOUGHT_SIGNATURE,
        )
        self.assertEqual(
            get_thought_signature(None, "nonexistent_fn", {"a": 1}),
            DUMMY_THOUGHT_SIGNATURE,
        )

    def test_cache_and_retrieve_by_call_id(self):
        from bridge.transform import cache_thought_signature, get_thought_signature

        call_id = f"test_call_{uuid.uuid4().hex}"
        sig = "sig_token_12345"
        cache_thought_signature(call_id=call_id, signature=sig)
        self.assertEqual(get_thought_signature(call_id=call_id), sig)

    def test_cache_and_retrieve_by_name_and_args(self):
        from bridge.transform import cache_thought_signature, get_thought_signature

        sig = "sig_calc_98765"
        fn_name = "calculate_tax"
        fn_args = {"amount": 100, "rate": 0.21}
        cache_thought_signature(signature=sig, name=fn_name, args=fn_args)
        # Check retrieval with same args
        self.assertEqual(
            get_thought_signature(call_id=None, name=fn_name, args=fn_args),
            sig,
        )
        # Check retrieval when args is json string
        self.assertEqual(
            get_thought_signature(call_id=None, name=fn_name, args='{"amount": 100, "rate": 0.21}'),
            sig,
        )

    def test_openai_request_preserves_explicit_thought_signature(self):
        sig = "custom_user_sig_555"
        payload = {
            "model": "gemini-2.5-pro",
            "messages": [
                {"role": "user", "content": "Run tool"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_custom_sig",
                            "type": "function",
                            "function": {"name": "run", "arguments": "{}"},
                            "thought_signature": sig,
                        }
                    ],
                },
            ],
        }
        _, contents, _, _, _ = openai_to_cloudcode_request(payload, "test-project")
        self.assertEqual(
            contents[1]["parts"][0],
            {
                "thoughtSignature": sig,
                "functionCall": {"name": "run", "args": {}},
            },
        )


if __name__ == "__main__":
    unittest.main()



