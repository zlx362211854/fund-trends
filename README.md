# 基金双周期观察工具

面向个人研究的基金观察与验证工具。系统按工作日刷新基金、市场、指数估值和新闻数据，分别生成“长期持有条件分”和“当前投入时机分”，并持续评价历史记录相对基准的5/20/60日表现。

两项分数都是规则化研究观察，不表示预期收益、上涨概率或操作指令。

## 核心能力

- **双周期评分**：长期条件和当前时机独立计算，不再混成含义不清的总分。
- **真实指数估值**：QDII使用纳斯达克100前瞻PE及其近10年历史分位，不使用价格分位冒充估值。
- **趋势友好**：稳定上涨和正常创新高不会被机械扣分；只有显著偏离自身趋势时才降低时机分。
- **企稳确认**：深度回撤只有配合短期跌势减弱和MA20企稳才提高时机分。
- **数据可信度**：分别显示净值、指数、汇率、估值、持仓、新闻和AI事件状态。
- **事件审计**：保存LLM模型、分析状态、新闻标题、来源、时间和URL，但LLM不参与数字评分。
- **前瞻评价**：记录满5/20/60个基金交易日后，分别评价两个评分维度的相对基准表现。
- **版本隔离**：`observation-v1`历史保持不变，`observation-v2`不会与旧分数混算。

## 分数含义

### 长期持有条件分

| 因子 | 权重 | 含义 |
| --- | ---: | --- |
| 真实指数估值 | 40% | 前瞻PE当前值及近10年历史分位 |
| 长期趋势 | 30% | MA200斜率、近6个月和12个月趋势 |
| 风险稳定性 | 20% | 近3年最大回撤、年化波动率 |
| 跟踪质量 | 10% | 基金净值与人民币口径基准的一致程度 |

真实估值是必要输入。估值缺失、超过7个自然日或历史少于60个样本时，长期分显示“暂不可评估”，不会退回净值或指数价格分位。

当前版本为纳斯达克100 QDII接入前瞻PE。国内指数和主动基金在没有经过验证的真实估值或基本面输入前，长期分可能暂不可评估。

### 当前投入时机分

| 因子 | 权重 | 含义 |
| --- | ---: | --- |
| 趋势状态 | 30% | 价格相对MA200及MA200斜率 |
| 趋势偏离度 | 30% | 相对MA60/MA200的波动率标准化距离 |
| 回撤与企稳 | 25% | 当前回撤、MA20斜率、近5/20日变化 |
| 短期温度 | 15% | RSI14及短期收益 |

时机分至少需要约220条价格记录。稳定上升趋势不会因“一年高分位”扣分；突然大幅偏离趋势会降低分数；仍在加速下跌时不会仅因回撤较深获得高分。

统一等级：

- `80-100`：条件较强
- `60-79`：条件偏强
- `40-59`：条件中性
- `20-39`：条件偏弱
- `0-19`：条件较弱
- 核心数据不足：暂不可评估

## 估值数据与缓存

纳斯达克100前瞻PE来自 [History of Market NDX Forward PE JSON](https://historyofmarket.com/api/ndx/forward-pe.json)，其页面标注前瞻PE为Bloomberg BEst月频数据。系统保存来源、指标、数值、数据日期、样本数和抓取时间。

USD/CNY使用[欧洲央行官方日频参考汇率](https://data.ecb.europa.eu/help/api/data)：一次请求获取人民币/欧元和美元/欧元，再用两者相除得到美元兑人民币。该口径用于研究观察，不代表可成交报价。

- 每个基准每天最多请求一次。
- 多只QDII基金共享同一份估值缓存。
- 刷新失败时可使用不超过7个自然日的最近缓存，并明确显示缓存日期。
- 返回空数据、异常字段、非正数或非法日期时拒绝写入有效缓存。
- 外部接口不可用不会阻断净值刷新和当前时机分计算。

## 数据质量

默认最大自然日时效：

| 数据 | 最大时效 |
| --- | ---: |
| 基金净值 | 7天 |
| 市场数据 | 7天 |
| 指数估值 | 7天 |
| 基金持仓 | 180天 |
| 新闻刷新 | 3天 |

日报不再笼统显示“市场未知”，而是逐项标记 `正常 / 缓存可用 / 过期 / 缺失 / 失败 / 样本不足`。一项分数不可评估不会阻止另一项分数展示。

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

数据库初始化包含幂等迁移，升级时不需要手工修改SQLite表结构。

## 配置

```yaml
scoring:
  version: observation-v2
  long_term_weights:
    valuation: 0.40
    trend: 0.30
    risk: 0.20
    tracking: 0.10
  timing_weights:
    trend: 0.30
    deviation: 0.30
    stabilization: 0.25
    temperature: 0.15
  max_valuation_age_days: 7
  min_valuation_samples: 60
```

每组权重必须合计为 `1.0`。修改公式或权重时必须更新评分版本，避免不同规则混入同一统计分组。

## 结果评价

```bash
python scripts/run_backtest.py
```

基准口径：

- 国内主动和国内指数基金：沪深300。
- QDII指数基金：纳斯达克100人民币收益，即指数变化与USD/CNY变化的乘积。

周报按评分版本、评分维度、等级和期限展示样本数、平均/中位超额收益和跑赢比例。样本少于30条时只标记“证据不足”，不据此调整权重或宣称规则有效。

## 常用命令

```bash
# 运行测试
python -m pytest -q

# 源码编译检查
python -m compileall -q src scripts

# 查看最近双评分记录
sqlite3 data/fund_trends.db \
  "SELECT score_date, code, long_term_score, timing_score, quality_status, scoring_version FROM daily_scores ORDER BY score_date DESC LIMIT 20"

# 查看v2到期结果
sqlite3 data/fund_trends.db \
  "SELECT code, signal_date, dimension, horizon_days, excess_return_pct, beat_benchmark FROM score_outcomes_v2 ORDER BY signal_date DESC"
```

## 部署与资源

```bash
bash deploy/install.sh
```

默认cron任务为工作日8:00生成日报、周五17:00生成周报。服务器为UTC时，部署脚本会换算为对应北京时间。

实现只使用现有pandas、numpy和SQLite。约5只基金共享行情和估值数据，单只基金最多计算约3年序列，复杂度为 `O(n)`；每日新增开销主要是一条轻量估值HTTP请求和一次SQLite批量写入，不增加AI调用，适合1核1GB服务器。

也可以不使用服务器，改用 GitHub Actions 免费定时运行。仓库已内置 `.github/workflows/fund-trends.yml`，配置方法见 [docs/github-actions-deploy.md](docs/github-actions-deploy.md)。

## 局限

- 数据依赖AKShare及第三方公开接口，可能延迟、不可用或改变字段。
- 第三方纳指估值数据并非交易所授权数据终端，系统会完整显示来源和日期。
- 主动基金尚缺少可验证的持仓加权基本面模型，不能仅凭市场指数估值评价其长期条件。
- LLM事件分析可能出错，因此只作为独立说明，不进入数字评分。
- 工具不包含个人风险承受能力、资金期限、仓位和组合约束，不能作为面向他人的投资顾问系统。
