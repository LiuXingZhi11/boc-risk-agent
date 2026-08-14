from __future__ import annotations

import argparse
import csv
import hashlib
import mimetypes
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests


def safe_name(text: str, max_len: int = 100) -> str:
    text = re.sub(r'[\\/:*?"<>|]+', "_", text).strip()
    text = re.sub(r"\s+", "_", text)
    return text[:max_len] or "source"


def choose_suffix(url: str, content_type: str) -> str:
    path_suffix = Path(urlparse(url).path).suffix.lower()
    if path_suffix in {".pdf", ".html", ".htm", ".txt", ".doc", ".docx", ".xls", ".xlsx"}:
        return path_suffix
    content_type = (content_type or "").split(";")[0].strip().lower()
    if content_type == "application/pdf":
        return ".pdf"
    if content_type in {"text/html", "application/xhtml+xml"}:
        return ".html"
    return mimetypes.guess_extension(content_type) or ".bin"


def extract_pdf_links(content: bytes, base_url: str) -> list[str]:
    """从公告 HTML 中提取 PDF 附件链接，保留顺序并去重。"""
    matches = re.findall(
        rb"(?i)(?:https?:)?//[^\"'<>\s]+?\.pdf(?:\?[^\"'<>\s]*)?",
        content,
    )
    links: list[str] = []
    for raw in matches:
        link = urljoin(base_url, raw.decode("ascii", errors="ignore"))
        if link not in links:
            links.append(link)
    return links


def main() -> None:
    parser = argparse.ArgumentParser(description="下载 Ontology 数据来源清单中的公开材料")
    parser.add_argument("--manifest", default="material_manifest.csv")
    parser.add_argument("--output", default="downloaded_sources")
    parser.add_argument("--groups", nargs="*", help="仅下载指定 case_group")
    parser.add_argument("--priorities", nargs="*", default=["最高", "高", "中"])
    parser.add_argument("--delay", type=float, default=0.8)
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument(
        "--download-attachments",
        action="store_true",
        help="HTML 页面下载成功后，继续下载页面中的第一个 PDF 附件",
    )
    parser.add_argument(
        "--log",
        default="download_log.csv",
        help="下载日志文件名，默认 download_log.csv",
    )
    args = parser.parse_args()

    manifest = Path(args.manifest)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)

    with manifest.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/124 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/pdf,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
    })

    log_rows = []
    for row in rows:
        if args.groups and row["case_group"] not in args.groups:
            continue
        if row["priority"] not in args.priorities:
            continue

        group_dir = output / safe_name(row["case_group"])
        group_dir.mkdir(parents=True, exist_ok=True)
        base_name = f'{row["source_id"]}_{safe_name(row["title"])}'

        try:
            response = session.get(row["url"], timeout=args.timeout, allow_redirects=True)
            response.raise_for_status()
            suffix = choose_suffix(response.url, response.headers.get("Content-Type", ""))
            target = group_dir / f"{base_name}{suffix}"
            target.write_bytes(response.content)

            sha256 = hashlib.sha256(response.content).hexdigest()
            status = "ok"
            message = ""
            saved_path = str(target)
        except Exception as exc:
            status = "failed"
            message = repr(exc)
            saved_path = ""
            sha256 = ""

        attachment_status = "not_requested"
        attachment_url = ""
        attachment_path = ""
        attachment_sha256 = ""
        attachment_message = ""
        if status == "ok" and args.download_attachments and suffix in {".html", ".htm"}:
            attachment_status = "not_found"
            attachment_links = extract_pdf_links(response.content, response.url)
            if attachment_links:
                attachment_url = attachment_links[0]
                try:
                    attachment_response = session.get(
                        attachment_url,
                        timeout=args.timeout,
                        allow_redirects=True,
                    )
                    attachment_response.raise_for_status()
                    if not attachment_response.content.lstrip().startswith(b"%PDF"):
                        raise ValueError("附件响应不是有效 PDF（缺少 %PDF 文件头）")
                    attachment_target = group_dir / f"{base_name}_attachment.pdf"
                    attachment_target.write_bytes(attachment_response.content)
                    attachment_path = str(attachment_target)
                    attachment_sha256 = hashlib.sha256(attachment_response.content).hexdigest()
                    attachment_status = "ok"
                except Exception as exc:
                    attachment_status = "failed"
                    attachment_message = repr(exc)

        log_rows.append({
            "source_id": row["source_id"],
            "title": row["title"],
            "url": row["url"],
            "status": status,
            "saved_path": saved_path,
            "sha256": sha256,
            "message": message,
            "attachment_status": attachment_status,
            "attachment_url": attachment_url,
            "attachment_path": attachment_path,
            "attachment_sha256": attachment_sha256,
            "attachment_message": attachment_message,
        })
        print(
            f'[{status}] {row["source_id"]} {row["title"]}'
            f' attachment={attachment_status}'
        )
        time.sleep(args.delay)

    log_path = output / args.log
    with log_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(log_rows[0].keys()) if log_rows else [
            "source_id", "title", "url", "status", "saved_path", "sha256", "message",
            "attachment_status", "attachment_url", "attachment_path",
            "attachment_sha256", "attachment_message",
        ])
        writer.writeheader()
        writer.writerows(log_rows)

    failed = sum(1 for row in log_rows if row["status"] != "ok")
    print(f"完成：{len(log_rows)} 条，失败 {failed} 条。日志：{log_path}")


if __name__ == "__main__":
    main()
