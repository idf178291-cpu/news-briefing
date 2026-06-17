#!/usr/bin/env python3
"""财经新闻智能简报 — 主编排脚本。
从5个财经监管机构官网抓取最新新闻，LLM提取关键信息并生成摘要。
"""

import os, sys, json, argparse, time, re
from datetime import datetime, date
from pathlib import Path
from contextlib import contextmanager

from scraper import Scraper
from extractor import Extractor
from renderer import Renderer
from sources import get_sources, BaseSource, BriefingItem

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
DEFAULT_STATE_DIR = PROJECT_DIR / "state"
DEFAULT_OUTPUT_DIR = PROJECT_DIR / "output"

# ── simple phase logger ──────────────────────────────────────
class Log:
    INDENT = 0
    @staticmethod
    def phase(msg: str):
        print(f"\n{'='*56}", flush=True)
        print(f"  {msg}", flush=True)
        print(f"{'='*56}", flush=True)
    @staticmethod
    def step(msg: str, src: str = ""):
        prefix = f"[{src}] " if src else ""
        print(f"  → {prefix}{msg}", flush=True)
    @staticmethod
    def ok(msg: str, src: str = ""):
        prefix = f"[{src}] " if src else ""
        print(f"  ✓ {prefix}{msg}", flush=True)
    @staticmethod
    def warn(msg: str, src: str = ""):
        prefix = f"[{src}] " if src else ""
        print(f"  ⚠ {prefix}{msg}", flush=True)
    @staticmethod
    def info(msg: str):
        print(f"    {msg}", flush=True)
    @staticmethod
    def result(total: int, path: str):
        print(f"\n{'='*56}", flush=True)
        print(f"  ✅ 完成! {total} 篇新文章", flush=True)
        print(f"  📄 {path}", flush=True)
        print(f"{'='*56}", flush=True)

log = Log()


# ── state persistence ────────────────────────────────────────
def load_seen(state_dir: Path, slug: str) -> set[str]:
    path = state_dir / f"{slug}_seen.json"
    if path.exists():
        try:
            return set(json.loads(path.read_text()).get("urls", []))
        except (json.JSONDecodeError, KeyError):
            pass
    return set()

def save_seen(state_dir: Path, slug: str, urls: set[str]):
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / f"{slug}_seen.json").write_text(json.dumps({
        "updated": datetime.now().isoformat(), "count": len(urls), "urls": sorted(urls),
    }, ensure_ascii=False, indent=2))


# ── per-source pipeline ──────────────────────────────────────
def process_source(source, scraper, extractor, seen_urls, days_back, dry_run, max_articles, ref_date=None):
    slug = source.slug
    t0 = time.time()

    log.step(f"获取列表页: {source.list_url}", slug)

    # 1. fetch list pages — priority: list_urls > get_section_urls > list_url
    if source.list_urls:
        fetch_urls = source.list_urls
        log.info(f"列表URL: {len(fetch_urls)} 个")
    elif hasattr(source, "get_section_urls") and callable(source.get_section_urls):
        fetch_urls = [url for _, url in source.get_section_urls()]
        log.info(f"板块: {len(fetch_urls)} 个")
    else:
        fetch_urls = [source.list_url]

    html_pages: list[tuple[str, str]] = []  # (list_url, html) pairs
    for list_url in fetch_urls:
        if source.pagination == "load_more":
            html = scraper.click_load_more(list_url,
                button_selector="a.load-more, .loadmore, [class*=load-more], [class*=more]",
                clicks=source.pagination_max)
            html_pages.append((list_url, html))
        elif source.pagination == "page":
            for pg_html in scraper.click_next_pages(list_url,
                link_selector="a.next, .page-next, [class*=next], a:has-text('下一页')",
                pages=source.pagination_max):
                html_pages.append((list_url, pg_html))
        else:
            wait_sels = getattr(source, "WAIT_SELECTORS", None)
            html = scraper.fetch_page(list_url, wait_for=wait_sels)
            html_pages.append((list_url, html))
    t1 = time.time()

    # 2. parse links
    all_links = []
    # Allow sources to add extra links via scraper (e.g. drill-down navigation)
    if hasattr(source, "collect_extra_links") and callable(source.collect_extra_links):
        extra = source.collect_extra_links(scraper)
        if extra:
            log.info(f"额外链接: {len(extra)} 条")
            all_links.extend(extra)
    for list_url, html in html_pages:
        all_links.extend(source.parse_list_page(html, list_url))
    # dedup by URL within this run
    seen_this_run = set()
    unique_links = [l for l in all_links if not (l.url in seen_this_run or seen_this_run.add(l.url))]
    # Sort by date (newest first) so max_articles picks recent across all sections
    unique_links.sort(key=lambda x: x.date_str or "", reverse=True)
    log.info(f"列表页: {len(unique_links)} 条 ({time.time()-t1:.1f}s)")

    # 3. filter by title keywords (before history dedup + time window)
    if source.skip_title_keywords:
        before = len(unique_links)
        unique_links = [l for l in unique_links
            if not any(kw in l.title for kw in source.skip_title_keywords)]
        if before != len(unique_links):
            log.info(f"标题过滤: {before - len(unique_links)} 篇")

    # 4. dedup vs history + time window
    new_links, skipped_seen, skipped_window = [], 0, 0
    for link in unique_links:
        if link.url in seen_urls:
            skipped_seen += 1; continue
        if not source.is_within_window(link.date_str, days_back, ref_date):
            skipped_window += 1; continue
        new_links.append(link)
    if max_articles and len(new_links) > max_articles:
        new_links = new_links[:max_articles]
    log.info(f"过滤: 已读{skipped_seen} 超窗{skipped_window} → 待抓{len(new_links)} 篇")

    if not new_links:
        log.ok(f"无新文章 ({time.time()-t0:.1f}s)", slug)
        return []

    # 5. scrape detail pages — reuse ONE page
    articles = []
    page = scraper.borrow_page()
    try:
        for i, link in enumerate(new_links):
            try:
                html = scraper.navigate(page, link.url)
                article = source.parse_article_page(html, link.url)
                if article:
                    article.source = slug
                    if link.section:
                        article.section = link.section
                    if not article.date_str:
                        article.date_str = link.date_str
                    # Download and extract attachments
                    soup = scraper.to_soup(html)
                    atts = source.find_attachments(soup, source.base_url, article.url)
                    if atts:
                        att_text = scraper.download_attachments(atts)
                        if att_text:
                            article.body += "\n\n【附件内容】\n" + att_text
                    articles.append(article)
                else:
                    log.info(f"[{i+1}/{len(new_links)}] 跳过(非新闻): {link.title[:35]}")
            except Exception as e:
                log.warn(f"[{i+1}/{len(new_links)}] 出错: {e}", slug)
    finally:
        scraper.return_page(page)
    t2 = time.time()

    n_scraped = len(articles)
    # 6. post-scrape date filter
    filtered, skipped_late = [], 0
    for a in articles:
        if a.date_str and not source.is_within_window(a.date_str, days_back, ref_date):
            skipped_late += 1; continue
        filtered.append(a)
    articles = filtered
    log.info(f"详情: {n_scraped}篇 再滤{skipped_late} → {len(articles)}篇 ({t2-t1:.1f}s)")

    # 7. LLM extraction
    if dry_run or extractor is None:
        items = [BriefingItem(title=a.title, date_str=a.date_str, source=a.source,
                              section=a.section, url=a.url,
                              tags=[a.section] if a.section else []) for a in articles]
    else:
        items = []
        skipped_llm = 0
        for i, a in enumerate(articles):
            try:
                log.info(f"LLM [{i+1}/{len(articles)}] {a.title[:35]}...")
                item = extractor.extract(a, source.name)
                # Skip articles where LLM failed to produce a meaningful summary
                if not item.summary.strip() and not item.core_event.strip():
                    skipped_llm += 1
                    continue
                # Auto-add section name as tag
                if a.section and a.section not in item.tags:
                    item.tags.insert(0, a.section)
                items.append(item)
            except Exception as e:
                log.warn(f"LLM出错: {e}", slug)
        t3 = time.time()
        log.info(f"LLM: {len(items)}篇 (跳过{skipped_llm}篇空摘要) ({t3-t2:.1f}s)")

    # 8. source-specific dedup (e.g. 数据发布 vs 数据解读 overlap)
    if hasattr(source, "deduplicate_items") and callable(source.deduplicate_items):
        before = len(items)
        items = source.deduplicate_items(items)
        if len(items) < before:
            log.info(f"去重: {before - len(items)} 篇重复")

    log.ok(f"{len(items)} 篇 ({time.time()-t0:.1f}s)", slug)
    return items


# ── main ─────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="财经新闻每日简报")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--sources", type=str, default=None)
    parser.add_argument("--output", type=str, default=None)
    parser.add_argument("--max-articles", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--pdf", action="store_true", help="Also generate a PDF version")
    parser.add_argument("--headless", type=bool, default=True)
    parser.add_argument("--ref-date", type=str, default=None,
                        help="Reference date YYYY-MM-DD (default: today)")
    args = parser.parse_args()

    slugs = args.sources.split(",") if args.sources else None
    sources = get_sources(slugs)
    ref_date = date.fromisoformat(args.ref_date) if args.ref_date else None
    state_dir = DEFAULT_STATE_DIR
    output_dir = DEFAULT_OUTPUT_DIR
    if args.output:
        p = Path(args.output)
        state_dir = p; output_dir = p

    log.phase(f"财经新闻每日简报 | 基准日: {args.ref_date or '今天'} | 窗口: {args.days}天 | 源: {', '.join(s.name for s in sources)}")

    extractor = None if args.dry_run else Extractor()

    try:
        with Scraper(headless=args.headless) as scraper:
            all_items = []
            for source in sources:
                seen_urls = load_seen(state_dir, source.slug)
                items = process_source(source, scraper, extractor, seen_urls,
                    args.days, args.dry_run, args.max_articles, ref_date)
                for item in items:
                    seen_urls.add(item.url)
                save_seen(state_dir, source.slug, seen_urls)

                # group by section
                sections = {}
                for item in items:
                    sec = item.section or "其他"
                    sections.setdefault(sec, []).append(item)
                for sec_items in sections.values():
                    sec_items.sort(key=lambda x: (x.date_str or "", x.title), reverse=True)
                section_order = {s: i for i, s in enumerate(source.sections + ["其他"])}
                sorted_sec = sorted(sections.items(), key=lambda kv: section_order.get(kv[0], 99))

                all_items.append({
                    "name": source.name, "slug": source.slug,
                    "sections": [{"name": s, "articles": a} for s, a in sorted_sec],
                    "article_count": len(items),
                })
    except Exception as e:
        log.warn(f"运行出错: {e}")
        import traceback; traceback.print_exc()
        sys.exit(1)

    renderer = Renderer()
    date_str = args.ref_date if args.ref_date else datetime.now().strftime("%Y-%m-%d")
    html_path = output_dir / f"宏观形势及监管动态每日简报_{date_str}.html"
    output_dir.mkdir(parents=True, exist_ok=True)
    renderer.render(all_items, str(html_path), display_date=date_str)
    log.result(sum(s["article_count"] for s in all_items), str(html_path))

    pdf_path = output_dir / f"宏观形势及监管动态每日简报_{date_str}.pdf"
    renderer.pdf(str(html_path), str(pdf_path))
    log.info(f"📄 PDF 已生成: {pdf_path}")


if __name__ == "__main__":
    main()
