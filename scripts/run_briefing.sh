#!/bin/bash
# 新闻简报每日定时任务 — wrapper 脚本
# 由 crontab 调用，加载 SMTP 环境变量后执行 main.py

set -e

# ── SMTP 邮件配置 ──────────────────────────────────
source ~/.openclaw/smtp_env

# ── 路径 ──────────────────────────────────────────
PROJECT_DIR="/Users/idf/.openclaw/workspace/skills/news-briefing"
PYTHON="$PROJECT_DIR/venv/bin/python3"
SCRIPT="$PROJECT_DIR/scripts/main.py"
LOG_DIR="$PROJECT_DIR/output"
mkdir -p "$LOG_DIR"

# ── 基准日: 昨天（精确锁定，不混入今日早间文章）──
YESTERDAY=$(date -v-1d +%Y-%m-%d)

# ── 清理 30 天前的旧日志 ─────────────────────────
find "$LOG_DIR/logs" -name "briefing_*.log" -mtime +30 -delete 2>/dev/null

# ── 执行 ──────────────────────────────────────────
cd "$PROJECT_DIR/scripts"
exec "$PYTHON" "$SCRIPT" --days 1 --ref-date "$YESTERDAY" --send-email 2>&1
