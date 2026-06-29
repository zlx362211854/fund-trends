"""Render a compact, quality-aware observation dashboard with Pillow."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from src.quality import ISSUE_LABELS
from src.report.verdict import get_verdict

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
FONT_REG = PROJECT_ROOT / "fonts" / "NotoSansSC-Regular.otf"
FONT_BOLD = PROJECT_ROOT / "fonts" / "NotoSansSC-Bold.otf"

BG = "#f3f4f6"
CARD = "#ffffff"
BORDER = "#d1d5db"
TEXT = "#111827"
TEXT_DIM = "#4b5563"
TEXT_FAINT = "#6b7280"
TRACK = "#e5e7eb"
BLUE = "#2563eb"
PURPLE = "#7c3aed"
GREEN = "#059669"

LEVEL_STYLES = {
    "high_attention": ("#047857", "#ecfdf5", "高关注"),
    "attention": ("#0f766e", "#f0fdfa", "较高关注"),
    "neutral": ("#a16207", "#fffbeb", "中性观察"),
    "caution": ("#c2410c", "#fff7ed", "谨慎观察"),
    "low_attention": ("#b91c1c", "#fef2f2", "低关注"),
}

QUALITY_STYLES = {
    "reliable": ("#047857", "数据可靠"),
    "degraded": ("#b45309", "数据降级"),
    "unscorable": ("#b91c1c", "不可评分"),
}

TYPE_TAG = {
    "domestic_active": "国内主动",
    "domestic_index": "国内指数",
    "qdii_index": "QDII 指数",
}

_font_cache: dict[tuple[bool, int], ImageFont.FreeTypeFont] = {}


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    key = (bold, size)
    if key not in _font_cache:
        _font_cache[key] = ImageFont.truetype(
            str(FONT_BOLD if bold else FONT_REG), size
        )
    return _font_cache[key]


def _text_width(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0]


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for char in text:
        candidate = current + char
        if current and _text_width(draw, candidate, font) > max_width:
            lines.append(current)
            current = char
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def _badge(
    draw: ImageDraw.ImageDraw,
    right: int,
    top: int,
    text: str,
    foreground: str,
    background: str,
) -> None:
    font = _font(14, bold=True)
    width = _text_width(draw, text, font) + 24
    draw.rounded_rectangle(
        (right - width, top, right, top + 34),
        radius=8,
        fill=background,
        outline=foreground,
        width=1,
    )
    draw.text((right - width + 12, top + 7), text, font=font, fill=foreground)


def _progress(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    width: int,
    label: str,
    score: float | None,
    color: str,
) -> None:
    label_font = _font(14)
    value = "-" if score is None else f"{score:.0f}"
    draw.text((x, y), label, font=label_font, fill=TEXT_DIM)
    draw.text((x + width - 24, y), value, font=_font(14, bold=True), fill=TEXT)
    bar_y = y + 24
    draw.rounded_rectangle((x, bar_y, x + width, bar_y + 8), radius=4, fill=TRACK)
    if score is not None:
        fill_width = max(4, int(width * max(0, min(100, score)) / 100))
        draw.rounded_rectangle(
            (x, bar_y, x + fill_width, bar_y + 8), radius=4, fill=color
        )


CARD_X = 28
CARD_W = 844
CARD_GAP = 18
HEADER_H = 116
FOOTER_H = 62


def _card_height(result: dict) -> int:
    if result.get("total_score") is None:
        return 220 + 24 * min(3, len(result["quality"].get("issues", [])))
    issues = min(3, len(result["quality"].get("issues", [])))
    reason = (result.get("event") or {}).get("reason", "")
    reason_lines = 1 if reason else 0
    return 388 + issues * 22 + reason_lines * 22


def _draw_unscorable(
    draw: ImageDraw.ImageDraw, y: int, result: dict, height: int
) -> None:
    draw.rounded_rectangle(
        (CARD_X, y, CARD_X + CARD_W, y + height),
        radius=8,
        fill=CARD,
        outline=BORDER,
        width=1,
    )
    draw.rectangle((CARD_X, y, CARD_X + 6, y + height), fill="#b91c1c")
    draw.text((CARD_X + 28, y + 24), result["name"], font=_font(26, True), fill=TEXT)
    meta = f"{result['code']}  ·  {TYPE_TAG.get(result.get('type', ''), '')}"
    draw.text((CARD_X + 28, y + 64), meta, font=_font(14), fill=TEXT_DIM)
    _badge(
        draw,
        CARD_X + CARD_W - 24,
        y + 24,
        "不可评分",
        "#b91c1c",
        "#fef2f2",
    )
    draw.text(
        (CARD_X + 28, y + 108),
        "数据恢复前不生成数值观察分",
        font=_font(18, True),
        fill="#b91c1c",
    )
    cursor = y + 146
    for issue in result["quality"].get("issues", [])[:3]:
        draw.text(
            (CARD_X + 28, cursor),
            "• " + ISSUE_LABELS.get(issue, issue),
            font=_font(14),
            fill=TEXT_DIM,
        )
        cursor += 24


def _draw_scored(
    draw: ImageDraw.ImageDraw, y: int, result: dict, height: int
) -> None:
    level = result["observation_level"]
    accent, accent_bg, level_label = LEVEL_STYLES[level]
    quality = result["quality"]
    quality_color, quality_label = QUALITY_STYLES[quality["status"]]
    technical = result["technical"]
    valuation = result["valuation"]
    event = result["event"]

    draw.rounded_rectangle(
        (CARD_X, y, CARD_X + CARD_W, y + height),
        radius=8,
        fill=CARD,
        outline=BORDER,
        width=1,
    )
    draw.rectangle((CARD_X, y, CARD_X + 6, y + height), fill=accent)
    name = result["name"]
    name_font = _font(26, True)
    while _text_width(draw, name, name_font) > 500 and len(name) > 6:
        name = name[:-2] + "…"
    draw.text((CARD_X + 28, y + 22), name, font=name_font, fill=TEXT)
    meta = f"{result['code']}  ·  {TYPE_TAG.get(result.get('type', ''), '')}  ·  {result['scoring_version']}"
    draw.text((CARD_X + 28, y + 62), meta, font=_font(14), fill=TEXT_DIM)
    _badge(draw, CARD_X + CARD_W - 24, y + 22, level_label, accent, accent_bg)

    draw.text((CARD_X + 28, y + 105), "观察分", font=_font(15), fill=TEXT_DIM)
    draw.text(
        (CARD_X + 28, y + 124),
        f"{result['total_score']:.0f}",
        font=_font(60, True),
        fill=accent,
    )
    draw.text((CARD_X + 118, y + 166), "/100", font=_font(16), fill=TEXT_FAINT)
    draw.text(
        (CARD_X + 28, y + 204),
        f"● {quality_label}",
        font=_font(14, True),
        fill=quality_color,
    )

    bar_x = CARD_X + 220
    bar_width = 176
    _progress(draw, bar_x, y + 112, bar_width, "技术", technical["score"], BLUE)
    _progress(
        draw,
        bar_x + 196,
        y + 112,
        bar_width,
        "估值代理",
        valuation["score"],
        PURPLE,
    )
    _progress(
        draw,
        bar_x + 392,
        y + 112,
        bar_width,
        "事件",
        event.get("score") if event else None,
        GREEN,
    )

    metrics_y = y + 250
    metrics = (
        ("1年分位", f"{technical['quantile_1y'] * 100:.0f}%"),
        ("回撤", f"{technical['drawdown_pct']:.1f}%"),
        ("距MA60", f"{technical['ma60_dist_pct']:+.1f}%"),
        ("RSI", f"{technical['rsi_14']:.0f}"),
    )
    for index, (label, value) in enumerate(metrics):
        x = CARD_X + 28 + index * 196
        draw.text((x, metrics_y), label, font=_font(13), fill=TEXT_FAINT)
        draw.text((x, metrics_y + 22), value, font=_font(18, True), fill=TEXT)

    cursor = y + 316
    draw.text(
        (CARD_X + 28, cursor),
        f"估值代理方法：{valuation['method']}",
        font=_font(13),
        fill=TEXT_DIM,
    )
    cursor += 25
    for issue in quality.get("issues", [])[:3]:
        draw.text(
            (CARD_X + 28, cursor),
            "• " + ISSUE_LABELS.get(issue, issue),
            font=_font(13),
            fill="#b45309",
        )
        cursor += 22
    reason = (event or {}).get("reason")
    if reason:
        text = "事件摘要：" + reason
        line = _wrap(draw, text, _font(13), CARD_W - 56)[0]
        draw.text((CARD_X + 28, cursor), line, font=_font(13), fill=TEXT_DIM)
        cursor += 22
    draw.text(
        (CARD_X + 28, cursor + 4),
        get_verdict(level),
        font=_font(15, True),
        fill=accent,
    )


def render_dashboard(results: list[dict], output_path: str | Path) -> Path:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    heights = [_card_height(result) for result in results]
    total_height = HEADER_H + sum(heights) + CARD_GAP * len(results) + FOOTER_H
    image = Image.new("RGB", (900, total_height), BG)
    draw = ImageDraw.Draw(image)

    today = date.today()
    weekday = ["一", "二", "三", "四", "五", "六", "日"][today.weekday()]
    draw.text((28, 24), "基金观察日报", font=_font(30, True), fill=TEXT)
    draw.text(
        (28, 68),
        f"{today.isoformat()}  周{weekday}  ·  监控 {len(results)} 只",
        font=_font(14),
        fill=TEXT_DIM,
    )

    cursor = HEADER_H
    for result, height in zip(results, heights):
        if result.get("total_score") is None:
            _draw_unscorable(draw, cursor, result, height)
        else:
            _draw_scored(draw, cursor, result, height)
        cursor += height + CARD_GAP

    footer = "观察分仅用于研究排序，不是收益预测或操作指令"
    width = _text_width(draw, footer, _font(13))
    draw.text(
        ((900 - width) // 2, total_height - 40),
        footer,
        font=_font(13),
        fill=TEXT_FAINT,
    )
    image.save(output, format="PNG", optimize=True)
    return output
