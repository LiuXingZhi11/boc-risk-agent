"""加载业务人员可维护的提示词、抽取规则和画像逻辑。"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Mapping

import yaml

from src.ontology.loader import load_manifest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROMPTS_DIR = PROJECT_ROOT / "prompts"
ONTOLOGY_DATA_PATH = PROMPTS_DIR / "data" / "企业画像本体.yaml"
EXTRACTION_RULES_PATH = PROMPTS_DIR / "data" / "企业画像抽取规则.yaml"
PROFILE_DIMENSIONS_PATH = PROMPTS_DIR / "logic" / "企业画像维度映射.yaml"


def load_prompt(filename: str) -> str:
    """读取 prompts 目录中的运行时 Markdown。"""
    return (PROMPTS_DIR / filename).read_text(encoding="utf-8").strip()


def render_prompt(filename: str, values: Mapping[str, object]) -> str:
    """替换 Markdown 中显式声明的 {{placeholder}}。"""
    content = load_prompt(filename)
    for key, value in values.items():
        content = content.replace("{{" + key + "}}", str(value))
    return content


def load_prompt_section(filename: str, heading: str) -> str:
    """读取 Markdown 中以指定二级标题开始的业务规则段落。"""
    content = load_prompt(filename)
    marker = f"## {heading}"
    if marker not in content:
        raise ValueError(f"提示词未定义段落：{filename} -> {heading}")
    section = content.split(marker, 1)[1]
    return section.split("\n## ", 1)[0].strip()


def render_prompt_section(
    filename: str, heading: str, values: Mapping[str, object]
) -> str:
    """读取并替换指定业务规则段落中的运行时占位符。"""
    content = load_prompt_section(filename, heading)
    for key, value in values.items():
        content = content.replace("{{" + key + "}}", str(value))
    return content


def load_profile_domain_rules(
    domain: str,
    field_ids: Iterable[str] | None = None,
) -> str:
    """从 Ontology YAML 生成当前领域的可读字段语义规则。"""
    manifest = load_manifest()
    extraction_rules = yaml.safe_load(
        EXTRACTION_RULES_PATH.read_text(encoding="utf-8")
    )
    fields = manifest.get("fields", [])
    selected = set(field_ids or ())
    if selected:
        fields = [field for field in fields if field["id"] in selected]
    if not fields:
        raise ValueError(f"Ontology 未定义可用于领域的字段：{domain}")

    lines = [f"当前调查领域：{domain}", "通用数据规则："]
    lines.extend(f"- {rule}" for rule in extraction_rules.get("extraction_rules", []))
    domain_guidance = extraction_rules.get("domain_guidance", {}).get(domain, [])
    if domain_guidance:
        lines.append(f"{domain} 领域补充规则：")
        lines.extend(f"- {rule}" for rule in domain_guidance)
    lines.append("当前领域字段说明：")
    for field in fields:
        lines.extend(
            [
                f"### {field['id']}｜{field.get('label', field['id'])}",
                f"定义：{field.get('description', '按原文抽取该字段。')}",
                f"同义词或常见表述：{'、'.join(field.get('synonyms', [])) or '无'}",
                f"可归入：{'；'.join(field.get('include_when', [])) or '原文明确支持时'}",
                f"不得归入：{'；'.join(field.get('exclude_when', [])) or '无法由原文确认的内容'}",
                f"抽取注意：{'；'.join(field.get('extraction_notes', [])) or '保留主体、期间、单位和统计口径。'}",
            ]
        )
        if field.get("allowed_values"):
            lines.append(f"允许值：{'、'.join(field['allowed_values'])}")
    return "\n".join(lines)


def load_profile_dimension_mapping() -> dict[str, object]:
    """读取事实层到企业画像维度的逻辑映射。"""
    return yaml.safe_load(PROFILE_DIMENSIONS_PATH.read_text(encoding="utf-8"))
