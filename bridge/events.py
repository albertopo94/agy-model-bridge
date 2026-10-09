from collections.abc import Iterator
from dataclasses import dataclass, field
import json
from typing import Any
import uuid

from bridge.errors import (
    AuthenticationError,
    BridgeError,
    CapacityExhaustedError,
    ForbiddenError,
    InvalidRequestError,
    ModelNotFoundError,
    RateLimitError,
)


@dataclass(slots=True)
class ChatRequest:
    """Intermediate representation for chat requests across all protocols."""

    model: str
    contents: list[dict[str, Any]]
    system_instruction: dict[str, Any] | None = None
    generation_config: dict[str, Any] | None = None
    tools: list[dict[str, Any]] | None = None
    tool_config: dict[str, Any] | None = None

    @property
    def extra_kwargs(self) -> dict[str, Any]:
        """Collates generation_config, tools, and tool_config into keyword arguments."""
        kwargs: dict[str, Any] = {}
        if self.generation_config is not None:
            kwargs["generation_config"] = self.generation_config
        if self.tools is not None:
            kwargs["tools"] = self.tools
        if self.tool_config is not None:
            kwargs["tool_config"] = self.tool_config
        return kwargs

    def to_legacy_tuple(
        self,
    ) -> tuple[
        str,
        list[dict[str, Any]],
        dict[str, Any] | None,
        dict[str, Any] | None,
        list[dict[str, Any]] | None,
    ]:
        """Returns the 5-element tuple (model, contents, system_instruction, generation_config, tools)."""
        return (
            self.model,
            self.contents,
            self.system_instruction,
            self.generation_config,
            self.tools,
        )

    def to_anthropic_tuple(
        self,
    ) -> tuple[
        str,
        list[dict[str, Any]],
        dict[str, Any] | None,
        dict[str, Any] | None,
        list[dict[str, Any]] | None,
        dict[str, Any] | None,
    ]:
        """Returns the 6-element tuple (model, contents, system_instruction, generation_config, tools, tool_config)."""
        return (
            self.model,
            self.contents,
            self.system_instruction,
            self.generation_config,
            self.tools,
            self.tool_config,
        )

    def _to_tuple(self) -> tuple[Any, ...]:
        return (
            self.model,
            self.contents,
            self.system_instruction,
            self.generation_config,
            self.tools,
        )

    def __iter__(self) -> Iterator[Any]:
        return iter(self._to_tuple())

    def __getitem__(self, index: int | slice) -> Any:
        return self._to_tuple()[index]

    def __len__(self) -> int:
        return len(self._to_tuple())


@dataclass(slots=True)
class OpenAIChatRequest(ChatRequest):
    """Chat request originating from OpenAI Chat Completions API."""

    def _to_tuple(self) -> tuple[Any, ...]:
        return (
            self.model,
            self.contents,
            self.system_instruction,
            self.generation_config,
            self.tools,
        )


@dataclass(slots=True)
class ResponsesChatRequest(ChatRequest):
    """Chat request originating from OpenAI Responses API."""

    def _to_tuple(self) -> tuple[Any, ...]:
        return (
            self.model,
            self.contents,
            self.system_instruction,
            self.generation_config,
            self.tools,
        )


@dataclass(slots=True)
class AnthropicChatRequest(ChatRequest):
    """Chat request originating from Anthropic Messages API."""

    def _to_tuple(self) -> tuple[Any, ...]:
        return (
            self.model,
            self.contents,
            self.system_instruction,
            self.generation_config,
            self.tools,
            self.tool_config,
        )


def build_system_instruction(system_texts: list[str]) -> dict[str, Any] | None:
    """Combines non-empty system texts into a Cloud Code systemInstruction dictionary."""
    if not system_texts:
        return None
    cleaned = [t.strip() for t in system_texts if t and t.strip()]
    if not cleaned:
        return None
    combined = "\n".join(cleaned)
    return {"parts": [{"text": combined}]}


def normalize_turn_boundaries(contents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Enforces alternating conversation boundaries: prepends 'Hello' if starting with model, appends 'Continue' if ending with model."""
    if not contents:
        return contents
    if contents[0].get("role") == "model":
        contents.insert(0, {"role": "user", "parts": [{"text": "Hello"}]})
    if contents[-1].get("role") == "model":
        contents.append({"role": "user", "parts": [{"text": "Continue"}]})
    return contents


def append_or_merge_turn(
    contents: list[dict[str, Any]], role: str, parts: list[dict[str, Any]]
) -> None:
    """Appends a turn to contents or merges parts if previous turn had the same role."""
    if not parts:
        return
    if contents and contents[-1].get("role") == role:
        contents[-1]["parts"].extend(parts)
    else:
        contents.append({"role": role, "parts": list(parts)})


def build_tool_declarations(
    declarations: list[dict[str, Any]],
) -> list[dict[str, Any]] | None:
    """Wraps function declarations into Cloud Code tools structure."""
    if not declarations:
        return None
    return [{"functionDeclarations": declarations}]


@dataclass(slots=True)
class ToolCallDelta:
    id: str
    name: str
    args: dict[str, Any] = field(default_factory=dict)
    thought_signature: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "args": self.args,
        }
        if self.thought_signature:
            data["thought_signature"] = self.thought_signature
        return data


@dataclass(slots=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    thought_tokens: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass(slots=True)
class StreamEvent:
    delta_text: str | None = None
    delta_thought: str | None = None
    thought_signature: str | None = None
    tool_calls: list[ToolCallDelta] = field(default_factory=list)
    finish_reason: str | None = None
    usage: Usage | None = None
    raw: dict[str, Any] | None = None

    @property
    def has_content(self) -> bool:
        return bool(
            self.delta_text
            or self.delta_thought
            or self.thought_signature
            or self.tool_calls
            or self.finish_reason
            or self.usage
        )


def check_sse_error(event_dict: dict[str, Any]) -> None:
    """Checks if SSE event contains an error payload and raises appropriate BridgeError."""
    resp = event_dict.get("response")
    resp_obj: dict[str, Any] = resp if isinstance(resp, dict) else event_dict
    error_obj = resp_obj.get("error")
    if not error_obj:
        return

    code = None
    message = ""
    status = ""
    if isinstance(error_obj, dict):
        code = error_obj.get("code")
        message = error_obj.get("message") or ""
        status = error_obj.get("status") or ""
    else:
        message = str(error_obj)

    err_msg = message or status or "Unknown upstream error"
    if status and status not in err_msg:
        err_msg = f"{err_msg} ({status})"

    if code == 429 or status == "RESOURCE_EXHAUSTED":
        raise RateLimitError(f"Upstream rate limit: {err_msg}")
    if code == 503 or status == "UNAVAILABLE":
        raise CapacityExhaustedError(f"Upstream capacity exhausted: {err_msg}")
    if code == 403 or status == "PERMISSION_DENIED":
        raise ForbiddenError(f"Upstream forbidden: {err_msg}")
    if code == 401 or status == "UNAUTHENTICATED":
        raise AuthenticationError(f"Upstream authentication error: {err_msg}")
    if code == 404 or status == "NOT_FOUND":
        raise ModelNotFoundError(f"Upstream model not found: {err_msg}")
    if code == 400 or status == "INVALID_ARGUMENT":
        raise InvalidRequestError(f"Upstream invalid request: {err_msg}")

    raise BridgeError(f"Upstream error ({code or 'unknown'}): {err_msg}")


def parse_stream_event(
    event_dict: dict[str, Any] | None,
    check_error: bool = True,
) -> StreamEvent:
    """Parses a Cloud Code SSE event dictionary in a single pass into a StreamEvent."""
    if not isinstance(event_dict, dict):
        return StreamEvent(raw=event_dict)

    if check_error:
        check_sse_error(event_dict)

    resp = event_dict.get("response")
    resp_obj: dict[str, Any] = resp if isinstance(resp, dict) else event_dict

    finish_reason: str | None = None

    # Check promptFeedback
    prompt_feedback = resp_obj.get("promptFeedback") or event_dict.get("promptFeedback")
    if isinstance(prompt_feedback, dict):
        block_reason = prompt_feedback.get("blockReason")
        if block_reason:
            block_reason_str = str(block_reason).strip().upper()
            if block_reason_str not in ("BLOCK_REASON_UNSPECIFIED", "0", "UNSPECIFIED", ""):
                finish_reason = "content_filter"

    # Inspect usageMetadata
    usage: Usage | None = None
    metadata = resp_obj.get("usageMetadata")
    if isinstance(metadata, dict):
        prompt_tokens = int(metadata.get("promptTokenCount") or 0)
        candidates_tokens = int(metadata.get("candidatesTokenCount") or 0)
        total_tokens = int(metadata.get("totalTokenCount") or (prompt_tokens + candidates_tokens))
        thought_tokens = int(metadata.get("thoughtsTokenCount") or 0)
        usage = Usage(
            prompt_tokens=prompt_tokens,
            completion_tokens=candidates_tokens,
            total_tokens=total_tokens,
            thought_tokens=thought_tokens,
        )

    clean_texts: list[str] = []
    thought_texts: list[str] = []
    tool_calls: list[ToolCallDelta] = []
    captured_thought_sig: str | None = None

    candidates = resp_obj.get("candidates")
    if isinstance(candidates, list) and len(candidates) > 0:
        candidate = candidates[0]
        if isinstance(candidate, dict):
            reason = candidate.get("finishReason")
            if reason and finish_reason is None:
                reason_str = str(reason).strip().upper()
                if reason_str and reason_str not in ("FINISH_REASON_UNSPECIFIED", "0", "UNSPECIFIED"):
                    if reason_str in ("STOP", "1"):
                        finish_reason = "stop"
                    elif reason_str in ("MAX_TOKENS", "LENGTH", "2"):
                        finish_reason = "length"
                    elif reason_str in (
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
                        finish_reason = "content_filter"
                    else:
                        finish_reason = "stop"

            content = candidate.get("content")
            if isinstance(content, dict):
                parts = content.get("parts")
            else:
                parts = candidate.get("parts")

            if isinstance(parts, list):
                for part in parts:
                    if not isinstance(part, dict):
                        continue

                    part_sig = part.get("thoughtSignature") or part.get("thought_signature")
                    if part_sig and captured_thought_sig is None:
                        captured_thought_sig = str(part_sig)

                    if part.get("thought") is True:
                        t = part.get("text")
                        if t:
                            thought_texts.append(t)
                    elif part.get("functionCall"):
                        fc = part.get("functionCall")
                        if isinstance(fc, dict):
                            fn_name = fc.get("name")
                            if fn_name:
                                call_id = fc.get("id") or part.get("id") or f"toolu_{uuid.uuid4().hex[:16]}"
                                raw_args = fc.get("args")
                                if raw_args is None:
                                    args_dict = {}
                                elif isinstance(raw_args, str):
                                    try:
                                        loaded = json.loads(raw_args)
                                        args_dict = loaded if isinstance(loaded, dict) else {}
                                    except Exception:
                                        args_dict = {}
                                elif isinstance(raw_args, dict):
                                    args_dict = raw_args
                                else:
                                    args_dict = {}

                                tc_sig = (
                                    part_sig
                                    or fc.get("thoughtSignature")
                                    or fc.get("thought_signature")
                                )
                                if tc_sig and captured_thought_sig is None:
                                    captured_thought_sig = str(tc_sig)

                                tool_calls.append(
                                    ToolCallDelta(
                                        id=str(call_id),
                                        name=str(fn_name),
                                        args=args_dict,
                                        thought_signature=str(tc_sig) if tc_sig else None,
                                    )
                                )
                    else:
                        t = part.get("text")
                        if t:
                            clean_texts.append(t)

    delta_text = "".join(clean_texts) if clean_texts else None
    delta_thought = "".join(thought_texts) if thought_texts else None

    return StreamEvent(
        delta_text=delta_text,
        delta_thought=delta_thought,
        thought_signature=captured_thought_sig,
        tool_calls=tool_calls,
        finish_reason=finish_reason,
        usage=usage,
        raw=event_dict,
    )
