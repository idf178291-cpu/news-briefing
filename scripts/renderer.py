"""Jinja2 HTML renderer for the news briefing."""

import os
from datetime import datetime
from jinja2 import Environment, FileSystemLoader
from sources.base import BriefingItem


class Renderer:
    def __init__(self, template_dir: str | None = None):
        if template_dir is None:
            template_dir = os.path.join(os.path.dirname(__file__), "..", "templates")
        self.env = Environment(
            loader=FileSystemLoader(os.path.abspath(template_dir)),
            autoescape=False,
        )

    def render(self, items_by_source: list[dict], output_path: str, display_date: str | None = None):
        """Render briefing items grouped by source to an HTML file.

        items_by_source: list of dicts with keys: name, slug, article_count, articles
          where articles is a list of BriefingItem objects.
        """
        total = sum(src["article_count"] for src in items_by_source)
        template = self.env.get_template("briefing.html")
        html = template.render(
            date_str=display_date or datetime.now().strftime("%Y-%m-%d"),
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
            sources=items_by_source,
            total_articles=total,
        )
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)
        return output_path

    def pdf(self, html_path: str, output_path: str) -> str:
        """Convert a rendered HTML file to a single-page PDF via Playwright.

        Full-page screenshot at 2x → single-page PDF via img2pdf.
        This preserves all CSS colors that Chrome's native PDF engine strips."""
        from playwright.sync_api import sync_playwright
        import tempfile

        VW = 750

        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(
                viewport={"width": VW, "height": 900},
                device_scale_factor=2,
            )
            page.goto(f"file://{os.path.abspath(html_path)}", wait_until="networkidle")
            page.evaluate("() => { document.body.classList.add('pdf-mode'); }")
            page.wait_for_timeout(300)

            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                png_path = tmp.name

            page.screenshot(path=png_path, full_page=True)
            browser.close()

        self._png_to_pdf(png_path, output_path)
        os.unlink(png_path)
        return output_path

    @staticmethod
    def _png_to_pdf(png_path: str, output_path: str):
        """Convert a PNG screenshot to a single-page A4-width PDF."""
        from PIL import Image
        import img2pdf

        img = Image.open(png_path)
        w, h = img.size

        a4_w_pt = img2pdf.mm_to_pt(210)
        a4_h_pt = img2pdf.mm_to_pt(297)
        page_h_pt = a4_w_pt * h / w

        # Ensure single page — use a taller page if content exceeds A4
        layout = img2pdf.get_layout_fun(
            pagesize=(a4_w_pt, max(page_h_pt, a4_h_pt))
        )
        with open(output_path, "wb") as f:
            f.write(img2pdf.convert(png_path, layout_fun=layout))
