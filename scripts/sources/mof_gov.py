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
    date_tolerance_days = 1  # URL date (tYYYYMMDD_) may be 1 day before actual publish date
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

            # Skip external / non-news / non-article links
            if any(d in href for d in self.SKIP_DOMAINS):
                continue
            # MOF article URLs contain /tYYYYMMDD_<id>.htm pattern
            if not re.search(r'/t\d{8}_\d+\.htm', href):
                continue
            # Determine section based on page URL
            if "/zhengcefabu/" in page_url:
                section = "政策发布"
                if "/zhengcefabu/" not in href and "/caizhengxinwen/" not in href and "/ywgg/" not in href:
                    continue
            else:
                section = "财政新闻"
                # Main page features articles from all subdomains; don't filter by path

            full_url = self.make_absolute_url(href, page_url)
            if full_url in seen:
                continue
            seen.add(full_url)

            # Prefer displayed date over URL date (they can differ by days)
            date_str = ""
            parent = a.parent
            if parent:
                date_span = parent.select_one(".date, .time, span:last-child")
                if date_span:
                    date_str = date_span.get_text(strip=True)
            if not date_str:
                date_str = self._date_from_url(href)

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
        # Strip suffix like "-财政部网站" but not internal hyphens like "世界银行-中国"
        if title and "-" in title:
            suffix = title.rsplit("-", 1)[-1].strip()
            if len(suffix) <= 8:  # short suffix = site name, not part of title
                title = title.rsplit("-", 1)[0].strip()

        # Date: prefer dedicated selectors, then look for "发布日期" in page text
        date_str = ""
        date_el = soup.select_one(".xw-time") or soup.select_one(".time")
        if date_el:
            raw = date_el.get_text(strip=True)
            m = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', raw)
            if m:
                date_str = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        if not date_str:
            # Search for "发布日期" — only look at text after the label
            for el in soup.select("div, span, td, p, font"):
                text = el.get_text(strip=True)
                idx = text.find("发布日期")
                if idx >= 0:
                    m = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', text[idx:])
                    if m:
                        date_str = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
                        break

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
