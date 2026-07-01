"""国务院 — https://www.gov.cn/zhengce/zuixin/"""

from .base import BaseSource, ArticleLink, Article
from bs4 import BeautifulSoup
import re


class GovCnSource(BaseSource):
    name = "国务院"
    slug = "govcn"
    base_url = "https://www.gov.cn"
    list_url = "https://www.gov.cn/zhengce/zuixin/"
    sections = ["最新政策"]
    render_mode = "spa"
    pagination = "none"
    skip_title_keywords = ["微博", "微信", "客户端", "移动应用", "招聘", "录用", "遴选", "任职资格", "拟录用"]
    WAIT_SELECTORS = ["span.date", "a[href*='content_']"]

    def parse_list_page(self, html: str, page_url: str) -> list[ArticleLink]:
        soup = BeautifulSoup(html, "lxml")
        links = []
        seen = set()

        # Pair dates with links by index
        date_els = soup.select("span.date")
        dates = [d.get_text(strip=True) for d in date_els]

        idx = 0
        for a in soup.select("a[href]"):
            href = a.get("href", "").strip()
            if not href:
                continue
            if "content_" not in href:
                continue

            title = a.get_text(strip=True)
            if not title or len(title) < 8:
                continue

            full_url = self.make_absolute_url(href, page_url)
            if full_url in seen:
                continue
            seen.add(full_url)

            date_str = dates[idx] if idx < len(dates) else ""
            idx += 1

            links.append(ArticleLink(
                title=title,
                url=full_url,
                date_str=date_str,
                section="最新政策",
            ))

        return links

    def parse_article_page(self, html: str, url: str) -> Article | None:
        soup = BeautifulSoup(html, "lxml")

        title_el = soup.select_one("h1") or soup.select_one(".title") or soup.select_one("[class*=title]")
        title = title_el.get_text(strip=True) if title_el else ""

        # Date — prefer "发布日期" over "成文日期" (both may be in same text block)
        date_str = ""
        for el in soup.select("div, span, p, td"):
            text = el.get_text(strip=True)
            if "发布日期" in text:
                # Only search the segment starting from "发布日期"
                idx = text.index("发布日期")
                m = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', text[idx:])
                if m and 2025 <= int(m.group(1)) <= 2027:
                    date_str = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
                    break
        # Fallback: first valid date
        if not date_str:
            for el in soup.select("div, span, p, td"):
                text = el.get_text(strip=True)
                m = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', text)
                if m and 2025 <= int(m.group(1)) <= 2027:
                    date_str = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
                    break

        # Body
        body_parts = []
        for sel in [".article-con", ".content", ".TRS_Editor", "#UCAP-CONTENT", ".pages_content"]:
            container = soup.select_one(sel)
            if container:
                for p in container.find_all(["p", "div"]):
                    text = p.get_text(strip=True)
                    if text and len(text) > 15:
                        body_parts.append(text)
                break

        if not body_parts and soup.body:
            body_parts.append(soup.body.get_text(separator="\n", strip=True))

        return Article(
            title=title,
            url=url,
            date_str=date_str,
            source=self.slug,
            section="最新政策",
            body="\n\n".join(body_parts)[:10000],
        )
