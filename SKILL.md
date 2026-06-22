---
name: news-briefing
description: >-
  从国家统计局、财政部、人民银行、金融监管总局、证监会5个财经监管机构官网抓取新闻，LLM生成中文摘要，输出HTML简报。触发条件：用户提到"新闻简报"、"财经简报"、"每日简报"、"监管动态"、"抓新闻"、"生成简报"等。
---

# 宏观形势及金融相关管理部门动态每日简报

运行 `scripts/main.py` 生成简报。所有抓取、过滤、LLM提取、渲染逻辑均在脚本中，直接执行即可。

## 使用方式

```bash
cd scripts/

# 默认：最近7天，全部5个源
python main.py

# 指定天数和数据源
python main.py --days 10 --sources pbc,csrc

# 指定基准日期 + 窗口
python main.py --days 7 --ref-date 2026-06-10

# 限制每源最大文章数
python main.py --max-articles 20

# 试运行（仅列表，跳过LLM）
python main.py --dry-run

# 生成并发送邮件（需要设置 SMTP_* 环境变量）
python main.py --send-email
```

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--days` | 7 | 时间窗口（天） |
| `--ref-date` | 今天 | 基准日期 YYYY-MM-DD |
| `--sources` | 全部 | 逗号分隔：`nfra,pbc,mof,csrc,stats` |
| `--max-articles` | 无限制 | 每源最大文章数 |
| `--dry-run` | false | 仅列表不提取 |
| `--send-email` | false | 发送邮件（需要设置 SMTP_* 环境变量） |

## 输出

- `output/{date_range}-宏观形势及金融相关管理部门动态每日简报.html` — 汇总简报
- `state/{slug}_seen.json` — 去重记录，跨运行持久化

## 依赖

```bash
pip install playwright beautifulsoup4 lxml jinja2 anthropic requests python-docx openpyxl pdfplumber
playwright install chromium
```

## 邮件发送

使用 `--send-email` 参数可以通过 SMTP 发送简报邮件，包含纯文本摘要 + HTML 正文 + HTML/PDF 附件。依赖 Python 标准库 `smtplib` 和 `email`，无需额外安装。

### 环境变量

| 变量 | 必需 | 说明 |
|------|------|------|
| `SMTP_HOST` | 是 | SMTP 服务器地址 |
| `SMTP_TO` | 是 | 收件人邮箱，多个用逗号分隔 |
| `SMTP_PORT` | 否 | 端口：465(SSL) / 587(STARTTLS, 默认) / 25(明文) |
| `SMTP_USER` | 否 | 登录用户名 |
| `SMTP_PASS` | 否 | 登录密码 |
| `SMTP_CC` | 否 | 抄送邮箱，多个用逗号分隔 |
| `SMTP_FROM` | 否 | 发件人地址（默认同 SMTP_USER） |

### 示例

```bash
export SMTP_HOST=smtp.example.com
export SMTP_PORT=587
export SMTP_USER=user@example.com
export SMTP_PASS=yourpassword
export SMTP_TO=team@example.com
export SMTP_CC=manager@example.com

python main.py --send-email
```

邮件发送失败不会中断简报生成，仅输出警告信息。

## 新增数据源

在 `scripts/sources/` 下新建文件，继承 `BaseSource`，实现 `parse_list_page()` 和 `parse_article_page()`。在 `__init__.py` 中注册。
