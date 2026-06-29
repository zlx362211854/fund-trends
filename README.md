# 基金观察工具

面向个人研究的基金观察与验证工具。系统按工作日刷新基金、市场和新闻数据，生成可审计的观察分，并持续评价历史观察记录相对基准的5/20/60日表现。

观察分仅用于研究排序，不是收益预测、上涨概率或操作指令。

## 核心能力

- **观察日报**：技术、估值代理、事件三个维度的 `0-100` 观察分。
- **数据可信度**：明确区分 `数据可靠`、`数据降级` 和 `不可评分`。
- **事件审计**：保存LLM模型、分析状态、新闻标题、来源、时间和URL。
- **前瞻评价**：真实观察记录满5/20/60个基金交易日后，计算相对基准超额收益。
- **版本隔离**：每条记录带评分版本，规则变化后的结果不会与旧版本混算。
- **日报与周报**：支持Server酱文字推送和Pillow图片看板。

## 分数含义

默认观察分仍使用原始权重，便于连续比较：

- 技术：40%，包含近1年分位、MA60距离、回撤、RSI和短期趋势过滤。
- 估值代理：30%。国内主动基金使用净值分位；国内指数使用指数价格分位；QDII使用纳指价格分位和汇率因子。
- 事件：30%，由LLM基于已发生的市场事件与相关新闻分析。

五档等级为：`高关注 / 较高关注 / 中性观察 / 谨慎观察 / 低关注`。等级只反映当前规则的排序结果。

当前“估值代理”不是真实PE/PB估值。真实估值模型属于后续阶段。

## 数据质量

默认阈值：

| 数据 | 最大自然日时效 |
| --- | ---: |
| 基金净值 | 7天 |
| 市场数据 | 7天 |
| 基金持仓 | 180天 |
| 新闻刷新 | 3天 |

净值少于60条或严重过期时，系统不生成数值观察分。可选数据或LLM不可用时，系统按剩余可用维度重新归一化权重，并明确显示“数据降级”及原因。

## 快速开始

建议使用Python 3.11至3.13。

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp config.yaml.example config.yaml
# 在 .env 中设置 DEEPSEEK_API_KEY 和 SERVERCHAN_KEY

python scripts/init_db.py
python scripts/backfill.py
python scripts/run_daily.py
```

数据库初始化包含幂等迁移。已有部署升级后不需要手工修改SQLite表结构。

## 结果评价

手动更新所有已到期结果：

```bash
python scripts/run_backtest.py
```

基准口径：

- 国内主动和国内指数基金：沪深300。
- QDII指数基金：纳指人民币收益，即纳指区间变化与USD/CNY区间变化的乘积。

周报按评分版本、观察等级和期限展示样本数、平均/中位超额收益和跑赢比例。样本少于30条时只标记“证据不足”，不据此调整权重或宣称规则有效。

这是前瞻结果评价，不会使用未来数据重建历史事件分。

## 配置

```yaml
scoring:
  version: observation-v1
  weights:
    technical: 0.4
    valuation: 0.3
    event: 0.3

quality:
  max_nav_age_days: 7
  max_market_age_days: 7
  max_holdings_age_days: 180
  max_news_refresh_age_days: 3
  min_nav_rows: 60
```

改变评分公式或权重后必须更新 `scoring.version`，避免不同规则的结果混在同一统计分组。

## 常用命令

```bash
# 运行测试
pytest -q

# 源码编译检查
python -m compileall -q src scripts

# 查看最近观察记录
sqlite3 data/fund_trends.db \
  "SELECT score_date, code, total_score, observation_level, quality_status, scoring_version FROM daily_scores ORDER BY score_date DESC LIMIT 20"

# 查看已到期结果
sqlite3 data/fund_trends.db \
  "SELECT code, signal_date, horizon_days, excess_return_pct, beat_benchmark FROM signal_outcomes ORDER BY signal_date DESC"
```

## 部署

```bash
bash deploy/install.sh
```

默认cron任务：工作日8:00生成日报，周五17:00生成周报。服务器为UTC时，部署脚本会换算为对应的北京时间。

## 局限

- 数据依赖akshare及其上游公开接口，可能延迟或改变字段。
- 估值维度目前是价格/净值分位代理，不是基本面估值。
- LLM事件分析可能出错；失败会降级并退出事件维度，但有效输出也不等同于事实核验。
- 当前基金列表由用户配置，结果不代表完整市场样本。
- 工具不包含个人风险承受能力、资金期限、仓位和组合约束。

## 后续路线

- 在同版本到期样本达到统计门槛后评估因子和权重。
- 接入真实PE/PB、持仓加权估值与风格暴露。
- 增加组合风险预算和相关性分析。
- 增强新闻来源质量、去重和冲突证据处理。
