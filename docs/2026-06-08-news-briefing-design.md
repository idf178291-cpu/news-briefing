# 财经新闻智能简报 — 设计规格

## 概述

从5个核心财经监管机构官网自动抓取最新新闻，提取关键信息并生成AI摘要，输出为汇总HTML简报。

## 数据源

| # | 名称 | slug | 列表页完整URL | 渲染方式 | 板块 | 分页 |
|---|------|------|-----------|----------|------|------|
| 1 | 国家统计局 | stats | `https://www.stats.gov.cn/xw/tjxw/` | 静态HTML | 统计动态、通知公告 | 无（单页8条） |
| 2 | 财政部 | mof | `https://www.mof.gov.cn/zhengwuxinxi/` | 静态HTML | 财政新闻、政策发布、政策解读 | 无（单页7条/板块） |
| 3 | 人民银行 | pbc | `https://www.pbc.gov.cn/goutongjiaoliu/113456/113469/index.html` | 静态HTML | 单一新闻列表 | 有（404页, 15条/页） |
| 4 | 金融监管总局 | nfra | `https://www.nfra.gov.cn/cn/view/pages/xinwenzixun/xinwenzixun.html` | **SPA (Angular/Vue)** | 监管动态、领导活动及讲话、新闻发布会及访谈、政策解读 | 有 |
| 5 | 证监会 | csrc | `https://www.csrc.gov.cn/csrc/xwfb/index.shtml` | 静态HTML | 证监会要闻、新闻发布会、政策解读 | "加载更多"按钮 |

## 架构

```
/news-briefing  (OpenClaw 命令触发)
      │
      ▼
┌─────────────────────────────────────────┐
│  main.py — 编排器                        │
│                                          │
│  for each source in sources/:            │
│    1. scraper:   Playwright 抓取列表页    │
│    2. dedup:     对比 state/{slug}_seen.json │
│    3. filter:    时间窗口过滤 (默认7天)    │
│    4. scraper:   进入详情页获取正文        │
│    5. extractor: LLM 结构化提取 + 摘要     │
│                                          │
│  → 数据聚合 → renderer → 汇总HTML         │
└─────────────────────────────────────────┘
```

## 数据源适配层

每个数据源实现 `BaseSource` 接口：

```python
class BaseSource:
    name: str          # "国家统计局"
    slug: str          # "stats"
    base_url: str      # "https://www.stats.gov.cn"
    list_url: str      # 列表页URL
    sections: list     # 要监控的板块名列表
    render_mode: str   # "static" | "spa"
    pagination: str    # "none" | "page" | "load_more"
    days_back: int     # 时间窗口（天）

    def parse_list_page(self, html) -> list[ArticleLink]: ...
    def parse_article_page(self, html) -> Article: ...
```

### 各源特殊处理

| 源 | 关键挑战 | 处理策略 |
|----|----------|----------|
| stats | 板块内8条即全部，无需翻页 | 直接解析，提取 tjdt + tzgg |
| mof | 板块多，URL混合（相对路径/子域名/外链） | 只取 caizhengxinwen；外链（scio.gov.cn/CCTV）跳过 |
| pbc | 404页分页，URL含时间戳+随机码 | 只抓前2页（30条），时间窗口过滤即可 |
| nfra | **SPA动态渲染** | Playwright `wait_for_selector` 等列表项出现；需拦截API或等DOM稳定 |
| csrc | "加载更多"按钮 | Playwright 点击2-3次加载更多后解析；注意c106311和c100028重复 |

## 信息提取规格

每篇文章 LLM 提取以下字段：

```json
{
  "title": "文章标题",
  "date": "2026-06-05",
  "source": "stats",
  "section": "统计动态",
  "core_event": "一句话核心事件",
  "personnel": ["康义", "毛盛勇"],
  "departments": ["国家统计局党组"],
  "key_points": [
    "以战略眼光谋划统计改革...",
    "坚定不移防治统计造假..."
  ],
  "summary": "2-4句中文摘要，领导讲话观点完整保留",
  "url": "https://..."
}
```

### 摘要质量要求
- 领导讲话/活动类：逐条保留观点，不遗漏、不扭曲
- 通知公告类：提取核心事项 + 截止时间/影响范围
- 政策发布类：政策名称 + 核心内容 + 生效时间
- 新闻发布会类：问答要点归纳

## HTML 输出规格

单文件自包含HTML，无需外部CSS/JS依赖。

### 页面结构
```
┌──────────────────────────────────────────┐
│  财经监管新闻每日简报                      │
│  2026-06-08 · 5个数据源 · 12篇新文章       │
├──────────────────────────────────────────┤
│  📊 概览卡片行                             │
│  ┌────────┐ ┌────────┐ ┌────────┐        │
│  │ 统计局  │ │ 财政部  │ │ 人行   │ ...    │
│  │  3篇   │ │  2篇   │ │  4篇   │        │
│  └────────┘ └────────┘ └────────┘        │
├──────────────────────────────────────────┤
│  📰 国家统计局                             │
│  ┌────────────────────────────────────┐  │
│  │ 标题 · 日期 · 板块                   │  │
│  │ 📌 核心事件                         │  │
│  │ 👤 康义、毛盛勇 · 🏛 国家统计局      │  │
│  │ 📝 摘要...                          │  │
│  │ 🔗 原文链接                         │  │
│  └────────────────────────────────────┘  │
│  ...更多卡片...                           │
├──────────────────────────────────────────┤
│  生成时间: 2026-06-08 08:30                │
└──────────────────────────────────────────┘
```

### 样式要求
- 专业简洁风格，适合阅读和打印
- 响应式布局（桌面/平板）
- 不同数据源用不同强调色区分
- 支持暗色模式（prefers-color-scheme）

## 文件结构

```
news-briefing/
├── SKILL.md                    # 技能文档
├── _meta.json                  # 元数据
├── scripts/
│   ├── main.py                 # 入口脚本，编排流程
│   ├── scraper.py              # Playwright 通用抓取工具
│   ├── extractor.py            # LLM 结构提取 + 摘要
│   ├── renderer.py             # Jinja2 HTML 渲染
│   └── sources/                # 数据源插件
│       ├── __init__.py         # 自动发现 + 注册
│       ├── base.py             # 抽象基类
│       ├── stats_gov.py        # 国家统计局
│       ├── mof_gov.py          # 财政部
│       ├── pbc_gov.py          # 人民银行
│       ├── nfra_gov.py         # 金融监管总局
│       └── csrc_gov.py         # 证监会
├── templates/
│   └── briefing.html           # Jinja2 汇总模板
├── output/                     # HTML 简报输出
└── state/                      # 去重记录
    ├── stats_seen.json
    ├── mof_seen.json
    ├── pbc_seen.json
    ├── nfra_seen.json
    └── csrc_seen.json
```

## 依赖

- Python 3.12
- Playwright (Chromium)
- BeautifulSoup4
- Jinja2
- Anthropic SDK (LLM 提取)

## 配置项

```python
# 可在 main.py 或 _meta.json 中覆盖
CONFIG = {
    "days_back": 7,              # 默认时间窗口
    "max_articles_per_source": 20, # 每个源最多抓取文章数
    "pagination_max_pages": 3,   # 分页源最多翻几页
    "output_dir": "./output",
    "state_dir": "./state",
}
```
