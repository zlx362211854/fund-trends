"""人话版判决 — 给每个评分等级配一组口语化结论。
每天用 (日期 + 基金代码) 当 seed 抽一句,同一天保持一致,跨天变着花样说。
"""
from __future__ import annotations

import random
from datetime import date

# 注:这些文案会以"大字"画到图片上,字体不含 emoji,所以纯文本
# (Markdown 推送的版本可以带 emoji,在 daily.py 里另外加)

# 强烈加仓 85-100
STRONG_BUY = [
    "捡钱了,现在不上车更待何时!",
    "梭哈警告,这就是机会",
    "闭眼买,别想了",
    "错过这村就没这店",
    "千载难逢,该出手了",
]

# 可加仓 70-84
BUY = [
    "上车正合适,可以加点",
    "时机不错,小试牛刀",
    "稳稳的小幸福,慢慢加",
    "不亏,值得操作",
    "上车吧,别想太多",
]

# 中性 50-69(可定投)
NEUTRAL = [
    "佛系定投得了",
    "买不买都行,看心情",
    "不上不下,继续定投",
    "平稳态势,定投最稳",
    "想买就买点,别梭哈",
]

# 观望 30-49
WATCH = [
    "再等等,别急着上车",
    "稳住,我们能赢",
    "黄灯亮起,踩个刹车",
    "看戏就行,别下场",
    "搬好小板凳,坐等机会",
]

# 暂不加仓 0-29
AVOID = [
    "现在买就是大怨种",
    "高位接盘?三思啊兄弟",
    "刀尖上跳舞,别玩",
    "等等吧,别接飞刀",
    "韭菜请绕道",
    "别冲,等回调",
]

POOL = {
    "strong_buy": STRONG_BUY,
    "buy":        BUY,
    "neutral":    NEUTRAL,
    "watch":      WATCH,
    "avoid":      AVOID,
}


def get_verdict(recommendation: str, fund_code: str = "", seed_date: date | None = None) -> str:
    """根据评分等级 + 日期 + 基金代码,确定性地抽一句判决。
    同一只基金同一天结果固定,跨天变化。
    """
    pool = POOL.get(recommendation, NEUTRAL)
    seed_date = seed_date or date.today()
    seed = f"{seed_date.isoformat()}-{fund_code}"
    rng = random.Random(seed)
    return rng.choice(pool)
