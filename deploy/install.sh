#!/usr/bin/env bash
# 一键部署脚本 — 在服务器上执行
# 用法:
#   cd /path/to/fund-trends
#   bash deploy/install.sh

set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

echo "============================================"
echo "  基金趋势 - 一键部署"
echo "  项目目录: $PROJECT_DIR"
echo "============================================"

# ---------- 1. 系统依赖检查 ----------
echo "[1/6] 检查系统依赖..."
if ! command -v python3 &>/dev/null; then
    echo "❌ 未找到 python3,请先安装(apt install python3 python3-venv 或 yum install python3)"
    exit 1
fi
PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "    Python 版本: $PY_VER"

if ! python3 -c 'import venv' &>/dev/null; then
    echo "❌ python3-venv 未安装。Ubuntu/Debian: sudo apt install python3-venv"
    exit 1
fi

# ---------- 2. 虚拟环境 ----------
echo "[2/6] 创建虚拟环境..."
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi
source .venv/bin/activate
pip install --upgrade pip -q

# ---------- 3. 安装依赖 ----------
echo "[3/6] 安装 Python 依赖..."
# 默认走清华镜像加速;国外服务器可改用 pip install -r requirements.txt
PIP_INDEX="${PIP_INDEX:-https://pypi.tuna.tsinghua.edu.cn/simple}"
pip install -r requirements.txt -i "$PIP_INDEX" -q

# ---------- 4. 配置检查 ----------
echo "[4/6] 配置检查..."
if [ ! -f "config.yaml" ]; then
    echo "    config.yaml 不存在,复制模板..."
    cp config.yaml.example config.yaml
    echo "    ⚠️ 请编辑 config.yaml 填入你的基金列表"
fi
if [ ! -f ".env" ]; then
    echo "    .env 不存在,复制模板..."
    cp .env.example .env
    echo "    ⚠️ 请编辑 .env 填入 DEEPSEEK_API_KEY / SERVERCHAN_KEY / IMGBB_API_KEY"
    echo ""
    echo "    填好后再次运行 bash deploy/install.sh"
    exit 0
fi

# 检查 .env 中关键变量
source <(grep -E '^(DEEPSEEK_API_KEY|SERVERCHAN_KEY|IMGBB_API_KEY)=' .env | sed 's/^/export /')
missing=()
[ -z "$DEEPSEEK_API_KEY" ] && missing+=("DEEPSEEK_API_KEY")
[ -z "$SERVERCHAN_KEY" ] && missing+=("SERVERCHAN_KEY")
if [ ${#missing[@]} -gt 0 ]; then
    echo "❌ .env 缺少必填项: ${missing[*]}"
    exit 1
fi
[ -z "$IMGBB_API_KEY" ] && echo "    ⚠️ 未配置 IMGBB_API_KEY,推送将无图片"

# ---------- 5. 初始化 + 回填 ----------
echo "[5/6] 初始化数据库..."
python scripts/init_db.py

if [ -z "$SKIP_BACKFILL" ]; then
    echo "    回填历史数据(首次约 1-3 分钟)..."
    python scripts/backfill.py
else
    echo "    SKIP_BACKFILL=1,跳过回填"
fi

# ---------- 6. cron 配置 ----------
echo "[6/6] 配置 cron..."
CRON_TAG="# fund-trends"
TMP_CRON=$(mktemp)
crontab -l 2>/dev/null | grep -v "$CRON_TAG" > "$TMP_CRON" || true

# 时区检测
TZ_NAME=$(timedatectl show -p Timezone --value 2>/dev/null || cat /etc/timezone 2>/dev/null || echo "UTC")
echo "    服务器时区: $TZ_NAME"

if [ "$TZ_NAME" = "Asia/Shanghai" ] || [ "$TZ_NAME" = "PRC" ]; then
    # 已经是北京时间
    DAILY_CRON="0 8 * * 1-5"
    WEEKLY_CRON="0 17 * * 5"
    echo "    使用本地时间(北京时间)调度"
else
    # 假定 UTC,北京时间 = UTC+8
    DAILY_CRON="0 0 * * 1-5"     # UTC 00:00 = 北京 08:00
    WEEKLY_CRON="0 9 * * 5"      # UTC 09:00 = 北京 17:00
    echo "    服务器时区非北京,使用 UTC 时间调度(对应北京 08:00 / 17:00)"
    echo "    提示:运行 'sudo timedatectl set-timezone Asia/Shanghai' 可改为本地时间"
fi

cat >> "$TMP_CRON" <<EOF
$DAILY_CRON  cd $PROJECT_DIR && $PROJECT_DIR/.venv/bin/python scripts/run_daily.py  >> $PROJECT_DIR/logs/cron.log 2>&1 $CRON_TAG
$WEEKLY_CRON cd $PROJECT_DIR && $PROJECT_DIR/.venv/bin/python scripts/run_weekly.py >> $PROJECT_DIR/logs/cron.log 2>&1 $CRON_TAG
EOF

crontab "$TMP_CRON"
rm "$TMP_CRON"
mkdir -p logs

echo "    已安装 cron:"
crontab -l | grep "$CRON_TAG"

echo ""
echo "============================================"
echo "  ✅ 部署完成"
echo "============================================"
echo ""
echo "立即测试推送:"
echo "    bash deploy/test.sh"
echo ""
echo "查看日志:"
echo "    tail -f logs/cron.log"
echo ""
echo "下次更新代码后,只需要:"
echo "    cd $PROJECT_DIR && git pull && bash deploy/install.sh"
