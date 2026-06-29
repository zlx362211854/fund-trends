"""Render a compact dual-horizon observation dashboard with Pillow."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from src.quality import ISSUE_LABELS
from src.report.daily import LEVEL_LABELS, QUALITY_INFO, TYPE_TAG, _combination_summary

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
LONG_COLOR = "#047857"
TIMING_COLOR = "#2563eb"
WARN = "#b45309"
ERROR = "#b91c1c"

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


def _wrap(
    draw: ImageDraw.ImageDraw, text: str, font, max_width: int, max_lines: int
) -> list[str]:
    lines: list[str] = []
    current = ""
    for char in text:
        candidate = current + char
        if current and _text_width(draw, candidate, font) > max_width:
            lines.append(current)
            current = char
            if len(lines) == max_lines:
                break
        else:
            current = candidate
    if len(lines) < max_lines and current:
        lines.append(current)
    if lines and len("".join(lines)) < len(text):
        lines[-1] = lines[-1][:-1] + "…"
    return lines


def _badge(
    draw: ImageDraw.ImageDraw,
    right: int,
    top: int,
    text: str,
    foreground: str,
) -> None:
    font = _font(13, True)
    width = _text_width(draw, text, font) + 22
    draw.rounded_rectangle(
        (right - width, top, right, top + 30),
        radius=6,
        fill="#ffffff",
        outline=foreground,
        width=1,
    )
    draw.text((right - width + 11, top + 6), text, font=font, fill=foreground)


def _factor_bar(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    width: int,
    label: str,
    value: float | None,
    color: str,
) -> None:
    shown = "-" if value is None else f"{value:.0f}"
    draw.text((x, y), label, font=_font(12), fill=TEXT_DIM)
    draw.text((x + width - 22, y), shown, font=_font(12, True), fill=TEXT)
    draw.rounded_rectangle((x, y + 20, x + width, y + 26), 3, fill=TRACK)
    if value is not None:
        fill = max(4, int(width * max(0, min(100, value)) / 100))
        draw.rounded_rectangle((x, y + 20, x + fill, y + 26), 3, fill=color)


def _score_panel(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    width: int,
    title: str,
    score: dict,
    color: str,
    factor_labels: tuple[tuple[str, str], ...],
) -> None:
    draw.text((x, y), title, font=_font(15, True), fill=TEXT)
    numeric = score.get("score")
    if numeric is None:
        draw.text((x, y + 32), "--", font=_font(42, True), fill=TEXT_FAINT)
        draw.text((x + 68, y + 51), "暂不可评估", font=_font(14), fill=ERROR)
    else:
        draw.text((x, y + 26), f"{numeric:.0f}", font=_font(48, True), fill=color)
        draw.text((x + 67, y + 56), "/100", font=_font(13), fill=TEXT_FAINT)
        level = LEVEL_LABELS.get(score.get("level"), "状态未知")
        draw.text((x + 118, y + 51), level, font=_font(14, True), fill=color)

    factors = score.get("factors", {})
    first, second = factor_labels[:2]
    third, fourth = factor_labels[2:]
    half = (width - 18) // 2
    _factor_bar(draw, x, y + 96, half, first[1], factors.get(first[0]), color)
    _factor_bar(
        draw, x + half + 18, y + 96, half, second[1], factors.get(second[0]), color
    )
    _factor_bar(draw, x, y + 140, half, third[1], factors.get(third[0]), color)
    _factor_bar(
        draw, x + half + 18, y + 140, half, fourth[1], factors.get(fourth[0]), color
    )


CARD_X = 28
CARD_W = 844
CARD_H = 444
CARD_GAP = 18
HEADER_H = 108
FOOTER_H = 60


def _draw_card(draw: ImageDraw.ImageDraw, y: int, result: dict) -> None:
    draw.rounded_rectangle(
        (CARD_X, y, CARD_X + CARD_W, y + CARD_H),
        radius=8,
        fill=CARD,
        outline=BORDER,
        width=1,
    )
    draw.rectangle((CARD_X, y, CARD_X + 6, y + CARD_H), fill=TIMING_COLOR)
    name = result["name"]
    name_font = _font(24, True)
    while _text_width(draw, name, name_font) > 540 and len(name) > 6:
        name = name[:-2] + "…"
    draw.text((CARD_X + 28, y + 20), name, font=name_font, fill=TEXT)
    meta = (
        f"{result['code']}  ·  {TYPE_TAG.get(result.get('type', ''), '')}"
        f"  ·  {result['scoring_version']}"
    )
    draw.text((CARD_X + 28, y + 55), meta, font=_font(13), fill=TEXT_DIM)
    quality_label, _ = QUALITY_INFO.get(
        result["quality"].get("status"), ("状态未知", "")
    )
    quality_color = LONG_COLOR if result["quality"].get("status") == "reliable" else WARN
    if result["quality"].get("status") == "unscorable":
        quality_color = ERROR
    _badge(
        draw,
        CARD_X + CARD_W - 24,
        y + 21,
        quality_label,
        quality_color,
    )

    summary = _combination_summary(result)
    summary_lines = _wrap(draw, summary, _font(14), CARD_W - 56, 2)
    for index, line in enumerate(summary_lines):
        draw.text((CARD_X + 28, y + 86 + index * 21), line, font=_font(14), fill=TEXT_DIM)

    panel_y = y + 132
    panel_w = 380
    _score_panel(
        draw,
        CARD_X + 28,
        panel_y,
        panel_w,
        "长期持有条件",
        result["long_term"],
        LONG_COLOR,
        (("valuation", "估值"), ("trend", "趋势"), ("risk", "风险"), ("tracking", "跟踪")),
    )
    _score_panel(
        draw,
        CARD_X + 436,
        panel_y,
        panel_w,
        "当前投入时机",
        result["timing"],
        TIMING_COLOR,
        (("trend", "趋势"), ("deviation", "偏离"), ("stabilization", "企稳"), ("temperature", "温度")),
    )

    issues = result["quality"].get("issues", [])
    status_y = y + 352
    if issues:
        issue_text = "数据提示：" + "；".join(
            ISSUE_LABELS.get(issue, issue) for issue in issues[:2]
        )
    else:
        inputs = result["quality"].get("inputs", {})
        valuation_date = inputs.get("ndx_valuation", {}).get("date")
        nav_date = inputs.get("nav", {}).get("date")
        issue_text = f"数据日期：净值 {str(nav_date or '未知')[:10]}"
        if valuation_date:
            issue_text += f" · 估值 {str(valuation_date)[:10]}"
    for index, line in enumerate(
        _wrap(draw, issue_text, _font(12), CARD_W - 56, 2)
    ):
        draw.text((CARD_X + 28, status_y + index * 19), line, font=_font(12), fill=TEXT_DIM)

    reason = (result.get("event") or {}).get("reason")
    if reason:
        event_text = "AI事件（不参与评分）：" + reason
        line = _wrap(draw, event_text, _font(12), CARD_W - 56, 1)[0]
        draw.text((CARD_X + 28, y + 407), line, font=_font(12), fill=TEXT_FAINT)


def render_dashboard(results: list[dict], output_path: str | Path) -> Path:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    total_height = HEADER_H + len(results) * (CARD_H + CARD_GAP) + FOOTER_H
    image = Image.new("RGB", (900, total_height), BG)
    draw = ImageDraw.Draw(image)

    today = date.today()
    weekday = ["一", "二", "三", "四", "五", "六", "日"][today.weekday()]
    draw.text((28, 22), "基金双周期观察", font=_font(28, True), fill=TEXT)
    draw.text(
        (28, 64),
        f"{today.isoformat()}  周{weekday}  ·  监控 {len(results)} 只",
        font=_font(13),
        fill=TEXT_DIM,
    )

    cursor = HEADER_H
    for result in results:
        _draw_card(draw, cursor, result)
        cursor += CARD_H + CARD_GAP

    footer = "双评分仅用于研究观察，不是收益预测或操作指令"
    width = _text_width(draw, footer, _font(13))
    draw.text(
        ((900 - width) // 2, total_height - 38),
        footer,
        font=_font(13),
        fill=TEXT_FAINT,
    )
    image.save(output, format="PNG", optimize=True)
    return output
