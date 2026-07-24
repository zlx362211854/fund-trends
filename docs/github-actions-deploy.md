# GitHub Actions 免费定时运行

这个方式不需要服务器。GitHub 会按定时任务拉起一台临时机器，运行现有 Python 脚本，生成报告后通过 Server酱推送。

## 适合什么场景

- 个人自用，每天/每周定时推送。
- 基金数量较少，建议不超过 `5` 只。
- 可以接受 GitHub Actions 偶尔因公开数据接口波动而失败，下次自动重试。

不适合高可靠商业服务。数据仍依赖 AKShare 和第三方公开接口。

## 需要准备的 GitHub Secrets

进入 GitHub 仓库：

`Settings` -> `Secrets and variables` -> `Actions` -> `New repository secret`

添加下面几个：

| Secret 名称 | 是否必填 | 内容 |
| --- | --- | --- |
| `CONFIG_YAML` | 必填 | 你的整个 `config.yaml` 文件内容 |
| `DEEPSEEK_API_KEY` | 必填 | DeepSeek API Key |
| `SERVERCHAN_KEY` | 必填 | Server酱 SendKey |
| `IMGBB_API_KEY` | 可选 | ImgBB API Key；不填则只推文字和本地生成记录 |

`CONFIG_YAML` 里不要填写真实 API Key，保持类似下面这样即可：

```yaml
funds:
  - code: "021000"
    name: "南方纳斯达克100指数发起(DQII)I"
    type: qdii_index

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

quality:
  max_nav_age_days: 7
  max_market_age_days: 7
  max_holdings_age_days: 180
  max_news_refresh_age_days: 3
  min_nav_rows: 60

llm:
  provider: deepseek
  base_url: "https://api.deepseek.com/v1"
  model: "deepseek-v4-pro"

schedule:
  daily_time: "08:17"
  weekly_time: "17:23"
  weekly_day: "friday"

database:
  path: "data/fund_trends.db"

logging:
  level: INFO
  path: "logs/fund_trends.log"
```

## 定时规则

GitHub Actions 使用 UTC 时间。当前工作流已经换算好，并刻意避开整点。为了降低 GitHub 定时任务漏触发的影响，日报和周报都会安排多个备份触发点；脚本会检查 `push_history`，当天已经成功推送过就自动跳过。

- 北京时间工作日 `08:17 / 08:37 / 08:57 / 09:17`：尝试运行日报
- 北京时间周五 `17:23 / 17:43 / 18:03`：尝试运行周报

对应文件是：

`.github/workflows/fund-trends.yml`

## 第一次手动试跑

进入 GitHub 仓库：

`Actions` -> `Fund Trends` -> `Run workflow`

推荐第一次选择：

- `report_type`: `daily`
- `force_backfill`: `true`

第一次会先回填历史数据，然后发送一份日报。后续定时运行会复用缓存里的数据库。

如果只想提前把历史数据跑一遍，不推送报告：

- `report_type`: `backfill`
- `force_backfill`: `true`

## 数据库怎么保存

GitHub Actions 每次运行都是临时环境，所以工作流使用 `actions/cache` 保存：

- `data/fund_trends.db`
- `data/reports`
- `logs`

每次运行也会上传一个 artifact，保留 `14` 天，方便你下载排查。

注意：cache 不是正式数据库托管服务，偶尔可能丢缓存。丢了也不会损坏程序，只是下次会自动重新回填历史数据，历史评分样本会从新数据库开始累计。

## 从旧服务器迁移数据库

如果服务器还没完全到期，想保留之前的历史评分，可以先在服务器下载：

```bash
scp root@你的服务器IP:/projects/fund-trends/data/fund_trends.db ./fund_trends.db
```

然后在 GitHub Actions 第一次跑完后，也可以从 artifact 里下载新的数据库作备份。

如果不迁移旧数据库，也能正常运行，只是历史评分评价会重新积累。

## 常见问题

### 需要服务器吗？

不需要。GitHub Actions 会临时运行。

### 要不要部署脚本 `bash deploy/install.sh`？

不需要。那个脚本是给 VPS 用的。

### 改配置后怎么办？

修改 GitHub Secret `CONFIG_YAML`，下次运行自动生效。

### 可以马上发一次报告吗？

可以。在 `Actions` 页面手动运行 `Fund Trends`，选择 `daily`。

### 为什么偶尔失败？

大概率是 AKShare 或上游公开接口临时不可用。手动重新运行一次即可。
