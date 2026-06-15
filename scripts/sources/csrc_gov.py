"""证监会 — https://www.csrc.gov.cn/csrc/xwfb/index.shtml"""

from .base import BaseSource, ArticleLink, Article
from bs4 import BeautifulSoup
import re
from datetime import date


class CsrcGovSource(BaseSource):
    name = "证监会"
    slug = "csrc"
    base_url = "https://www.csrc.gov.cn"
    list_url = "https://www.csrc.gov.cn/csrc/xwfb/index.shtml"
    list_urls = [
        "https://www.csrc.gov.cn/csrc/xwfb/index.shtml",
        "https://www.csrc.gov.cn/csrc/c100120/common_list.shtml",
    ]
    sections = ["证监会要闻", "统计信息"]
    render_mode = "static"
    pagination = "load_more"
    pagination_max = 3

    def parse_list_page(self, html: str, page_url: str) -> list[ArticleLink]:
        soup = BeautifulSoup(html, "lxml")
        links = []
        seen = set()

        # Branch: common_list.shtml (统计信息) vs xwfb (新闻发布)
        if "/c100120/" in page_url:
            return self._parse_common_list(soup, page_url)

        for a in soup.select("a[href]"):
            href = a.get("href", "").strip()
            if not href:
                continue
            if "/csrc/" not in href or not href.endswith("/content.shtml"):
                continue

            title = a.get_text(strip=True)
            if not title or len(title) < 6:
                continue

            full_url = self.make_absolute_url(href, page_url)
            if full_url in seen:
                continue
            seen.add(full_url)

            section = self._section_from_url(href)
            if section not in self.sections:
                continue

            date_str = self._date_from_adjacent(a)

            links.append(ArticleLink(
                title=title,
                url=full_url,
                date_str=date_str,
                section=section,
            ))

        return links

    def _parse_common_list(self, soup, page_url: str) -> list[ArticleLink]:
        """Parse /csrc/c100120/common_list.shtml — simple <ul> list."""
        links = []
        seen = set()
        # Second <ul> under .statistics-content is the article list
        uls = soup.select(".statistics-content ul")
        target_ul = uls[1] if len(uls) >= 2 else None
        if not target_ul:
            # Fallback: find <a> with /c100120/ pattern
            for a in soup.select("a[href]"):
                href = a.get("href", "").strip()
                if "/c100120/" in href and href.endswith("/content.shtml"):
                    title = a.get_text(strip=True)
                    full_url = self.make_absolute_url(href, page_url)
                    if full_url in seen or not title:
                        continue
                    seen.add(full_url)
                    date_str = self._date_from_li_text(a.parent)
                    links.append(ArticleLink(
                        title=title, url=full_url,
                        date_str=date_str, section="统计信息",
                    ))
            return links

        for li in target_ul.select("li"):
            a = li.find("a")
            if not a:
                continue
            href = a.get("href", "").strip()
            title = a.get_text(strip=True)
            if not href or not title:
                continue
            full_url = self.make_absolute_url(href, page_url)
            if full_url in seen:
                continue
            seen.add(full_url)
            # Date is text node after <a> tag
            date_str = self._date_from_li_text(li)
            links.append(ArticleLink(
                title=title, url=full_url,
                date_str=date_str, section="统计信息",
            ))
        return links

    def _date_from_li_text(self, el) -> str:
        """Extract YYYY-MM-DD date from <li> text after the <a> tag."""
        import re
        text = el.get_text(strip=True)
        m = re.search(r'(\d{4}-\d{2}-\d{2})', text)
        return m.group(1) if m else ""

    def parse_article_page(self, html: str, url: str) -> Article | None:
        soup = BeautifulSoup(html, "lxml")

        # CSRC has site-wide <h1>政府网站年度报表</h1> on every page — use h2 first
        title_el = (
            soup.select_one(".article-title")
            or soup.select_one("h2")
            or soup.select_one("[class*=art-title]")
        )
        if not title_el:
            for h in soup.select("h1"):
                t = h.get_text(strip=True)
                if t and t != "政府网站年度报表" and len(t) > 10:
                    title_el = h
                    break
        if not title_el:
            title_el = soup.select_one("title")
        title = title_el.get_text(strip=True) if title_el else ""

        # Date: CSRC uses YYYY-MM-DD or MM-DD format
        date_str = ""
        date_el = soup.select_one(".time, .date, .info, [class*=date], [class*=time]")
        if date_el:
            raw = date_el.get_text(strip=True)
            date_str = self._normalize_date(raw)

        section = self._section_from_url(url)

        # Body
        body_parts = []
        for sel in [".article-content", ".content", ".TRS_Editor", "#zoom", ".main-content"]:
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

    def _section_from_url(self, href: str) -> str:
        if "c100120" in href:
            return "统计信息"
        if "c100028" in href or "c106311" in href:
            return "证监会要闻"
        elif "c100029" in href:
            return "新闻发布会"
        elif "c100039" in href:
            return "政策解读"
        return ""

    def _date_from_adjacent(self, a_tag) -> str:
        """CSRC shows dates as MM-DD in text nodes between <a> tags."""
        parent = a_tag.parent
        if parent:
            full_text = parent.get_text(" ", strip=True)
            title = a_tag.get_text(strip=True)
            # Check if title itself contains a full date with year
            m_full = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', title)
            if m_full:
                return f"{m_full.group(1)}-{int(m_full.group(2)):02d}-{int(m_full.group(3)):02d}"
            # Find MM-DD after the title
            idx = full_text.find(title)
            if idx >= 0:
                after = full_text[idx + len(title):idx + len(title) + 20]
                m = re.search(r'(\d{2})-(\d{2})', after)
                if m:
                    year = date.today().year
                    month, day = int(m.group(1)), int(m.group(2))
                    # If this MM-DD is in the future, it's from last year
                    try:
                        candidate = date(year, month, day)
                        if candidate > date.today():
                            year -= 1
                    except ValueError:
                        pass
                    return f"{year}-{m.group(1)}-{m.group(2)}"
            # Fallback: any MM-DD in parent
            m = re.search(r'(\d{2})-(\d{2})', full_text)
            if m:
                year = date.today().year
                month, day = int(m.group(1)), int(m.group(2))
                try:
                    if date(year, month, day) > date.today():
                        year -= 1
                except ValueError:
                    pass
                return f"{year}-{m.group(1)}-{m.group(2)}"
        return ""

    def _normalize_date(self, raw: str) -> str:
        m = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', raw)
        if m:
            return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        m = re.search(r'(\d{4}-\d{2}-\d{2})', raw)
        if m:
            return m.group(1)
        m = re.match(r'^(\d{2})-(\d{2})$', raw.strip())
        if m:
            return f"{date.today().year}-{m.group(1)}-{m.group(2)}"
        return raw.strip()
