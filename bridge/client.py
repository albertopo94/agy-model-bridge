"""Upstream HTTP client for Google Cloud Code Assist APIs."""

from collections.abc import Iterator
import http.client
import json
import socket
from typing import Any
import urllib.error
import urllib.request


from bridge.errors import (
    AuthenticationError,
    BridgeError,
    CapacityExhaustedError,
    ForbiddenError,
    InvalidRequestError,
    ModelNotFoundError,
    RateLimitError,
    UpstreamError,
    UpstreamTimeoutError,
)

__all__ = [
    "AuthenticationError",
    "BridgeError",
    "CapacityExhaustedError",
    "CloudCodeClient",
    "ForbiddenError",
    "InvalidRequestError",
    "ModelNotFoundError",
    "RateLimitError",
    "UpstreamError",
    "UpstreamTimeoutError",
]


class CloudCodeClient:
    """Client for Google Cloud Code Assist upstream endpoints."""

    def __init__(
        self,
        token_provider: Any,
        base_url: str = "https://daily-cloudcode-pa.googleapis.com",
        timeout: float = 60.0,
    ) -> None:
        self.token_provider = token_provider
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _build_headers(self, token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "antigravity/1.0",
        }

    def _map_http_error(self, err: urllib.error.HTTPError) -> Exception:
        msg = ""
        try:
            try:
                raw_body_bytes = err.read()
            finally:
                err.close()

            raw_body = raw_body_bytes.decode("utf-8")
            parsed = json.loads(raw_body)
            if isinstance(parsed, dict):
                err_obj = parsed.get("error")
                if isinstance(err_obj, str):
                    msg = err_obj
                elif isinstance(err_obj, dict):
                    msg = err_obj.get("message") or raw_body
                else:
                    msg = raw_body
            else:
                msg = raw_body
        except Exception:
            msg = getattr(err, "reason", None) or str(err)


        if err.code == 400:
            return InvalidRequestError(f"Upstream 400 Bad Request: {msg}")
        if err.code == 401:
            return AuthenticationError(
                f"Upstream authentication failure (401): {msg}"
            )
        if err.code == 403:
            return ForbiddenError(
                f"Upstream forbidden (403): {msg}"
            )
        if err.code == 404:
            return ModelNotFoundError(f"Upstream 404 Not Found: {msg}")
        if err.code == 429:
            return RateLimitError(f"Upstream 429 Rate Limit: {msg}")
        if err.code == 503:
            return CapacityExhaustedError(f"Upstream 503 Capacity Exhausted: {msg}")
        return BridgeError(f"Upstream HTTP error ({err.code}): {msg}")

    def _request(
        self,
        path: str,
        payload: dict[str, Any],
        stream: bool = False,
        retry_on_401: bool = True,
    ) -> Any:
        url = f"{self.base_url}/{path.lstrip('/')}"
        data = json.dumps(payload).encode("utf-8")
        token = self.token_provider.get_token()
        headers = self._build_headers(token)

        req = urllib.request.Request(url, data=data, headers=headers, method="POST")

        try:
            resp = urllib.request.urlopen(req, timeout=self.timeout)
            if stream:
                return resp
            try:
                return resp.read()
            finally:
                resp.close()
        except urllib.error.HTTPError as err:
            if err.code == 401 and retry_on_401:
                err.close()
                self.token_provider.invalidate()
                refreshed_token = self.token_provider.get_token(force_refresh=True)
                retry_headers = self._build_headers(refreshed_token)
                retry_req = urllib.request.Request(
                    url, data=data, headers=retry_headers, method="POST"
                )
                try:
                    retry_resp = urllib.request.urlopen(retry_req, timeout=self.timeout)
                    if stream:
                        return retry_resp
                    try:
                        return retry_resp.read()
                    finally:
                        retry_resp.close()
                except urllib.error.HTTPError as retry_err:
                    raise self._map_http_error(retry_err) from retry_err
                except (socket.timeout, TimeoutError) as e:
                    raise UpstreamTimeoutError(f"Upstream timeout: {e}") from e
                except urllib.error.URLError as e:
                    if isinstance(e.reason, (socket.timeout, TimeoutError)):
                        raise UpstreamTimeoutError(f"Upstream timeout: {e.reason}") from e
                    raise BridgeError(f"Upstream connection error: {e}") from e
                except (http.client.HTTPException, OSError) as e:
                    raise BridgeError(f"Upstream connection error: {e}") from e

            raise self._map_http_error(err) from err
        except (socket.timeout, TimeoutError) as e:
            raise UpstreamTimeoutError(f"Upstream request timed out: {e}") from e
        except urllib.error.URLError as e:
            if isinstance(e.reason, (socket.timeout, TimeoutError)):
                raise UpstreamTimeoutError(f"Upstream request timed out: {e.reason}") from e
            raise BridgeError(f"Upstream connection error: {e}") from e
        except (http.client.HTTPException, OSError) as e:
            raise BridgeError(f"Upstream connection error: {e}") from e

    def load_code_assist(self) -> dict[str, Any]:
        """Discovers active project identifier and user tier."""
        payload = {
            "metadata": {
                "ideType": "ANTIGRAVITY",
                "platform": "PLATFORM_UNSPECIFIED",
                "pluginType": "GEMINI",
            }
        }
        raw_bytes = self._request("/v1internal:loadCodeAssist", payload)
        data = json.loads(raw_bytes.decode("utf-8"))

        raw_proj = data.get("cloudaicompanionProject") or data.get("project") or ""
        if isinstance(raw_proj, str) and raw_proj.startswith("projects/"):
            raw_proj = raw_proj[len("projects/") :]
        data["project"] = raw_proj

        return data

    def fetch_available_models(self, project: str) -> list[dict[str, Any]]:
        """Retrieves available model descriptors for the active project."""
        payload = {"project": project}
        raw_bytes = self._request("/v1internal:fetchAvailableModels", payload)
        data = json.loads(raw_bytes.decode("utf-8"))
        models = data.get("models")
        if isinstance(models, list):
            return models
        if isinstance(models, dict):
            return [{"id": k, **(v if isinstance(v, dict) else {})} for k, v in models.items()]
        return []

    def stream_generate_content(
        self,
        project: str,
        model: str,
        contents: list[dict[str, Any]],
        system_instruction: dict[str, Any] | None = None,
        generation_config: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_config: dict[str, Any] | None = None,
    ) -> Iterator[str]:
        """Streams Server-Sent Events from streamGenerateContent endpoint."""
        req_body: dict[str, Any] = {"contents": contents}
        if system_instruction is not None:
            req_body["systemInstruction"] = system_instruction
        if generation_config is not None:
            req_body["generationConfig"] = generation_config
        if tools is not None:
            req_body["tools"] = tools
        if tool_config is not None:
            req_body["toolConfig"] = tool_config

        payload: dict[str, Any] = {
            "project": project,
            "model": model,
            "request": req_body,
        }

        resp = self._request(
            "/v1internal:streamGenerateContent?alt=sse", payload, stream=True
        )
        try:
            for line in resp:
                yield line.decode("utf-8", errors="replace") if isinstance(line, bytes) else str(line)
        except (socket.timeout, TimeoutError) as e:
            raise UpstreamTimeoutError(f"Upstream stream timed out: {e}") from e
        except (http.client.HTTPException, OSError, urllib.error.URLError) as e:
            raise BridgeError(f"Upstream stream error: {e}") from e
        finally:
            if hasattr(resp, "close"):
                resp.close()
