"""生成基金日报 Dashboard 图片(Pillow 手绘暗色卡片风格)"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont

from src.report.verdict import get_verdict

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
FONT_REG = PROJECT_ROOT / "fonts" / "NotoSansSC-Regular.otf"
FONT_BOLD = PROJECT_ROOT / "fonts" / "NotoSansSC-Bold.otf"

# ---------------- 调色板 ----------------
BG          = "#0f172a"          # slate-900
CARD        = "#1e293b"          # slate-800
CARD_BORDER = "#334155"          # slate-700
TEXT        = "#e2e8f0"          # slate-200
TEXT_DIM    = "#94a3b8"          # slate-400
TEXT_FAINT  = "#64748b"          # slate-500
TRACK       = "#334155"          # 进度条底
ACCENT      = "#3b82f6"          # blue
BADGE_BG    = "#0b1220"

REC_COLORS = {
    "strong_buy": ("#22c55e", "#052e16", "强烈加仓"),   # green
    "buy":        ("#10b981", "#022c22", "可加仓"),
    "neutral":    ("#f59e0b", "#231507", "小幅 / 定投"),
    "watch":      ("#fb923c", "#2a1604", "观望"),
    "avoid":      ("#ef4444", "#2a0a0a", "暂不加仓"),
}

TYPE_TAG = {
    "domestic_active": "国内主动",
    "domestic_index":  "国内指数",
    "qdii_index":      "QDII 指数",
}


# ---------------- 字体缓存 ----------------
_font_cache: dict[tuple[bool, int], ImageFont.FreeTypeFont] = {}


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    key = (bold, size)
    if key not in _font_cache:
        path = FONT_BOLD if bold else FONT_REG
        _font_cache[key] = ImageFont.truetype(str(path), size)
    return _font_cache[key]


# ---------------- 工具 ----------------
def _text_size(draw: ImageDraw.ImageDraw, text: str, font) -> tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def _draw_progress(
    draw: ImageDraw.ImageDraw,
    x: int, y: int, w: int, h: int,
    pct: float, color: str,
) -> None:
    """画进度条:圆角底 + 圆角填充。"""
    pct = max(0.0, min(1.0, pct))
    draw.rounded_rectangle((x, y, x + w, y + h), radius=h // 2, fill=TRACK)
    fill_w = int(w * pct)
    if fill_w >= h:
        draw.rounded_rectangle((x, y, x + fill_w, y + h), radius=h // 2, fill=color)
    elif fill_w > 0:
        # 太短时画椭圆,避免圆角变形
        draw.ellipse((x, y, x + h, y + h), fill=color)


def _draw_metric_pair(
    draw: ImageDraw.ImageDraw,
    x: int, y: int,
    label: str, value: str,
    label_color=TEXT_FAINT, value_color=TEXT,
) -> int:
    """画一个 "label: value" 对,返回总宽度。"""
    f_l = _font(14)
    f_v = _font(16, bold=True)
    draw.text((x, y + 4), label, font=f_l, fill=label_color)
    lw, _ = _text_size(draw, label, f_l)
    draw.text((x + lw + 6, y), value, font=f_v, fill=value_color)
    vw, _ = _text_size(draw, value, f_v)
    return lw + 6 + vw


# ---------------- 卡片 ----------------
CARD_W = 760
CARD_PAD = 28


def _wrap_count(text: str, font, max_w: int) -> int:
    """计算文本换行后的行数(不实际绘制)"""
    tmp = Image.new("RGB", (10, 10))
    return len(_wrap_text(ImageDraw.Draw(tmp), text, font, max_w))


def _estimate_card_height(r: dict) -> int:
    """根据内容预估卡片高度,要和 _draw_card 内部 cur_y 保持一致。"""
    # 基础:顶部色条 + padding + 标题区 + 分隔线 + 评分区 + 分隔线 + 指标 2 行
    bars_total_h = 8 + 26 * 3       # 三条进度条占用高度
    score_block_h = max(72, bars_total_h)
    h = (
        CARD_PAD                # 顶部 padding
        + 32                    # 名字行
        + 22                    # code/类型
        + 24                    # 标题到大数字间距
        + score_block_h + 18    # 综合分块
        + 26 * 2 + 6            # 指标网格
    )
    if r.get("market_events"):
        ev_lines = sum(1 for l in r["market_events"].split("\n") if l.strip())
        h += 22 + 20 * ev_lines + 4
    reason = r["event"].get("reason", "")
    if reason and "无可用事件" not in reason and "无相关新闻" not in reason:
        n_lines = min(_wrap_count(reason, _font(14), CARD_W - 2 * CARD_PAD - 26), 3)
        h += 4 + 22 + 22 * n_lines + 8
    risks = list(r["event"].get("risks", []) or [])
    if not r["technical"].get("trend_filter_passed", True):
        risks.append("placeholder")
    if risks:
        h += 6 + 22 + 19 * min(len(risks), 3)
    # 大白话判决块:固定 ~70px (26pt 字 + padding)
    h += 16 + 26 + 28 + 4
    h += CARD_PAD  # 底部 padding
    return h


def _draw_card(img: Image.Image, x: int, y: int, r: dict, card_height: int) -> None:
    """画一只基金卡片。"""
    draw = ImageDraw.Draw(img)
    rec = r["recommendation"]
    rec_color, rec_bg, rec_label = REC_COLORS.get(rec, ("#94a3b8", "#1e293b", rec))
    tech, val, ev = r["technical"], r["valuation"], r["event"]
    total = r["total_score"]
    type_tag = TYPE_TAG.get(r.get("type", ""), "")

    inner_x = x + CARD_PAD + 8       # 给左侧竖条让 8px 空间

    # 1. 基金名
    name = r["name"]
    f_name = _font(26, bold=True)
    # 名字过长截断
    max_name_w = CARD_W - 2 * CARD_PAD - 140  # 给徽章留空间
    while _text_size(draw, name, f_name)[0] > max_name_w and len(name) > 6:
        name = name[:-2] + "…"
    name_w, name_h = _text_size(draw, name, f_name)

    # 2. 代码 + 类型标签 + 推荐徽章
    f_meta = _font(15)
    code_str = f"{r['code']}  ·  {type_tag}"

    # 画卡片外框
    draw.rounded_rectangle(
        (x, y, x + CARD_W, y + card_height),
        radius=20, fill=CARD, outline=CARD_BORDER, width=1,
    )
    # 左侧细色条(状态标识)
    draw.rounded_rectangle(
        (x, y + 16, x + 5, y + card_height - 16),
        radius=2, fill=rec_color,
    )

    cur_y = y + CARD_PAD

    # 1. 基金名
    draw.text((inner_x, cur_y), name, font=f_name, fill=TEXT)
    cur_y += name_h + 6

    # 2. code + 类型
    draw.text((inner_x, cur_y), code_str, font=f_meta, fill=TEXT_DIM)
    cur_y += 22

    # 推荐徽章(右上角)
    badge_text = rec_label
    f_badge = _font(15, bold=True)
    bw, bh = _text_size(draw, badge_text, f_badge)
    bx = x + CARD_W - CARD_PAD - bw - 24
    by = y + CARD_PAD
    draw.rounded_rectangle(
        (bx, by, bx + bw + 24, by + bh + 14),
        radius=8, fill=rec_bg, outline=rec_color, width=1,
    )
    draw.text((bx + 12, by + 7), badge_text, font=f_badge, fill=rec_color)

    cur_y += 24

    # 3. 综合分(大数字)+ 三条进度条
    f_score = _font(72, bold=True)
    score_str = f"{total:.0f}"
    sw, sh = _text_size(draw, score_str, f_score)
    draw.text((inner_x, cur_y), score_str, font=f_score, fill=rec_color)
    # 小字 /100
    f_unit = _font(18)
    draw.text((inner_x + sw + 6, cur_y + sh - 28), "/100", font=f_unit, fill=TEXT_DIM)

    # 进度条放右边
    bars_x = inner_x + 200
    bars_y = cur_y + 8
    for i, (label, score, color) in enumerate([
        ("技术", tech["score"], "#3b82f6"),
        ("估值", val["score"], "#a855f7"),
        ("事件", ev["score"], "#10b981"),
    ]):
        bar_y = bars_y + i * 26
        draw.text((bars_x, bar_y), label, font=_font(14), fill=TEXT_DIM)
        draw.text((bars_x + 350, bar_y), f"{score:.0f}", font=_font(14, bold=True), fill=TEXT)
        _draw_progress(draw, bars_x + 40, bar_y + 5, 300, 10, score / 100, color)

    # 综合分块的实际高度 = max(大字高度, 3 行进度条高度)
    bars_total_h = 8 + 26 * 3
    block_h = max(sh, bars_total_h)
    cur_y += block_h + 18

    # 4. 关键指标(网格 2x2)
    metrics = [
        ("1年分位", f"{tech['quantile_1y']*100:.0f}%"),
        ("回撤", f"{tech['drawdown_pct']:.1f}%"),
        (f"距MA60", f"{tech['ma60_dist_pct']:+.1f}%"),
        ("RSI", f"{tech['rsi_14']:.0f}"),
    ]
    col_w = (CARD_W - 2 * CARD_PAD) // 2
    for i, (label, value) in enumerate(metrics):
        col = i % 2
        row = i // 2
        mx = inner_x + col * col_w
        my = cur_y + row * 26
        f_l = _font(13)
        f_v = _font(16, bold=True)
        draw.text((mx, my + 3), label, font=f_l, fill=TEXT_FAINT)
        lw, _ = _text_size(draw, label, f_l)
        draw.text((mx + lw + 10, my), value, font=f_v, fill=TEXT)
    cur_y += 26 * 2 + 6

    # 5. 市场事件(如果有)
    if r.get("market_events"):
        # 小标题
        draw.text((inner_x, cur_y), "市场状态", font=_font(13, bold=True), fill=TEXT_DIM)
        cur_y += 22
        for line in r["market_events"].split("\n"):
            line = line.strip()
            if not line:
                continue
            # 解析头部 emoji 替换为字体支持的箭头
            marker = "·"
            color = TEXT_DIM
            content = line
            if line.startswith("📈"):
                marker, color = "▲", "#10b981"
                content = line[1:].strip()
            elif line.startswith("📉"):
                marker, color = "▼", "#ef4444"
                content = line[1:].strip()
            elif line.startswith("·"):
                content = line[1:].strip()
            draw.text((inner_x, cur_y), marker, font=_font(13, bold=True), fill=color)
            draw.text((inner_x + 22, cur_y), content, font=_font(13), fill=TEXT)
            cur_y += 20
        cur_y += 4

    # 6. AI 评语
    reason = ev.get("reason", "")
    if reason and "无可用事件" not in reason and "无相关新闻" not in reason:
        cur_y += 4
        draw.text((inner_x, cur_y), "AI 评语", font=_font(13, bold=True), fill=ACCENT)
        cur_y += 22
        # 左侧引言竖条
        bar_x0, bar_y0 = inner_x, cur_y
        f_q = _font(14)
        max_w = CARD_W - 2 * CARD_PAD - 18
        wrapped = _wrap_text(draw, reason, f_q, max_w)
        n_lines = min(len(wrapped), 3)
        draw.rectangle((bar_x0, bar_y0, bar_x0 + 3, bar_y0 + 22 * n_lines),
                       fill=ACCENT)
        for i, line in enumerate(wrapped[:3]):
            draw.text((bar_x0 + 12, bar_y0 + i * 22), line, font=f_q, fill=TEXT)
        cur_y += 22 * n_lines + 8

    # 7. 风险提示
    risks = list(ev.get("risks", []) or [])
    if not tech.get("trend_filter_passed", True):
        risks.append("短期趋势下行,反转过滤打折")
    if risks:
        cur_y += 6
        # 黄色三角图标
        tri = [(inner_x, cur_y + 14), (inner_x + 14, cur_y + 14), (inner_x + 7, cur_y + 2)]
        draw.polygon(tri, outline="#f59e0b", fill="#231507")
        draw.text((inner_x + 5, cur_y + 4), "!", font=_font(11, bold=True), fill="#f59e0b")
        draw.text((inner_x + 22, cur_y), "风险提示", font=_font(13, bold=True), fill="#f59e0b")
        cur_y += 22
        for risk in risks[:3]:
            draw.text((inner_x + 8, cur_y), "•", font=_font(13), fill="#f59e0b")
            draw.text((inner_x + 24, cur_y), risk, font=_font(13), fill=TEXT_DIM)
            cur_y += 19

    # 8. 大白话判决(最显眼)
    verdict = get_verdict(rec, r["code"])
    cur_y += 16
    # 背景色块(用 recommendation 的暗色背景)
    box_left = inner_x - 4
    box_right = x + CARD_W - CARD_PAD
    f_verdict = _font(26, bold=True)
    vw, vh = _text_size(draw, verdict, f_verdict)
    box_h = vh + 28
    draw.rounded_rectangle(
        (box_left, cur_y, box_right, cur_y + box_h),
        radius=12, fill=rec_bg, outline=rec_color, width=1,
    )
    # 居中
    text_x = box_left + (box_right - box_left - vw) // 2
    draw.text((text_x, cur_y + 14), verdict, font=f_verdict, fill=rec_color)
    cur_y += box_h + 4


def _wrap_text(
    draw: ImageDraw.ImageDraw, text: str, font, max_w: int,
) -> list[str]:
    """简单按字符宽度换行(中文按字断行)"""
    lines: list[str] = []
    cur = ""
    for ch in text:
        test = cur + ch
        w, _ = _text_size(draw, test, font)
        if w > max_w and cur:
            lines.append(cur)
            cur = ch
        else:
            cur = test
    if cur:
        lines.append(cur)
    return lines


# ---------------- 主入口 ----------------
W = 816
HEADER_H = 110
FOOTER_H = 50
GAP = 20


def render_dashboard(results: list[dict], output_path: str | Path) -> Path:
    """生成日报 Dashboard PNG,返回输出路径"""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    card_heights = [_estimate_card_height(r) for r in results]
    total_h = HEADER_H + sum(card_heights) + GAP * len(results) + FOOTER_H

    img = Image.new("RGB", (W, total_h), BG)
    draw = ImageDraw.Draw(img)

    # ---- Header ----
    today = date.today()
    weekday = ["一", "二", "三", "四", "五", "六", "日"][today.weekday()]
    # 左侧蓝色装饰条
    draw.rectangle((28, 36, 34, 70), fill=ACCENT)
    draw.text((48, 28), "基金日报", font=_font(32, bold=True), fill=TEXT)
    draw.text((48, 72), f"{today.strftime('%Y-%m-%d')}  周{weekday}",
              font=_font(15), fill=TEXT_DIM)

    # 右上角:基金数量
    f_meta = _font(13)
    info = f"监控 {len(results)} 只"
    iw, _ = _text_size(draw, info, f_meta)
    draw.text((W - 28 - iw, 80), info, font=f_meta, fill=TEXT_FAINT)

    # ---- 每张卡片 ----
    cur_y = HEADER_H
    for r, ch in zip(results, card_heights):
        _draw_card(img, (W - CARD_W) // 2, cur_y, r, ch)
        cur_y += ch + GAP

    # ---- Footer ----
    footer = "本报告仅供参考,不构成投资建议"
    fw, _ = _text_size(draw, footer, f_meta)
    draw.text(((W - fw) // 2, total_h - FOOTER_H + 14), footer,
              font=f_meta, fill=TEXT_FAINT)

    img.save(output_path, format="PNG", optimize=True)
    return output_path
