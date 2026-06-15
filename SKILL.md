---
name: news-briefing
description: >-
  从国家统计局、财政部、人民银行、金融监管总局、证监会5个财经监管机构官网抓取新闻，LLM生成中文摘要，输出HTML简报。触发条件：用户提到"新闻简报"、"财经简报"、"每日简报"、"监管动态"、"抓新闻"、"生成简报"等。
---

# 宏观形势及监管动态每日简报

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
```

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--days` | 7 | 时间窗口（天） |
| `--ref-date` | 今天 | 基准日期 YYYY-MM-DD |
| `--sources` | 全部 | 逗号分隔：`nfra,pbc,mof,csrc,stats` |
| `--max-articles` | 无限制 | 每源最大文章数 |
| `--dry-run` | false | 仅列表不提取 |

## 输出

- `output/briefing_YYYY-MM-DD.html` — 汇总简报
- `state/{slug}_seen.json` — 去重记录，跨运行持久化

## 依赖

```bash
pip install playwright beautifulsoup4 lxml jinja2 anthropic requests python-docx openpyxl pdfplumber
playwright install chromium
```

## 新增数据源

在 `scripts/sources/` 下新建文件，继承 `BaseSource`，实现 `parse_list_page()` 和 `parse_article_page()`。在 `__init__.py` 中注册。
