"""按 fund_type 配置事件关键词包。
用于从财经新闻中筛选与该基金相关的内容。
"""
from __future__ import annotations

from src.config import FundType


# QDII 纳指相关:美联储 / 美股 / 七巨头 / 中美关系
QDII_NASDAQ_KEYWORDS = [
    # 美股大盘 / 指数
    "纳指", "纳斯达克", "纳斯达克100", "标普", "标普500", "道指", "道琼斯", "美股",
    "罗素2000", "VIX",
    # 美联储 / 货币政策
    "美联储", "鲍威尔", "FOMC", "议息", "降息", "加息", "联邦基金利率", "缩表", "扩表",
    "通胀", "CPI", "PCE", "非农", "失业率", "PMI", "ISM",
    # 七巨头 + 主要科技股
    "英伟达", "NVIDIA", "Nvidia",
    "微软", "Microsoft",
    "苹果", "Apple",
    "谷歌", "Google", "Alphabet",
    "亚马逊", "Amazon",
    "Meta", "脸书", "Facebook",
    "特斯拉", "Tesla", "马斯克",
    "博通", "Broadcom",
    "台积电", "TSMC",
    "AMD", "英特尔", "Intel",
    "OpenAI", "ChatGPT", "Claude", "Anthropic",
    # 中美 / 关税 / 出口管制
    "中美", "贸易战", "关税", "出口管制", "实体清单", "芯片法案", "半导体出口",
    # 货币 / 汇率
    "美元", "美元指数", "DXY", "人民币汇率",
    # 行业
    "AI", "人工智能", "芯片", "半导体", "云计算", "数据中心",
]

# 国内主动基金:行业 + 政策类
DOMESTIC_BASE_KEYWORDS = [
    "降息", "降准", "加息", "央行", "货币政策", "财政政策", "降准",
    "国常会", "政治局会议", "中央经济工作会议",
    "GDP", "CPI", "PPI", "社融", "M2", "PMI", "工业增加值",
    "A股", "沪指", "深指", "创业板", "科创板", "北向资金", "外资",
]

# 行业关键词(中文)— 自动 + 持仓股票名 之外的兜底
DOMESTIC_ACTIVE_INDUSTRY = [
    "白酒", "啤酒", "食品饮料", "消费",
    "医药", "生物医药", "创新药", "集采", "医保",
    "新能源", "电池", "锂电", "光伏", "风电",
    "半导体", "芯片", "集成电路",
    "金融", "银行", "保险", "券商",
    "地产", "房地产",
    "AI", "人工智能", "算力",
    "军工", "国防",
]


def keywords_for_fund(fund_type: FundType, fund_name: str, holdings_names: list[str]) -> list[str]:
    """根据基金类型和持仓,组合出关键词列表"""
    base: list[str] = [fund_name]

    if fund_type == "qdii_index":
        # 纳指 QDII 用美股关键词包,持仓(美股名)+ 中文映射兜底
        base += QDII_NASDAQ_KEYWORDS
        # 持仓里如果有中文名也加上
        base += [n for n in holdings_names if n]
        return _dedup(base)

    if fund_type == "domestic_index":
        base += DOMESTIC_BASE_KEYWORDS
        base += DOMESTIC_ACTIVE_INDUSTRY
        base += holdings_names
        return _dedup(base)

    # domestic_active
    base += DOMESTIC_BASE_KEYWORDS
    base += DOMESTIC_ACTIVE_INDUSTRY
    base += holdings_names
    return _dedup(base)


def _dedup(items: list[str]) -> list[str]:
    seen = set()
    out: list[str] = []
    for x in items:
        if x and len(x) >= 2 and x not in seen:
            seen.add(x)
            out.append(x)
    return out
