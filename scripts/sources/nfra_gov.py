"""金融监管总局 — https://www.nfra.gov.cn/cn/view/pages/xinwenzixun/xinwenzixun.html
SPA page (Angular/Vue) — actual content loaded via ItemList.html with query params.
We bypass the SPA shell and hit the ItemList pages directly."""

from .base import BaseSource, ArticleLink, Article
from bs4 import BeautifulSoup
import re


class NfraGovSource(BaseSource):
    name = "金融监管总局"
    slug = "nfra"
    base_url = "https://www.nfra.gov.cn"
    list_url = "https://www.nfra.gov.cn/cn/view/pages/xinwenzixun/xinwenzixun.html"
    sections = ["监管动态", "领导活动及讲话", "新闻发布会及访谈", "政策解读",
                "政策法规", "统计信息"]
    render_mode = "static"  # we bypass SPA by hitting ItemList directly
    pagination = "none"
    skip_title_keywords = ["任职资格", "任职批复", "核准任职", "会见", "拟录用", "遴选", "公开招聘", "聘用"]
    WAIT_SELECTORS = ["span.date.ng-binding", "a[href*='ItemDetail.html']"]

    # Direct URLs for each subsection (bypasses SPA shell)
    SECTION_URLS = {
        "监管动态": "/cn/view/pages/ItemList.html?itemPId=914&itemId=915&itemUrl=ItemListRightList.html&itemName=监管动态",
        "领导活动及讲话": "/cn/view/pages/ItemList.html?itemPId=914&itemId=919&itemUrl=ItemListRightList.html&itemName=领导活动及讲话",
        "新闻发布会及访谈": "/cn/view/pages/ItemList.html?itemPId=914&itemId=920&itemUrl=xinwenzixun/xinwenfabu.html&itemName=新闻发布会及访谈",
        "政策解读": "/cn/view/pages/ItemList.html?itemPId=914&itemId=917&itemUrl=ItemListRightList.html&itemName=政策解读&itemsubPId=916",
        "政策法规": "/cn/view/pages/ItemList.html?itemPId=923&itemId=926&itemUrl=ItemListRightMore.html&itemName=政策法规",
        "统计信息": "/cn/view/pages/ItemList.html?itemPId=954&itemId=954&itemUrl=ItemListRightList.html&itemName=统计信息",
    }

    # Map itemId to section name
    ITEM_ID_MAP = {
        "915": "监管动态",
        "919": "领导活动及讲话",
        "920": "新闻发布会及访谈",
        "917": "政策解读",
        "921": "新闻发言人",
        "926": "政策法规",
        "927": "政策法规",
        "928": "政策法规",
        "954": "统计信息",
    }

    # Which itemIds belong to each section (for filtering out sidebar noise)
    SECTION_ITEM_IDS = {
        "监管动态": {"915"},
        "领导活动及讲话": {"919"},
        "新闻发布会及访谈": {"920"},
        "政策解读": {"917"},
        "政策法规": {"926", "927", "928"},
        "统计信息": {"954"},
    }

    def get_section_urls(self) -> list[tuple[str, str]]:
        """Return list of (section_name, full_url) to scrape."""
        return [
            (name, self.make_absolute_url(path))
            for name, path in self.SECTION_URLS.items()
            if name in self.sections
        ]

    def parse_list_page(self, html: str, page_url: str) -> list[ArticleLink]:
        soup = BeautifulSoup(html, "lxml")
        links = []
        seen_urls = set()
        seen_docids = set()

        # Determine which section this page belongs to, for itemId filtering
        page_item_id = ""
        m = re.search(r'itemId=(\d+)', page_url)
        if m:
            page_item_id = m.group(1)
        page_section = ""
        for sname, spath in self.SECTION_URLS.items():
            if f"itemId={page_item_id}" in spath:
                page_section = sname
                break
        allowed_ids = self.SECTION_ITEM_IDS.get(page_section, set())

        # NFRA page has separate panels for titles and dates — pair by index
        date_els = soup.select("span.date.ng-binding")
        dates = []
        for d in date_els:
            raw = d.get_text(strip=True)
            m2 = re.search(r'(\d{4}-\d{2}-\d{2}|\d{4}/\d{2}/\d{2})', raw)
            dates.append(m2.group(1) if m2 else "")

        article_idx = 0
        for a in soup.select("a[href]"):
            href = a.get("href", "").strip()
            if not href:
                continue
            if "ItemDetail.html" not in href or "docId=" not in href:
                continue

            title = a.get_text(strip=True)
            if not title or len(title) < 6:
                continue

            full_url = self.make_absolute_url(href, page_url)
            if full_url in seen_urls:
                continue

            m = re.search(r'docId=(\d+)', href)
            doc_id = m.group(1) if m else ""
            if doc_id and doc_id in seen_docids:
                continue

            seen_urls.add(full_url)
            if doc_id:
                seen_docids.add(doc_id)

            # Determine section and filter by itemId
            m = re.search(r'itemId=(\d+)', href)
            article_item_id = m.group(1) if m else ""
            section = self.ITEM_ID_MAP.get(article_item_id, "")

            if allowed_ids and article_item_id not in allowed_ids:
                continue

            # Date: pair by index with date spans
            date_str = dates[article_idx] if article_idx < len(dates) else ""
            # Fallback: date embedded at end of title
            if not date_str:
                m2 = re.search(r'(\d{4}-\d{2}-\d{2})\s*$', title)
                if m2:
                    date_str = m2.group(1)
                    title = re.sub(r'\s*\d{4}-\d{2}-\d{2}\s*$', '', title).strip()

            article_idx += 1
            links.append(ArticleLink(
                title=title, url=full_url,
                date_str=date_str, section=section,
            ))

        return links

    def parse_article_page(self, html: str, url: str) -> Article | None:
        soup = BeautifulSoup(html, "lxml")

        # Title: NFRA uses <div class="wenzhang-title"> for the article heading
        # Avoid <span class="title"> which are sidebar items
        title_el = (
            soup.select_one(".wenzhang-title")
            or soup.select_one("[class*=wenzhang-title]")
            or soup.select_one("div[class*=art-title]")
        )
        if not title_el:
            # Fallback: first h1/h2 with substantial text (skip sidebar leader names)
            for h in soup.select("h1, h2"):
                text = h.get_text(strip=True)
                if len(text) > 15:
                    title_el = h
                    break
        if not title_el:
            title_el = soup.select_one("title")
        title = title_el.get_text(strip=True) if title_el else ""

        # Date: find "发布时间" specifically, ignore "留言时间"
        date_str = ""
        for el in soup.select('[class*=publish], [class*=pubtime], span, font, td, div, p'):
            text = el.get_text(strip=True)
            if text and "发布时间" in text:
                # Extract snippet around "发布时间" — the full text may be huge from nav boilerplate
                idx = text.index("发布时间")
                snippet = text[idx:idx + 100]
                m = re.search(r'(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})', snippet)
                if m:
                    date_str = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
                    break
        # Must have both .wenzhang-title (article heading) AND "发布时间" — skip list/guide pages
        if not date_str:
            return None
        if not soup.select_one(".wenzhang-title, [class*=wenzhang-title]"):
            return None

        # Section from URL itemId
        section = ""
        m = re.search(r'itemId=(\d+)', url)
        if m:
            section = self.ITEM_ID_MAP.get(m.group(1), "")

        # Body
        body_parts = []
        for sel in [".article-content", ".content", ".TRS_Editor", "article", "#zoom", ".detail-content"]:
            container = soup.select_one(sel)
            if container:
                for p in container.find_all(["p", "div"]):
                    text = p.get_text(strip=True)
                    if text and len(text) > 10:
                        body_parts.append(text)
                break

        if not body_parts and soup.body:
            body_parts.append(soup.body.get_text(separator="\n", strip=True))

        return Article(
            title=title,
            url=url,
            date_str=date_str,
            source=self.slug,
            section=section,
            body="\n\n".join(body_parts)[:10000],
        )
