"""财政部 — https://www.mof.gov.cn/zhengwuxinxi/"""

from .base import BaseSource, ArticleLink, Article
from bs4 import BeautifulSoup
import re


class MofGovSource(BaseSource):
    name = "财政部"
    slug = "mof"
    base_url = "https://www.mof.gov.cn"
    list_url = "https://www.mof.gov.cn/zhengwuxinxi/"
    list_urls = [
        "https://www.mof.gov.cn/zhengwuxinxi/",
        "https://www.mof.gov.cn/zhengwuxinxi/zhengcefabu/",
    ]
    sections = ["财政新闻", "政策发布"]
    render_mode = "static"
    pagination = "none"

    # External domains to skip
    SKIP_DOMAINS = {"scio.gov.cn", "cctv.com", "cctvnews.cctv.com"}

    def parse_list_page(self, html: str, page_url: str) -> list[ArticleLink]:
        soup = BeautifulSoup(html, "lxml")
        links = []
        seen = set()

        # Target the 财政新闻 section — links under caizhengxinwen path
        for a in soup.select("a[href]"):
            href = a.get("href", "").strip()
            if not href:
                continue
            title = a.get_text(strip=True)
            if not title or len(title) < 8:
                continue

            # Skip external / non-news links
            if any(d in href for d in self.SKIP_DOMAINS):
                continue
            # Determine section based on page URL
            if "/zhengcefabu/" in page_url:
                section = "政策发布"
                if "/zhengcefabu/" not in href and "/caizhengxinwen/" not in href:
                    continue
            else:
                section = "财政新闻"
                if "/caizhengxinwen/" not in href:
                    continue

            full_url = self.make_absolute_url(href, page_url)
            if full_url in seen:
                continue
            seen.add(full_url)

            date_str = self._date_from_url(href)

            # Try to find date in adjacent element
            if not date_str:
                parent = a.parent
                if parent:
                    date_span = parent.select_one(".date, .time, span:last-child")
                    if date_span:
                        date_str = date_span.get_text(strip=True)

            links.append(ArticleLink(
                title=title,
                url=full_url,
                date_str=date_str,
                section=section,
            ))

        return links

    def parse_article_page(self, html: str, url: str) -> Article | None:
        soup = BeautifulSoup(html, "lxml")

        title_el = soup.select_one(".xw-tit") or soup.select_one("h1") or soup.select_one("title")
        title = title_el.get_text(strip=True) if title_el else ""
        if title and "-" in title:
            title = title.rsplit("-", 1)[0].strip()

        # Date
        date_str = ""
        date_el = soup.select_one(".xw-time") or soup.select_one(".time") or soup.find(string=re.compile(r"\d{4}年\d{1,2}月\d{1,2}日"))
        if date_el:
            raw = date_el.get_text(strip=True) if hasattr(date_el, "get_text") else str(date_el)
            m = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', raw)
            if m:
                date_str = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

        # Body
        body_parts = []
        for sel in [".TRS_Editor", ".xw-con", ".content", ".article-con", "#zoom"]:
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
            section="财政新闻",
            body="\n\n".join(body_parts)[:10000],
        )

    def _date_from_url(self, href: str) -> str:
        m = re.search(r'/t(\d{8})_', href)
        if m:
            d = m.group(1)
            return f"{d[:4]}-{d[4:6]}-{d[6:8]}"
        return ""
