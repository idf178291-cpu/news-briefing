from dataclasses import dataclass, field
from abc import ABC, abstractmethod
from datetime import date


@dataclass
class ArticleLink:
    title: str
    url: str
    date_str: str  # as it appears on the list page
    section: str = ""


@dataclass
class Article:
    title: str
    url: str
    date_str: str
    source: str
    section: str
    body: str  # raw text content
    attachment_tables: list[dict] = field(default_factory=list)  # [{filename, sheet_name, html}, ...]


TAG_CATEGORIES = [
    "领导讲话", "对外交流", "政策发布", "政策解读", "数据发布",
    "监管动态", "人事任免", "会议纪要", "通知公告", "国际合作",
]


@dataclass
class BriefingItem:
    """Final structured output for one article."""
    title: str
    date_str: str
    source: str
    section: str
    url: str
    core_event: str = ""
    personnel: list[str] = field(default_factory=list)
    departments: list[str] = field(default_factory=list)
    key_points: list[str] = field(default_factory=list)
    summary: str = ""
    tags: list[str] = field(default_factory=list)
    attachment_tables: list[dict] = field(default_factory=list)  # [{filename, sheet_name, html}, ...]


class BaseSource(ABC):
    name: str = ""
    slug: str = ""
    base_url: str = ""
    list_url: str = ""
    sections: list[str] = []  # subsection names to monitor on the list page
    render_mode: str = "static"  # "static" | "spa"
    pagination: str = "none"  # "none" | "page" | "load_more"
    pagination_max: int = 1  # max page clicks / load-more clicks
    encoding: str = "utf-8"
    list_urls: list[str] = []  # multiple list URLs (merged into one source)
    date_tolerance_days: int = 0  # extra days to accept at list stage (URL date may differ from publish date)
    skip_title_keywords: list[str] = ["人员招聘", "人事任免", "任职资格", "会见", "拟录用", "遴选", "公开招聘", "聘用"]  # filter out articles whose title contains these

    @staticmethod
    def find_attachments(soup, base_url: str, page_url: str = "") -> list[tuple[str, str]]:
        """Find attachment links in article HTML. Returns [(full_url, filename), ...]."""
        from urllib.parse import urljoin
        attachments = []
        for a in soup.select("a[href]"):
            href = a.get("href", "").strip()
            if not href:
                continue
            if any(href.lower().endswith(ext) for ext in
                   (".pdf", ".xls", ".xlsx", ".doc", ".docx", ".csv")):
                full_url = urljoin(page_url or base_url, href)
                import os
                filename = os.path.basename(href.split("?")[0]) or href.rsplit("/", 1)[-1]
                attachments.append((full_url, filename))
        return attachments

    @abstractmethod
    def parse_list_page(self, html: str, page_url: str) -> list[ArticleLink]:
        """Extract article links from a list-page HTML string."""

    @abstractmethod
    def parse_article_page(self, html: str, url: str) -> Article | None:
        """Extract article content from a detail-page HTML string."""

    def make_absolute_url(self, href: str, page_url: str = "") -> str:
        """Resolve a relative href. Uses page_url if provided, else base_url."""
        from urllib.parse import urljoin
        base = page_url or self.base_url
        return urljoin(base, href)

    def is_within_window(self, date_str: str, days_back: int, today: date | None = None) -> bool:
        """Check if date_str is within the configured time window."""
        from datetime import timedelta
        parsed = self._parse_date(date_str)
        if parsed is None:
            return True  # keep if we can't parse — don't miss articles
        ref = today or date.today()
        delta = (ref - parsed).days
        if delta < 0:
            return False  # future date — bad parse, skip
        return delta < days_back

    def _parse_date(self, date_str: str) -> date | None:
        """Try common Chinese gov date formats. Override if source differs."""
        import re
        from datetime import datetime
        formats = [
            "%Y-%m-%d",
            "%Y年%m月%d日",
            "%Y/%m/%d",
            "%m-%d",
            "%m月%d日",
        ]
        for fmt in formats:
            try:
                return datetime.strptime(date_str.strip(), fmt).date()
            except ValueError:
                continue
        # Try YYYY-MM-DD subset
        m = re.search(r'(\d{4})-(\d{1,2})-(\d{1,2})', date_str)
        if m:
            try:
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                pass
        return None
