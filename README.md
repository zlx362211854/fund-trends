# 基金趋势监控

每天 8:00 微信推送基金加仓建议,每周五 17:00 推送周报。基于 akshare + DeepSeek + Server酱,部署在 Vultr。

## 功能

- **日报**:每个交易日 8:00 推送 5 只以内基金的加仓吸引力打分(0-100)
- **周报**:每周五 17:00 推送本周打分趋势 + 关键事件复盘
- **打分维度**:技术面 40%(分位/回撤/MA/RSI)+ 估值面 30%(分位 + 汇率因子)+ 事件面 30%(LLM 分析持仓相关新闻)
- **基金类型**:国内主动 / 国内指数 / 纳指 QDII(场外)

## 项目结构

```
fund-trends/
├── config.yaml.example     # 配置模板
├── requirements.txt
├── src/
│   ├── config.py           # 配置加载
│   ├── db.py               # SQLite schema
│   ├── data/               # akshare 抓数据
│   ├── scoring/            # 技术 / 估值 / 事件面打分
│   ├── agents/             # Agent 编排(pipeline 或 openai-agents SDK)
│   ├── report/             # 日报 / 周报模板
│   └── push/               # Server酱
├── scripts/
│   ├── init_db.py          # 初始化 DB
│   ├── backfill.py         # 首次回填历史净值
│   ├── run_daily.py        # 日报入口
│   └── run_weekly.py       # 周报入口
└── data/fund_trends.db     # SQLite(gitignored)
```

## 快速开始(本地)

```bash
# 1. 准备环境
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. 配置
cp config.yaml.example config.yaml
# 编辑 config.yaml:填基金代码、DeepSeek key、Server酱 key

# 3. 初始化数据库 + 回填历史数据(首次,耗时 1-3 分钟)
python scripts/init_db.py
python scripts/backfill.py

# 4. 手动跑一次日报(测试)
python scripts/run_daily.py
```

如果一切正常,你的微信会收到一份日报。

## 部署到 Vultr

```bash
# 在 Vultr 服务器上
git clone <repo> ~/fund-trends
cd ~/fund-trends
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp config.yaml.example config.yaml
vim config.yaml                          # 填配置
python scripts/init_db.py
python scripts/backfill.py
```

### 配 cron

```bash
crontab -e
```

加入以下两行(注意时区:Vultr 默认 UTC,北京时间 8:00 = UTC 00:00):

```cron
# 每个交易日早 8:00(北京时间)推日报
0 0 * * 1-5  cd /root/fund-trends && /root/fund-trends/.venv/bin/python scripts/run_daily.py >> logs/cron.log 2>&1

# 每周五 17:00(北京时间)推周报
0 9 * * 5  cd /root/fund-trends && /root/fund-trends/.venv/bin/python scripts/run_weekly.py >> logs/cron.log 2>&1
```

如果服务器是本地时区(`timedatectl set-timezone Asia/Shanghai`):

```cron
0 8  * * 1-5  cd /root/fund-trends && .venv/bin/python scripts/run_daily.py >> logs/cron.log 2>&1
0 17 * * 5    cd /root/fund-trends && .venv/bin/python scripts/run_weekly.py >> logs/cron.log 2>&1
```

## 切换到 openai-agents SDK 模式

默认 `scripts/run_daily.py` 走直接调用(`src/agents/pipeline.py`),稳定可靠。

如果想让 LLM 自主决策"先查哪个、要不要重试",改 `scripts/run_daily.py`:

```python
# 把
from src.agents.pipeline import run_pipeline
results = run_pipeline(cfg)
# 改成
from src.agents.sdk_agents import run_with_sdk
results = run_with_sdk(cfg)
```

## 加新基金

只改 `config.yaml`,在 `funds` 列表加一行,然后:

```bash
python scripts/backfill.py    # 回填新基金的历史数据
```

下次 cron 触发就会包含新基金。

## 日志和调试

- 应用日志:`logs/fund_trends.log`
- cron 日志:`logs/cron.log`
- 数据库:`data/fund_trends.db`(可用 SQLite 工具直接看)

查最近一次打分:

```bash
sqlite3 data/fund_trends.db \
  "SELECT score_date, code, total_score, recommendation FROM daily_scores ORDER BY score_date DESC LIMIT 20"
```

## 风险提示

本工具仅供个人参考,不构成投资建议。LLM 输出可能有误,所有决策请独立判断。

## 后续路线图

- [ ] 持仓股 PE 加权(目前估值面用净值分位代理)
- [ ] 财联社电报实时新闻
- [ ] 信号准确率统计(运行 4 周后启用)
- [ ] 量化回测模块
