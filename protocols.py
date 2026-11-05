"""Payload and response adapters for four AI API families."""

import base64
import json
from dataclasses import dataclass
from urllib.parse import quote, urlsplit


DEFAULTS = {
    "chat": ("https://api.openai.com/v1", "/chat/completions", "gpt-4.1-mini"),
    "responses": ("https://api.openai.com/v1", "/responses", "gpt-4.1-mini"),
    "claude": ("https://api.anthropic.com", "/v1/messages", "claude-sonnet-4-5"),
    "gemini": (
        "https://generativelanguage.googleapis.com",
        "/v1beta/models/{model}:generateContent",
        "gemini-2.5-flash",
    ),
}


@dataclass(frozen=True)
class RequestSpec:
    url: str
    headers: dict[str, str]
    body: dict


class ProtocolError(Exception):
    pass


def _message_for_provider(message: dict, mode: str) -> dict:
    role = message["role"]
    attachments = message.get("attachments") or []
    if not attachments or role != "user":
        return {"role": role, "content": message["content"]}
    text = message["content"]
    for item in attachments:
        if item["kind"] == "text":
            content = base64.b64decode(item["data"]).decode("utf-8-sig")
            text += f"\n\nAttached file ({item['name']}):\n{content}"
    media = [item for item in attachments if item["kind"] != "text"]
    if mode == "chat" and any(item["kind"] == "pdf" for item in media):
        raise ProtocolError("pdf_not_supported")
    if not media:
        return {"role": "user", "content": text}
    if mode == "chat":
        parts = [{"type": "text", "text": text}]
        parts.extend({"type": "image_url", "image_url": {"url": f"data:{item['mime']};base64,{item['data']}"}} for item in media)
    elif mode == "responses":
        parts = [{"type": "input_text", "text": text}]
        for item in media:
            if item["kind"] == "image":
                parts.append({"type": "input_image", "image_url": f"data:{item['mime']};base64,{item['data']}"})
            else:
                parts.append({"type": "input_file", "filename": item["name"], "file_data": f"data:application/pdf;base64,{item['data']}"})
    elif mode == "claude":
        parts = [{"type": "text", "text": text}]
        for item in media:
            parts.append({
                "type": "image" if item["kind"] == "image" else "document",
                "source": {"type": "base64", "media_type": item["mime"], "data": item["data"]},
            })
    else:
        parts = [{"text": text}]
        parts.extend({"inlineData": {"mimeType": item["mime"], "data": item["data"]}} for item in media)
        return {"role": "user", "parts": parts}
    return {"role": "user", "content": parts}


def build_request(
    config: dict,
    system_prompt: str,
    messages: list[dict],
    images: list[dict] | None = None,
    schema: dict | None = None,
) -> RequestSpec:
    mode = config.get("api_mode", "chat")
    if mode not in DEFAULTS:
        raise ProtocolError("invalid_response")
    key = config.get("api_key", "").strip()
    model = config.get("model", "").strip()
    if not key:
        raise ProtocolError("missing_key")
    if not model:
        raise ProtocolError("missing_model")
    host = config.get("api_host", "").strip().rstrip("/")
    parts = urlsplit(host)
    if (
        parts.scheme not in ("http", "https")
        or not parts.netloc
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
    ):
        raise ProtocolError("invalid_host")
    path = config.get("api_path", "").strip()
    if not path.startswith("/") or path.startswith("//") or "?" in path or "#" in path:
        raise ProtocolError("invalid_path")
    path = path.replace("{model}", quote(model, safe=""))
    url = host if host.endswith(path) else host + path
    headers = {"Content-Type": "application/json"}
    images = images or []
    image_caption = "Reference images from the current Anki card: " + ", ".join(
        image["name"] for image in images
    )
    turns = [_message_for_provider(message, mode) for message in messages]

    if mode == "chat":
        headers["Authorization"] = f"Bearer {key}"
        image_messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": image_caption},
                    *(
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{image['mime']};base64,{image['data']}"},
                        }
                        for image in images
                    ),
                ],
            }
        ] if images else []
        body = {
            "model": model,
            "messages": [{"role": "system", "content": system_prompt}, *image_messages, *turns],
        }
        if schema:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "response", "strict": True, "schema": schema},
            }
    elif mode == "responses":
        headers["Authorization"] = f"Bearer {key}"
        image_messages = [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": image_caption},
                    *(
                        {"type": "input_image", "image_url": f"data:{image['mime']};base64,{image['data']}"}
                        for image in images
                    ),
                ],
            }
        ] if images else []
        body = {"model": model, "instructions": system_prompt, "input": image_messages + turns}
        if schema:
            body["text"] = {
                "format": {"type": "json_schema", "name": "response", "schema": schema, "strict": True}
            }
    elif mode == "claude":
        headers["x-api-key"] = key
        headers["anthropic-version"] = "2023-06-01"
        image_messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": image_caption},
                    *(
                        {
                            "type": "image",
                            "source": {
                                "type": "base64", "media_type": image["mime"], "data": image["data"]
                            },
                        }
                        for image in images
                    ),
                ],
            }
        ] if images else []
        body = {
            "model": model,
            "max_tokens": 2048,
            "system": system_prompt,
            "messages": image_messages + turns,
        }
        if schema:
            body["tools"] = [{
                "name": "response",
                "description": "Return the requested structured result.",
                "input_schema": schema,
            }]
            body["tool_choice"] = {"type": "tool", "name": "response"}
    else:
        headers["x-goog-api-key"] = key
        image_contents = [
            {
                "role": "user",
                "parts": [
                    {"text": image_caption},
                    *(
                        {"inlineData": {"mimeType": image["mime"], "data": image["data"]}}
                        for image in images
                    ),
                ],
            }
        ] if images else []
        body = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": image_contents + [
                {"role": "model" if message["role"] == "assistant" else "user",
                 "parts": turn["parts"] if "parts" in turn else [{"text": turn["content"]}]}
                for message, turn in zip(messages, turns)
            ],
        }
        if schema:
            generation = body.setdefault("generationConfig", {})
            generation["responseMimeType"] = "application/json"
            generation["responseSchema"] = schema
    return RequestSpec(url, headers, body)


def _text_parts(parts: list) -> str:
    return "\n".join(
        part["text"] for part in parts
        if isinstance(part, dict) and isinstance(part.get("text"), str)
    ).strip()


def parse_response(mode: str, data: dict) -> str:
    try:
        if mode == "chat":
            content = data["choices"][0]["message"]["content"]
            text = content if isinstance(content, str) else _text_parts(content)
        elif mode == "responses":
            text = _text_parts(
                [part for item in data.get("output", []) if item.get("type") == "message"
                 for part in item.get("content", []) if part.get("type") == "output_text"]
            )
        elif mode == "claude":
            tools = [
                part.get("input") for part in data["content"]
                if part.get("type") == "tool_use" and isinstance(part.get("input"), dict)
            ]
            text = json.dumps(tools[-1], ensure_ascii=False) if tools else _text_parts(
                [part for part in data["content"] if part.get("type") == "text"]
            )
        elif mode == "gemini":
            text = _text_parts(data["candidates"][0]["content"]["parts"])
        else:
            raise ProtocolError("invalid_response")
    except (KeyError, IndexError, TypeError, AttributeError) as error:
        raise ProtocolError("invalid_response") from error
    if not text:
        raise ProtocolError("empty_response")
    return text


def parse_usage(mode: str, data: dict) -> dict | None:
    """Normalize provider token usage into input/output/total/cached counts."""
    if not isinstance(data, dict):
        return None
    usage = data.get("usage") or data.get("usage_metadata") or data.get("usageMetadata")
    if not isinstance(usage, dict):
        return None

    def number(*keys):
        for key in keys:
            value = usage.get(key)
            if isinstance(value, (int, float)) and value >= 0:
                return int(value)
        return 0

    if mode == "chat":
        input_tokens = number("prompt_tokens", "input_tokens")
        output_tokens = number("completion_tokens", "output_tokens")
        total_tokens = number("total_tokens")
        details = usage.get("prompt_tokens_details") or {}
        cached_tokens = int(details.get("cached_tokens", 0) or 0)
    elif mode == "responses":
        input_tokens = number("input_tokens", "prompt_tokens")
        output_tokens = number("output_tokens", "completion_tokens")
        total_tokens = number("total_tokens")
        details = usage.get("input_tokens_details") or {}
        cached_tokens = int(details.get("cached_tokens", 0) or 0)
    elif mode == "claude":
        input_tokens = number("input_tokens", "prompt_tokens")
        output_tokens = number("output_tokens", "completion_tokens")
        cached_tokens = number("cache_read_input_tokens") + number("cache_creation_input_tokens")
        total_tokens = number("total_tokens") or input_tokens + output_tokens + cached_tokens
    elif mode == "gemini":
        input_tokens = number("promptTokenCount", "input_tokens")
        output_tokens = number("candidatesTokenCount", "output_tokens")
        total_tokens = number("totalTokenCount", "total_tokens")
        cached_tokens = number("cachedContentTokenCount")
    else:
        return None
    if total_tokens <= 0:
        total_tokens = input_tokens + output_tokens
    if not (input_tokens or output_tokens or total_tokens or cached_tokens):
        return None
    return {
        "input": input_tokens,
        "output": output_tokens,
        "total": total_tokens,
        "cached": cached_tokens,
    }


def provider_error(status: int, data: object) -> str:
    detail = ""
    if isinstance(data, dict):
        error = data.get("error", {})
        if isinstance(error, dict):
            detail = error.get("message", "")
        elif isinstance(error, str):
            detail = error
        if not detail and isinstance(data.get("message"), str):
            detail = data["message"]
    return f"HTTP {status}: {str(detail)[:500]}" if detail else f"HTTP {status}"
