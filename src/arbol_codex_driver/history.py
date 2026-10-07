import base64
import os
import secrets
from pathlib import Path

from .json_types import Json, Object, dumps, object_value


def images(item: Object) -> list[Object]:
    raw = item.get("images")
    return [object_value(image) for image in raw] if isinstance(raw, list) else []


def tool_result_text(item: Object) -> str:
    result = item.get("result")
    text = ""
    if isinstance(result, str):
        text = result
    elif "result" in item:
        if item.get("name") == "shell" and isinstance(result, dict) and "output" in result:
            text = result["output"] if isinstance(result["output"], str) else dumps(result["output"])
            if isinstance(result.get("exitCode"), (int, float)) and result["exitCode"] != 0:
                text += "\nexit code: " + dumps(result["exitCode"])
        else:
            text = dumps(result)
    if not item.get("ok") and item.get("error"):
        text += ("\n" if text else "") + str(item["error"])
    return text


def history_items(history: list[Object]) -> list[Json]:
    items: list[Json] = []
    for item in history:
        if item.get("type") == "message":
            content: list[Json] = [
                {"type": "input_text" if item["role"] == "user" else "output_text", "text": item["text"]}
            ]
            content.extend(
                {"type": "input_image", "image_url": f"data:{picture['mediaType']};base64,{picture['data']}"}
                for picture in images(item)
            )
            items.append({"type": "message", "role": item["role"], "content": content})
        else:
            call_id = "call_" + secrets.token_hex(12)
            input_ = item["input"]
            if item["name"] == "shell" and isinstance(input_, dict):
                input_ = {key: input_[key] for key in ("command", "cwd") if key in input_}
            items.extend(
                [
                    {"type": "function_call", "name": item["name"], "arguments": dumps(input_), "call_id": call_id},
                    {"type": "function_call_output", "call_id": call_id, "output": tool_result_text(item)},
                ]
            )
    return items


def labelled_history_input(history: list[Object], input_: Object) -> Object:
    parts = ["Earlier conversation, for context:\n"]
    pictures: list[Json] = []
    for item in history:
        if item.get("type") == "message":
            attachments = images(item)
            parts.append(
                f"[{'User' if item['role'] == 'user' else 'Assistant'}]\n{item['text']}"
                + (f"\n[Images: {len(attachments)}]" if attachments else "")
            )
            pictures.extend(attachments)
        else:
            parts.append(
                f"[Tool call: {item['name']}]\n{dumps(item['input'])}\n[Tool {'result' if item['ok'] else 'error'}]\n{tool_result_text(item)}"
            )
    return {
        "text": "\n".join(parts) + "\n\nNew message:\n\n" + str(input_["text"]),
        "images": [*pictures, *images(input_)],
    }


def prepare_turn_input(input_: Object, temporary: Path) -> list[Json]:
    message: list[Json] = [{"type": "text", "text": input_["text"]}]
    extensions = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif"}
    for index, picture in enumerate(images(input_)):
        path = temporary / f"image-{index}.{extensions[str(picture['mediaType'])]}"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as file:
            file.write(base64.b64decode(str(picture["data"])))
        message.append({"type": "localImage", "path": str(path)})
    return message
