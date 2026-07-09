#!/bin/bash
# 新闻简报每日定时任务 — wrapper 脚本
# 由 crontab 调用，加载 SMTP 环境变量后执行 main.py
# 自动识别工作日/非工作日，节假日后的第一个工作日自动扩大覆盖窗口
#
# 工作日判定：周一至周五 + workdays.txt 中列出的补班日
# 非工作日：  周六/周日 + holidays.txt 中的法定节假日
# 补班日优先级高于节假日（workdays.txt 中的日期视为工作日，无论周末与否）

set -e

# ── 配置 ──────────────────────────────────────────
source ~/.openclaw/smtp_env

PROJECT_DIR="/Users/idf/.openclaw/workspace/skills/news-briefing"
PYTHON="$PROJECT_DIR/venv/bin/python3"
SCRIPT="$PROJECT_DIR/scripts/main.py"
LOG_DIR="$PROJECT_DIR/output"
HOLIDAYS_FILE="$PROJECT_DIR/state/holidays.txt"
WORKDAYS_FILE="$PROJECT_DIR/state/workdays.txt"
mkdir -p "$LOG_DIR"

# ── 日期 ──────────────────────────────────────────
TODAY=$(date +%Y-%m-%d)
YESTERDAY=$(date -v-1d +%Y-%m-%d)

# ── 辅助函数 ──────────────────────────────────────

# 判断是否为补班日（调休后变成工作日的周末/假期）
is_workday_override() {
    local d=$1
    [ -f "$WORKDAYS_FILE" ] && grep -q "^${d}$" "$WORKDAYS_FILE" 2>/dev/null
}

# 判断是否在节假日列表中
is_holiday() {
    local d=$1
    [ -f "$HOLIDAYS_FILE" ] && grep -q "^${d}$" "$HOLIDAYS_FILE" 2>/dev/null
}

# 判断是否为非工作日
# 判定顺序：补班日 > 周末 > 节假日
# 返回值: 0 = 非工作日, 1 = 工作日
is_off_day() {
    local d=$1
    # 补班日强制视为工作日
    is_workday_override "$d" && return 1
    local dow
    dow=$(date -j -f "%Y-%m-%d" "$d" "+%u" 2>/dev/null)
    # 周六(6) 或 周日(7)
    if [ "$dow" -ge 6 ]; then
        return 0
    fi
    # 法定节假日
    is_holiday "$d" && return 0
    return 1
}

# ── 今天是非工作日则跳过 ────────────────────────
if is_off_day "$TODAY"; then
    echo "[$(date '+%H:%M:%S')] $(date '+%Y-%m-%d') 是非工作日（周末或节假日），跳过简报"
    exit 0
fi

# ── 计算智能覆盖窗口 ──────────────────────────────
# 规则：
#   - 昨天是工作日 → 只覆盖昨天 (days=1)
#   - 昨天是非工作日 → 往前数，覆盖昨天+所有连续非工作日+最后一个工作日
#
# 示例：
#   周二~周五运行（昨天=工作日）→ days=1
#   周一运行（昨天=周日,前天=周六,大前天=周五）→ days=3，覆盖周五六日
#   节后首日（昨天=假期...→工作日）→ days=N，覆盖假期+最后工作日

DAYS=1

if is_off_day "$YESTERDAY"; then
    # 昨天是非工作日：从昨天开始往前数连续的非工作日，再纳入最后的工作日
    DAYS=0
    CURSOR="$YESTERDAY"
    while is_off_day "$CURSOR"; do
        DAYS=$((DAYS + 1))
        CURSOR=$(date -j -f "%Y-%m-%d" -v-1d "$CURSOR" "+%Y-%m-%d")
    done
    # CURSOR 现在是紧邻的最后一个工作日 —— 它还没被覆盖，纳入窗口
    DAYS=$((DAYS + 1))
fi

WINDOW_START=$(date -j -f "%Y-%m-%d" -v-${DAYS}d -v+1d "$YESTERDAY" "+%Y-%m-%d")

# ── 清理旧日志 ────────────────────────────────────
find "$LOG_DIR/logs" -name "briefing_*.log" -mtime +30 -delete 2>/dev/null || true

# ── 执行 ──────────────────────────────────────────
echo "[$(date '+%H:%M:%S')] 窗口: ${DAYS}天 | 范围: ${WINDOW_START} ~ ${YESTERDAY}"

cd "$PROJECT_DIR/scripts"
exec "$PYTHON" "$SCRIPT" --days "$DAYS" --ref-date "$YESTERDAY" --send-email 2>&1
