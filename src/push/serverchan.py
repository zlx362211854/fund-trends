"""Server酱 推送
官方文档:https://sct.ftqq.com/
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import httpx
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config import Config
from src.db import get_conn
from src.push.imgbb import upload_imgbb


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
def _send(send_key: str, title: str, desp: str) -> dict:
    url = f"https://sctapi.ftqq.com/{send_key}.send"
    r = httpx.post(url, data={"title": title, "desp": desp}, timeout=20)
    r.raise_for_status()
    return r.json()


def push(
    cfg: Config,
    title: str,
    body: str,
    push_type: str = "daily",
    image_path: str | Path | None = None,
) -> bool:
    # 如果提供图片,先上传图床,把 URL 嵌入正文顶部
    if image_path:
        try:
            url = upload_imgbb(image_path)
            if url:
                body = (
                    f"![dashboard]({url})\n\n"
                    f"[🔍 查看高清原图]({url})\n\n"
                    f"{body}"
                )
        except Exception as e:
            logger.error(f"[push] 图片上传失败,仅推送文字: {e}")
    success = False
    err: str | None = None
    try:
        resp = _send(cfg.push.serverchan_key, title, body)
        if resp.get("code") == 0:
            success = True
            logger.success(f"[push] OK: {title}")
        else:
            err = str(resp)
            logger.error(f"[push] Server酱返回错误: {resp}")
    except Exception as e:
        err = str(e)
        logger.error(f"[push] 推送失败: {e}")

    with get_conn(cfg.db_path) as conn:
        conn.execute(
            "INSERT INTO push_history(push_type, push_date, title, content, success, error) "
            "VALUES (?,?,?,?,?,?)",
            (push_type, date.today().isoformat(), title, body, int(success), err),
        )

    return success
