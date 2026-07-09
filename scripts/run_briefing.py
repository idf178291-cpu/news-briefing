#!/usr/bin/env python3
"""跨平台新闻简报定时任务 wrapper。

替代 run_briefing.sh，在 macOS / Linux / Windows 上均可运行。
自动计算智能覆盖窗口：工作日仅覆盖前一天，节假日/周末后的首个工作日自动扩大。

用法:
    python run_briefing.py                  # 自动计算窗口，生成并发送邮件
    python run_briefing.py --dry-run        # 仅显示将执行的命令，不实际运行
    python run_briefing.py --smtp-env FILE  # 指定 SMTP 配置文件路径
"""

import os
import sys
import subprocess
import argparse
from datetime import date, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
DEFAULT_SMTP_ENV = Path.home() / ".openclaw" / "smtp_env"
HOLIDAYS_FILE = PROJECT_DIR / "state" / "holidays.txt"
WORKDAYS_FILE = PROJECT_DIR / "state" / "workdays.txt"
LOG_DIR = PROJECT_DIR / "output"
LOG_RETENTION_DAYS = 30


# ── 假日/补班日加载 ──────────────────────────────────

def _load_dates(filepath: Path) -> set[date]:
    """从文件中加载日期集合，跳过空行和 # 注释行。"""
    if not filepath.exists():
        return set()
    dates = set()
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                dates.add(date.fromisoformat(line))
            except ValueError:
                print(f"[WARN] {filepath.name}: 忽略无效日期 '{line}'", file=sys.stderr)
    return dates


def is_off_day(d: date, holidays: set[date], workdays: set[date]) -> bool:
    """判断某日是否为非工作日。

    判定顺序：补班日 > 周末 > 节假日。
    workdays 中的日期强制视为工作日（处理调休）。
    """
    if d in workdays:
        return False
    if d.weekday() >= 5:  # 周六=5, 周日=6
        return True
    if d in holidays:
        return True
    return False


def calc_window(
    today: date, holidays: set[date], workdays: set[date]
) -> tuple[int, date, date]:
    """计算应覆盖的天数和日期范围。

    Returns (days, ref_date, window_start)
      - ref_date 固定为昨天
      - days = 1 + 昨天之前连续非工作日的天数（如昨天本身非工作日则 + 回溯到的最后工作日）
    """
    yesterday = today - timedelta(days=1)

    if not is_off_day(yesterday, holidays, workdays):
        # 昨天是工作日 → 仅覆盖昨天
        return 1, yesterday, yesterday

    # 昨天是非工作日 → 往前数
    days = 0
    cursor = yesterday
    while is_off_day(cursor, holidays, workdays):
        days += 1
        cursor -= timedelta(days=1)
    # cursor 现在是最后一个未被覆盖的工作日，一并纳入
    days += 1
    window_start = yesterday - timedelta(days=days - 1)
    return days, yesterday, window_start


# ── SMTP 环境变量加载 ───────────────────────────────

def load_smtp_env(filepath: Path) -> dict[str, str]:
    """从 shell 格式的配置文件中解析 SMTP 环境变量。"""
    env = {}
    if not filepath.exists():
        return env
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            # 跳过注释和空行
            if not line or line.startswith("#"):
                continue
            # 解析: export KEY=VALUE 或 KEY=VALUE
            if line.startswith("export "):
                line = line[7:]
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and value:
                env[key] = value
    return env


# ── 日志清理 ────────────────────────────────────────

def clean_old_logs(log_dir: Path, retention_days: int) -> int:
    """清理超过 retention_days 天的日志文件。返回删除数量。"""
    logs_subdir = log_dir / "logs"
    if not logs_subdir.exists():
        return 0
    cutoff = date.today() - timedelta(days=retention_days)
    deleted = 0
    for f in logs_subdir.glob("briefing_*.log"):
        try:
            # 尝试从文件名提取日期: briefing_2026-07-06.log
            stem = f.stem  # briefing_2026-07-06
            parts = stem.split("_", 1)
            if len(parts) == 2:
                file_date = date.fromisoformat(parts[1])
                if file_date < cutoff:
                    f.unlink()
                    deleted += 1
        except (ValueError, OSError):
            # 无法解析日期或删除失败 → 跳过，用 mtime 兜底
            pass
    # mtime 兜底
    for f in logs_subdir.glob("*.log"):
        try:
            mtime = date.fromtimestamp(f.stat().st_mtime)
            if mtime < cutoff:
                f.unlink()
                deleted += 1
        except OSError:
            pass
    return deleted


# ── Python 解释器查找 ───────────────────────────────

def find_python(project_dir: Path) -> str:
    """查找 venv 中的 Python 解释器，跨平台。"""
    if sys.platform == "win32":
        candidates = [
            project_dir / "venv" / "Scripts" / "python.exe",
            project_dir / "scripts" / ".venv" / "Scripts" / "python.exe",
        ]
    else:
        candidates = [
            project_dir / "venv" / "bin" / "python3",
            project_dir / "venv" / "bin" / "python",
            project_dir / "scripts" / ".venv" / "bin" / "python3",
        ]
    for p in candidates:
        if p.exists():
            return str(p)
    # 兜底：当前解释器
    return sys.executable


# ── 主入口 ──────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="跨平台简报定时任务 — 智能窗口计算 + 邮件发送"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="仅显示将执行的命令和窗口信息，不实际运行"
    )
    parser.add_argument(
        "--smtp-env", type=str, default=str(DEFAULT_SMTP_ENV),
        help=f"SMTP 配置文件路径（默认: {DEFAULT_SMTP_ENV}）"
    )
    parser.add_argument(
        "--date", type=str, default=None,
        help="模拟指定日期 YYYY-MM-DD（用于测试，默认使用今天）"
    )
    args = parser.parse_args()

    # 日期
    today = date.today() if args.date is None else date.fromisoformat(args.date)
    yesterday = today - timedelta(days=1)

    # 加载配置文件
    holidays = _load_dates(HOLIDAYS_FILE)
    workdays = _load_dates(WORKDAYS_FILE)

    # 非工作日 → 跳过
    if is_off_day(today, holidays, workdays):
        dow_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        reason = "周末" if today.weekday() >= 5 else "节假日"
        print(
            f"[{today}] {dow_names[today.weekday()]} 是非工作日（{reason}），跳过简报"
        )
        return

    # 计算窗口
    days, ref_date, window_start = calc_window(today, holidays, workdays)

    # 清理旧日志
    deleted = clean_old_logs(LOG_DIR, LOG_RETENTION_DAYS)
    if deleted:
        print(f"[LOG] 清理 {deleted} 个旧日志文件")

    # 构建命令
    python_exe = find_python(PROJECT_DIR)
    main_script = SCRIPT_DIR / "main.py"
    cmd = [
        python_exe, str(main_script),
        "--days", str(days),
        "--ref-date", ref_date.isoformat(),
        "--send-email",
    ]

    print(f"窗口: {days}天 | 范围: {window_start} ~ {ref_date}")
    print(f"Python: {python_exe}")
    print(f"命令: {' '.join(cmd)}")

    if args.dry_run:
        print("[DRY-RUN] 跳过实际执行")
        return

    # 加载 SMTP 环境变量
    smtp_env = load_smtp_env(Path(args.smtp_env))
    env = os.environ.copy()
    env.update(smtp_env)

    # 执行
    try:
        result = subprocess.run(
            cmd,
            cwd=str(SCRIPT_DIR),
            env=env,
            capture_output=False,
        )
        sys.exit(result.returncode)
    except FileNotFoundError:
        print(f"[ERROR] 找不到 Python 解释器: {python_exe}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n[INFO] 用户中断")
        sys.exit(130)


if __name__ == "__main__":
    main()
