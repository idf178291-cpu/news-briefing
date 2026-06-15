"""国家统计局 — https://www.stats.gov.cn/"""

from .base import BaseSource, ArticleLink, Article
from bs4 import BeautifulSoup
import re


class StatsGovSource(BaseSource):
    name = "国家统计局"
    slug = "stats"
    base_url = "https://www.stats.gov.cn"
    list_url = "https://www.stats.gov.cn/xw/tjxw/"
    list_urls = [
        "https://www.stats.gov.cn/xw/tjxw/",    # 统计新闻 (tjdt sub-pages now live here)
        "https://www.stats.gov.cn/sj/zxfb/",    # 数据发布
        "https://www.stats.gov.cn/sj/sjjd/",    # 数据解读
    ]
    sections = ["统计新闻", "统计动态", "数据发布", "数据解读"]
    render_mode = "static"
    pagination = "none"

    def parse_list_page(self, html: str, page_url: str) -> list[ArticleLink]:
        soup = BeautifulSoup(html, "lxml")

        if "/sj/" in page_url:
            return self._parse_sj_page(soup, page_url)
        return self._parse_xw_page(soup, page_url)

    def _parse_xw_page(self, soup, page_url: str) -> list[ArticleLink]:
        """Parse /xw/ news pages (统计新闻, 统计动态, 通知公告)."""
        links = []
        section_map = {
            "tjxw": "统计新闻", "tjdt": "统计动态",
        }
        seen = set()

        for a in soup.select("a[href]"):
            href = a.get("href", "")
            if not href:
                continue
            # Skip external links
            if href.startswith("http") and "stats.gov.cn" not in href:
                continue

            # Prefer title attr (full text) over truncated display text
            title = a.get("title") or a.get_text(strip=True)
            if not title or len(title) < 6:
                continue

            for path_key, section_name in section_map.items():
                if f"/{path_key}/" in href:
                    full_url = self.make_absolute_url(href, page_url)
                    if full_url in seen:
                        continue
                    seen.add(full_url)
                    date_str = self._date_from_url(href)
                    links.append(ArticleLink(
                        title=title, url=full_url,
                        date_str=date_str, section=section_name,
                    ))
                    break
        return links

    def _parse_sj_page(self, soup, page_url: str) -> list[ArticleLink]:
        """Parse /sj/ data pages (数据发布, 数据解读).

        Each <li> has 3 redundant <a> tags (responsive design) + trailing date text.
        We use the first <a>'s title attr and the last text token as the date.
        """
        links = []
        section_map = {"zxfb": "数据发布", "sjjd": "数据解读"}
        seen = set()

        # Determine section from page_url
        page_section = ""
        for pk, sn in section_map.items():
            if f"/{pk}/" in page_url:
                page_section = sn
                break
        if not page_section:
            return links

        for li in soup.select("li"):
            a_tags = li.find_all("a", href=True)
            if not a_tags:
                continue
            href = a_tags[0].get("href", "").strip()
            if not href:
                continue
            # Article links look like: ./202606/t20260610_1963923.html
            title = a_tags[0].get("title") or a_tags[0].get_text(strip=True)
            if not title or len(title) < 6:
                continue
            # Skip external links (footer sidebar of government sites)
            if href.startswith("http") and "stats.gov.cn" not in href:
                continue
            # Must match stats article URL pattern
            if not re.search(r'/t\d{8}_\d+', href) and not re.search(r'/\d{6}/t\d{8}', href):
                continue

            full_url = self.make_absolute_url(href, page_url)
            if full_url in seen:
                continue
            seen.add(full_url)

            # Date: last token in <li> text is YYYY-MM-DD
            li_text = li.get_text()
            m = re.search(r'(\d{4}-\d{2}-\d{2})\s*$', li_text.strip())
            date_str = m.group(1) if m else self._date_from_url(href)

            links.append(ArticleLink(
                title=title, url=full_url,
                date_str=date_str, section=page_section,
            ))
        return links

    def parse_article_page(self, html: str, url: str) -> Article | None:
        soup = BeautifulSoup(html, "lxml")

        # Title
        title_el = soup.select_one(".xw-tit") or soup.select_one("h1")
        if not title_el:
            title_el = soup.select_one("title")
        title = title_el.get_text(strip=True) if title_el else ""
        # Strip " - 国家统计局" suffix
        if title and "-" in title:
            title = title.rsplit("-", 1)[0].strip()
        # Also strip "国家统计局" suffix without dash
        if title.endswith("国家统计局"):
            title = title[:-5].strip()

        # Date: try multiple formats and locations
        date_str = ""
        # 1. <meta name="PubDate"> (new page structure)
        pub_meta = soup.select_one('meta[name="PubDate"]')
        if pub_meta and pub_meta.get("content"):
            date_str = pub_meta["content"]  # "2026/06/05 19:34"
        # 2. Class-based selectors (old page structure)
        if not date_str:
            date_el = soup.select_one(".xw-time") or soup.select_one(".time")
            if date_el:
                date_str = date_el.get_text(strip=True) if hasattr(date_el, "get_text") else str(date_el)
        # 3. h2 with date pattern (e.g. "2026/06/05 19:34 来源：...")
        if not date_str:
            for h in soup.select("h2"):
                t = h.get_text(strip=True)
                if re.search(r'\d{4}/\d{1,2}/\d{1,2}', t):
                    date_str = t
                    break
        # 4. YYYY年MM月DD日 pattern — but exclude noise like "切换上线"
        if not date_str:
            date_el = soup.find(string=re.compile(r"\d{4}年\d{1,2}月\d{1,2}日"))
            if date_el:
                t = str(date_el)
                if "切换" not in t and "上线" not in t:
                    date_str = t

        if date_str:
            # YYYY/MM/DD HH:MM (sj pages)
            m = re.search(r'(\d{4})/(\d{1,2})/(\d{1,2})', date_str)
            if m:
                date_str = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
            else:
                # YYYY年MM月DD日
                m = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', date_str)
                if m:
                    date_str = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
                else:
                    # YYYY-MM-DD
                    m = re.search(r'(\d{4}-\d{2}-\d{2})', date_str)
                    if m:
                        date_str = m.group(1)

        # Section from URL
        section = ""
        for pk, sn in {"tjxw": "统计新闻", "tjdt": "统计动态",
                       "tzgg": "通知公告", "zxfb": "数据发布",
                       "sjjd": "数据解读"}.items():
            if f"/{pk}/" in url:
                section = sn
                break

        # Body
        body_parts = []
        for sel in [".TRS_Editor", ".xw-con", ".content", ".article-content", "#zoom"]:
            container = soup.select_one(sel)
            if container:
                for p in container.find_all(["p", "div"]):
                    text = p.get_text(strip=True)
                    if text and len(text) > 10:
                        body_parts.append(text)
                break

        if not body_parts and soup.body:
            body_parts.append(soup.body.get_text(separator="\n", strip=True) if soup.body else "")

        body = "\n\n".join(body_parts)
        return Article(
            title=title, url=url, date_str=date_str,
            source=self.slug, section=section,
            body=body[:10000],
        )

    def _date_from_url(self, href: str) -> str:
        m = re.search(r'/t(\d{8})_', href)
        if m:
            d = m.group(1)
            return f"{d[:4]}-{d[4:6]}-{d[6:8]}"
        return ""
