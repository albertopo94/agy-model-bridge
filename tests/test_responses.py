"""Unit tests for the OpenAI Responses API shim."""

import json
import unittest
from bridge.responses import (
    responses_to_cloudcode_request,
    build_responses_completion,
    build_responses_sse_events,
    build_responses_error_response,
)


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
        model, contents, system_inst, gen_config = responses_to_cloudcode_request(
            payload, project="test-project"
        )
        self.assertEqual(model, "gemini-2.5-pro")
        self.assertEqual(system_inst, {"parts": [{"text": "Be concise."}]})
        self.assertEqual(contents, [{"role": "user", "parts": [{"text": "Hello world"}]}])
        self.assertIsNotNone(gen_config)
        self.assertEqual(gen_config["temperature"], 0.2)
        self.assertNotIn("thinkingConfig", gen_config)

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
        _, contents, _, _ = responses_to_cloudcode_request(payload, "test-project")
        self.assertEqual(len(contents), 3)
        self.assertEqual(contents[0]["role"], "user")
        self.assertEqual(contents[0]["parts"], [{"text": "What is Python?"}])
        self.assertEqual(contents[1]["role"], "model")
        self.assertEqual(contents[1]["parts"], [{"text": "A programming language."}])
        self.assertEqual(contents[2]["role"], "user")
        self.assertEqual(contents[2]["parts"], [{"text": "Tell me more."}])

    def test_input_as_string_normalized(self):
        payload = {
            "model": "gemini-2.5-pro",
            "input": "Single prompt string",
        }
        _, contents, _, _ = responses_to_cloudcode_request(payload, "test-project")
        self.assertEqual(len(contents), 1)
        self.assertEqual(contents[0]["role"], "user")
        self.assertEqual(contents[0]["parts"], [{"text": "Single prompt string"}])

    def test_input_with_system_and_developer_roles_extracted_to_system_instruction(self):
        payload = {
            "model": "gemini-2.5-pro",
            "input": [
                {"role": "system", "content": "System prompt."},
                {"role": "developer", "content": "Developer prompt."},
                {"role": "user", "content": "User question."},
            ],
        }
        _, contents, system_inst, _ = responses_to_cloudcode_request(payload, "test-project")
        self.assertEqual(
            system_inst,
            {"parts": [{"text": "System prompt.\nDeveloper prompt."}]},
        )
        self.assertEqual(len(contents), 1)
        self.assertEqual(contents[0]["role"], "user")
        self.assertEqual(contents[0]["parts"], [{"text": "User question."}])

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
        _, contents, _, _ = responses_to_cloudcode_request(payload, "test-project")
        self.assertEqual(len(contents), 1)
        self.assertEqual(contents[0]["role"], "user")
        self.assertEqual(contents[0]["parts"], [{"text": "[Function Output]: 42"}])

    def test_thinking_config_integration(self):
        payload_high = {
            "model": "gemini-3.1-pro-high",
            "input": ["Solve this riddle"],
        }
        _, _, _, gen_config_high = responses_to_cloudcode_request(payload_high, "test-project")
        self.assertEqual(gen_config_high["thinkingConfig"], {"thinkingLevel": "HIGH"})

        payload_override = {
            "model": "gemini-3.1-pro-high",
            "input": ["Solve this riddle"],
            "reasoning_effort": "low",
        }
        _, _, _, gen_config_ovr = responses_to_cloudcode_request(payload_override, "test-project")
        self.assertEqual(gen_config_ovr["thinkingConfig"], {"thinkingLevel": "LOW"})

    def test_input_as_dict_normalized(self):
        payload = {
            "model": "gemini-2.5-pro",
            "input": {"role": "user", "content": "Single dict input"},
        }
        _, contents, _, _ = responses_to_cloudcode_request(payload, "test-project")
        self.assertEqual(len(contents), 1)
        self.assertEqual(contents[0]["role"], "user")
        self.assertEqual(contents[0]["parts"], [{"text": "Single dict input"}])

    def test_input_function_call_with_dict_arguments_serialized(self):
        payload = {
            "model": "gemini-2.5-pro",
            "input": [
                {
                    "type": "function_call",
                    "name": "search",
                    "arguments": {"query": "weather", "days": 3},
                }
            ],
        }
        _, contents, _, _ = responses_to_cloudcode_request(payload, "test-project")
        self.assertEqual(len(contents), 3)  # leading hello user turn + assistant turn + trailing continue user turn
        self.assertEqual(contents[0]["role"], "user")
        self.assertEqual(contents[1]["role"], "model")
        self.assertIn('"query": "weather"', contents[1]["parts"][0]["text"])
        self.assertEqual(contents[2]["role"], "user")

    def test_stop_sequences_preserve_newlines_and_filter_whitespace(self):
        payload = {
            "model": "gemini-2.5-pro",
            "input": ["Hi"],
            "stop": ["", "  ", "\n", "STOP"],
        }
        _, _, _, gen_config = responses_to_cloudcode_request(payload, "test-project")
        self.assertEqual(gen_config["stopSequences"], ["\n", "STOP"])

    def test_omitted_or_aliased_model_resolves_to_flash_tiered(self):
        # Omitted model defaults to flash-tiered with HIGH thinking
        model, _, _, gen_config = responses_to_cloudcode_request(
            {"input": ["Hi"]}, "p"
        )
        self.assertEqual(model, "gemini-3.8-flash-tiered")
        self.assertEqual(gen_config.get("thinkingConfig"), {"thinkingLevel": "HIGH"})

        # "auto" model
        model_auto, _, _, gen_config_auto = responses_to_cloudcode_request(
            {"model": "auto", "input": ["Hi"]}, "p"
        )
        self.assertEqual(model_auto, "gemini-3.8-flash-tiered")
        self.assertEqual(gen_config_auto.get("thinkingConfig"), {"thinkingLevel": "HIGH"})

        # "gemini-3.8-flash-high"
        model_fh, _, _, gen_config_fh = responses_to_cloudcode_request(
            {"model": "gemini-3.8-flash-high", "input": ["Hi"]}, "p"
        )
        self.assertEqual(model_fh, "gemini-3.8-flash-tiered")
        self.assertEqual(gen_config_fh.get("thinkingConfig"), {"thinkingLevel": "HIGH"})

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


if __name__ == "__main__":
    unittest.main()
