"""Payload and response adapters for four AI API families."""

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


def build_request(
    config: dict, system_prompt: str, messages: list[dict], images: list[dict] | None = None
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
            "messages": [{"role": "system", "content": system_prompt}, *image_messages, *messages],
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
        body = {"model": model, "instructions": system_prompt, "input": image_messages + messages}
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
            "messages": image_messages + messages,
        }
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
                {
                    "role": "model" if message["role"] == "assistant" else "user",
                    "parts": [{"text": message["content"]}],
                }
                for message in messages
            ],
        }
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
            text = _text_parts(
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
