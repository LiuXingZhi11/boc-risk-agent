"""UTF-8 文本和 JSON 工具。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_text(path: str | Path) -> str:
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"文件不存在：{file_path}")
    text = file_path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"文件内容为空：{file_path}")
    return text


def load_json(path: str | Path) -> dict[str, Any]:
    file_path = Path(path)
    try:
        data = json.loads(load_text(file_path))
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 文件解析失败：{file_path}：{exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"JSON 顶层必须是对象：{file_path}")
    return data


def save_json(path: str | Path, data: dict[str, Any]) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def extract_json_from_text(text: str) -> dict[str, Any]:
    """解析纯 JSON、代码块 JSON 或包裹在说明文字中的 JSON 对象。"""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("模型输出为空，无法解析 JSON。")
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].lstrip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    decoder = json.JSONDecoder()
    try:
        value, end = decoder.raw_decode(cleaned)
        if not cleaned[end:].strip():
            if isinstance(value, dict):
                return value
            raise ValueError("JSON 顶层必须是对象。")
    except json.JSONDecodeError:
        pass

    for index, char in enumerate(cleaned):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(cleaned[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("模型输出中未找到合法 JSON 对象。")

