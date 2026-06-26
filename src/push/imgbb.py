"""ImgBB 图床上传
免费图床:https://imgbb.com/
注册账号 → 获取 API Key → 设置环境变量 IMGBB_API_KEY
"""
from __future__ import annotations

import base64
import os
from pathlib import Path

import httpx
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
def upload_imgbb(image_path: str | Path, api_key: str | None = None) -> str | None:
    """上传图片到 ImgBB,返回直链 URL。失败返回 None。"""
    api_key = api_key or os.getenv("IMGBB_API_KEY")
    if not api_key:
        logger.warning("[imgbb] 未配置 IMGBB_API_KEY,跳过图片上传")
        return None

    p = Path(image_path)
    if not p.exists():
        logger.error(f"[imgbb] 图片不存在: {p}")
        return None

    with open(p, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()

    try:
        resp = httpx.post(
            "https://api.imgbb.com/1/upload",
            data={"key": api_key, "image": b64, "name": p.stem},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("success"):
            logger.error(f"[imgbb] 上传失败: {data}")
            return None
        url = data["data"]["url"]
        logger.success(f"[imgbb] 上传成功: {url}")
        return url
    except Exception as e:
        logger.error(f"[imgbb] 上传异常: {e}")
        raise
