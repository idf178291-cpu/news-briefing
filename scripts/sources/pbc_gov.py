"""人民银行 — https://www.pbc.gov.cn/goutongjiaoliu/113456/113469/index.html"""

from .base import BaseSource, ArticleLink, Article
from bs4 import BeautifulSoup
import re
from datetime import date


STATS_SUBCATS = [
    ("shrzgm", "社会融资规模"),
    ("hbtjgl", "货币统计概览"),
    ("jryjgzcfztj", "金融业机构资产负债统计"),
    ("jrjgxdsztj", "金融机构信贷收支统计"),
    ("jrsctj", "金融市场统计"),
    ("qyspjgcgpizs", "企业商品价格（CGPI）指数"),
]


class PbcGovSource(BaseSource):
    name = "人民银行"
    slug = "pbc"
    base_url = "https://www.pbc.gov.cn"
    list_url = "https://www.pbc.gov.cn/goutongjiaoliu/113456/113469/index.html"
    list_urls = [
        "https://www.pbc.gov.cn/goutongjiaoliu/113456/113469/index.html",
        "https://www.pbc.gov.cn/diaochatongjisi/116219/116225/index.html",
        "https://www.pbc.gov.cn/diaochatongjisi/116219/116227/index.html",
    ]
    sections = ["新闻发布", "统计数据", "数据解读", "调查与分析"]
    render_mode = "static"
    pagination = "page"
    pagination_max = 5

    # ── parse_list_page dispatch ──────────────────────────────
    def parse_list_page(self, html: str, page_url: str) -> list[ArticleLink]:
        if "/116225/" in page_url:
            return self._parse_section_page(html, page_url, "数据解读")
        if "/116227/" in page_url:
            return self._parse_section_page(html, page_url, "调查与分析")
        return self._parse_news_page(html, page_url)

    # ── News page (goutongjiaoliu) ────────────────────────────
    def _parse_news_page(self, html: str, page_url: str) -> list[ArticleLink]:
        soup = BeautifulSoup(html, "lxml")
        links = []
        seen = set()

        for a in soup.select("a[href]"):
            href = a.get("href", "").strip()
            if not href:
                continue
            if "/113469/" not in href or not href.endswith("/index.html"):
                continue

            title = a.get_text(strip=True)
            if not title or len(title) < 8:
                continue

            full_url = self.make_absolute_url(href, page_url)
            if full_url in seen:
                continue
            seen.add(full_url)

            date_str = self._date_from_adjacent_text(a)
            # Fallback: URL timestamp (e.g. /113469/2026052912312386392/index.html)
            if not date_str:
                date_str = self._date_from_url_timestamp(href)

            links.append(ArticleLink(
                title=title, url=full_url,
                date_str=date_str, section="新闻发布",
            ))
        return links

    # ── Section pages (数据解读 / 调查与分析) ──────────────────
    def _parse_section_page(self, html: str, page_url: str,
                            section: str) -> list[ArticleLink]:
        """Parse 数据解读 or 调查与分析 list page.

        URLs follow two patterns:
          - /11622x/YYYYMMDDHHMMSSmmm/index.html  → date from timestamp
          - /11622x/<numeric_id>/index.html          → date from title
        """
        soup = BeautifulSoup(html, "lxml")
        links = []
        seen = set()

        for a in soup.select("a[href]"):
            href = a.get("href", "").strip()
            if not href or not href.endswith("/index.html"):
                continue

            title = a.get_text(strip=True)
            if not title or len(title) < 8:
                continue

            # Must be a section article (not navigation)
            section_id = None
            for sid in ["116225", "116227"]:
                if f"/{sid}/" in href:
                    section_id = sid
                    break
            if not section_id:
                continue

            full_url = self.make_absolute_url(href, page_url)
            if full_url in seen:
                continue
            seen.add(full_url)

            # Date from URL timestamp: /11622x/YYYYMMDDHHMMSS.../index.html
            date_str = self._date_from_url_timestamp(href)
            # Fallback: date from title text
            if not date_str:
                date_str = self._date_from_title(title)

            links.append(ArticleLink(
                title=title, url=full_url,
                date_str=date_str, section=section,
            ))
        return links

    # ── 统计数据 drill-down ───────────────────────────────────
    def collect_extra_links(self, scraper) -> list[ArticleLink]:
        """Navigate DCTS landing → current-year stats → sub-categories → attachments.

        Each sub-category page lists data tables with htm/xls/pdf attachment links.
        We extract attachment links and treat them as articles, using URL path dates.
        """
        page = scraper.borrow_page()
        links = []
        current_year = date.today().year

        try:
            # 1) Navigate to DCTS landing, find current-year stats link
            landing_url = "https://www.pbc.gov.cn/diaochatongjisi/116219/index.html"
            scraper.navigate(page, landing_url)
            soup = BeautifulSoup(page.content(), "lxml")

            year_href = ""
            for a in soup.select("a[href]"):
                href = a.get("href", "").strip()
                text = a.get_text(strip=True)
                if f"{current_year}年统计数据" in text and "/116319/" in href:
                    year_href = href
                    break

            if not year_href:
                return links

            year_url = self.make_absolute_url(year_href, landing_url)

            # 2) Navigate to year page, find sub-category links
            scraper.navigate(page, year_url)
            soup = BeautifulSoup(page.content(), "lxml")

            subcat_urls = {}
            for a in soup.select("a[href]"):
                href = a.get("href", "").strip()
                text = a.get_text(strip=True)
                for slug, name in STATS_SUBCATS:
                    if f"/{slug}/" in href and name in text:
                        full = self.make_absolute_url(href, year_url)
                        if slug not in subcat_urls:
                            subcat_urls[slug] = (full, name)
                        break

            # 3) For each sub-category, find attachment links
            for slug, (subcat_url, cat_name) in subcat_urls.items():
                try:
                    scraper.navigate(page, subcat_url)
                    soup = BeautifulSoup(page.content(), "lxml")

                    for a in soup.select("a[href]"):
                        href = a.get("href", "").strip()
                        if not href or "/attachDir/" not in href:
                            continue
                        # Only htm/html — xlsx/pdf trigger Playwright download
                        if not (href.endswith(".htm") or href.endswith(".html")):
                            continue

                        text = a.get_text(strip=True)
                        full_url = self.make_absolute_url(href, subcat_url)
                        date_str = self._date_from_attach_url(href)
                        if not date_str:
                            continue

                        # Look for table name in adjacent cells
                        table_name = self._find_table_name(a, cat_name)

                        links.append(ArticleLink(
                            title=table_name,
                            url=full_url,
                            date_str=date_str,
                            section="统计数据",
                        ))
                except Exception as e:
                    print(f"  [PBC] 统计数据/{cat_name} 出错: {e}")

        finally:
            scraper.return_page(page)

        return links

    @staticmethod
    def _find_table_name(a_tag, cat_name: str) -> str:
        """Find the table name from a parent row/cell that contains this <a>."""
        el = a_tag.parent
        for _ in range(6):
            if el is None:
                break
            # Look for a sibling or parent cell with text
            if el.name in ("tr",):
                texts = []
                for td in el.find_all("td"):
                    t = td.get_text(strip=True)
                    if t and len(t) > 2 and t not in ("htm", "xls", "pdf", "Q1", "Q2", "Q3", "Q4"):
                        texts.append(t)
                if texts:
                    return f"{cat_name} - {' | '.join(texts[:2])}"
            el = el.parent

        # Fallback: page title-derived
        title_el = BeautifulSoup(a_tag.prettify(), "lxml")  # not great, but works
        return cat_name + "统计数据"

    # ── Article page parsing ──────────────────────────────────
    def parse_article_page(self, html: str, url: str) -> Article | None:
        soup = BeautifulSoup(html, "lxml")

        # Handle attachDir htm files (统计数据 data tables)
        if "/attachDir/" in url:
            return self._parse_attach_article(soup, url)

        # Title
        title_el = soup.select_one("h2") or soup.select_one("h1") or soup.select_one("title")
        title = title_el.get_text(strip=True) if title_el else ""

        # Date
        date_str = self._date_from_url_timestamp(url)
        if not date_str:
            date_el = soup.select_one(".hui12, #lblDatetime, .time, [id*=date]")
            if date_el:
                raw = date_el.get_text(strip=True) if hasattr(date_el, "get_text") else str(date_el)
                m = re.search(r'(\d{4}-\d{2}-\d{2})', raw)
                if m:
                    date_str = m.group(1)
        if not date_str:
            date_el = soup.find(string=re.compile(r"\d{4}-\d{2}-\d{2}"))
            if date_el:
                m = re.search(r'(\d{4}-\d{2}-\d{2})', str(date_el))
                if m:
                    date_str = m.group(1)
        if not date_str:
            date_el = soup.find(string=re.compile(r"\d{4}年\d{1,2}月\d{1,2}日"))
            if date_el:
                m = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', str(date_el))
                if m:
                    date_str = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

        # Section from URL
        section = "新闻发布"
        if "/116225/" in url:
            section = "数据解读"
        elif "/116227/" in url:
            section = "调查与分析"
        elif "/116319/" in url or "/attachDir/" in url:
            section = "统计数据"

        # Body
        body_parts = []
        for sel in ["#zoom", ".TRS_Editor", ".content", ".article-con", "#content"]:
            container = soup.select_one(sel)
            if container:
                for p in container.find_all(["p", "div", "span"]):
                    text = p.get_text(strip=True)
                    if text and len(text) > 15 and not text.startswith("<!--"):
                        body_parts.append(text)
                break

        if not body_parts and soup.body:
            body_parts.append(soup.body.get_text(separator="\n", strip=True))

        return Article(
            title=title, url=url, date_str=date_str,
            source=self.slug, section=section,
            body="\n\n".join(body_parts)[:10000],
        )

    def _parse_attach_article(self, soup, url: str) -> Article | None:
        """Parse an attachDir htm page (统计数据 data table)."""
        title = ""
        # Try standard selectors first
        for sel in ["h2", "h1", "title", ".title", "[class*=title]"]:
            el = soup.select_one(sel)
            if el:
                title = el.get_text(strip=True)
                if len(title) > 4:
                    break

        if not title:
            # Use table header text
            for th in soup.select("th, thead td"):
                t = th.get_text(strip=True)
                if t and len(t) > 4:
                    title = t
                    break

        date_str = self._date_from_attach_url(url)

        # Extract table text as body
        body_parts = []
        for table in soup.select("table"):
            rows = []
            for tr in table.select("tr"):
                cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                if cells:
                    rows.append("\t".join(cells))
            if rows:
                body_parts.append("\n".join(rows))

        body = "\n\n".join(body_parts)
        if not body:
            body = soup.body.get_text(separator="\n", strip=True) if soup.body else ""

        return Article(
            title=title, url=url, date_str=date_str,
            source=self.slug, section="统计数据",
            body=body[:10000],
        )

    # ── Date extraction helpers ───────────────────────────────
    @staticmethod
    def _date_from_url_timestamp(href: str) -> str:
        """Extract date from URL like .../116225/YYYYMMDDHHMMSSmmm/index.html.

        Timestamp is 14+ digits; first 8 are YYYYMMDD.
        """
        m = re.search(r'/(\d{14})\d*/', href)
        if m:
            ts = m.group(1)
            return f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}"
        return ""

    @staticmethod
    def _date_from_attach_url(href: str) -> str:
        """Extract date from attachDir URL: /attachDir/YYYY/MM/timestamp.ext.

        Uses timestamp from filename (YYYYMMDDHHMMSS...) for exact date,
        falling back to YYYY-MM path.
        """
        # Try timestamp in filename for exact date
        m = re.search(r'/(\d{8})\d{6,}', href)
        if m:
            ts = m.group(1)
            return f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}"
        # Fallback: year/month from path
        m = re.search(r'/attachDir/(\d{4})/(\d{2})/', href)
        if m:
            return f"{m.group(1)}-{m.group(2)}-01"
        return ""

    @staticmethod
    def _date_from_title(title: str) -> str:
        """Extract date from title like '2026年4月金融统计数据报告'."""
        # "2026年4月" or "2026年一季度" or "2026年第一季度"
        m = re.search(r'(\d{4})年(\d{1,2})月', title)
        if m:
            return f"{m.group(1)}-{int(m.group(2)):02d}-01"
        m = re.search(r'(\d{4})年([一二三四]|半)季', title)
        if m:
            qmap = {"一": "01", "二": "04", "三": "07", "四": "10", "半": "07"}
            q = m.group(2)
            month = qmap.get(q, "01")
            return f"{m.group(1)}-{month}-01"
        m = re.search(r'(\d{4})年', title)
        if m:
            return f"{m.group(1)}-01-01"
        return ""

    @staticmethod
    def _date_from_adjacent_text(a_tag) -> str:
        """Extract YYYY-MM-DD date from adjacent text nodes around an <a> tag."""
        parent = a_tag.parent
        if parent:
            full_text = parent.get_text(" ", strip=True)
            m = re.search(r'(\d{4}-\d{2}-\d{2})', full_text)
            if m:
                return m.group(1)
            # Try find in siblings
            for el in parent.find_all(["span", "font", "td", "div"], recursive=False):
                text = el.get_text(strip=True)
                m = re.search(r'(\d{4}-\d{2}-\d{2})', text)
                if m:
                    return m.group(1)
        return ""

    # ── dedup: 数据发布 vs 数据解读 ─────────────────────────
    def deduplicate_items(self, items: list) -> list:
        """Remove 数据发布 items that overlap with 数据解读 on the same data."""
        # Extract data-period key from title: "2026年5月", "2026年一季度", etc
        def _period_key(item) -> str:
            t = item.title + item.core_event
            m = re.search(r'(\d{4})年(\d{1,2})月', t)
            if m:
                return f"{m.group(1)}-{int(m.group(2)):02d}"
            m = re.search(r'(\d{4})年([一二三四]|半)季', t)
            if m:
                qmap = {"一": "Q1", "二": "Q2", "三": "Q3", "四": "Q4", "半": "H1"}
                return f"{m.group(1)}-{qmap.get(m.group(2), m.group(2))}"
            m = re.search(r'(\d{4})年(\d{1,2})-(\d{1,2})月', t)
            if m:
                return f"{m.group(1)}-{int(m.group(2)):02d}"
            return ""

        # Section priority: data解读 > 数据发布, keep others
        KEEP_ORDER = {"数据发布": 0, "数据解读": 1}

        groups: dict[str, list] = {}
        ungrouped = []
        for item in items:
            key = _period_key(item)
            if key:
                groups.setdefault(key, []).append(item)
            else:
                ungrouped.append(item)

        result = list(ungrouped)
        for key, group in groups.items():
            if len(group) == 1:
                result.extend(group)
            else:
                # Sort by priority: prefer 数据解读 over 数据发布
                group.sort(key=lambda x: KEEP_ORDER.get(x.section, 99))
                result.append(group[0])

        return result
