"""Playwright-based scraper for both static and SPA pages."""

from playwright.sync_api import sync_playwright, Page, Browser
from bs4 import BeautifulSoup


class Scraper:
    def __init__(self, headless: bool = True, timeout: int = 30000):
        self.headless = headless
        self.timeout = timeout
        self._playwright = None
        self._browser: Browser | None = None
        self._page_pool: list[Page] = []

    def start(self):
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self.headless)

    def stop(self):
        for p in self._page_pool:
            try: p.close()
            except: pass
        self._page_pool.clear()
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()

    def borrow_page(self) -> Page:
        """Get a reusable page. For detail scraping to avoid new_page/close per article."""
        if self._page_pool:
            return self._page_pool.pop()
        return self._browser.new_page()

    def return_page(self, page: Page):
        """Return page to pool for reuse."""
        self._page_pool.append(page)

    def navigate(self, page: Page, url: str, wait_ms: int = 1000) -> str:
        """Navigate existing page to url, return HTML. Much faster than new_page+close."""
        page.goto(url, wait_until="domcontentloaded", timeout=self.timeout)
        page.wait_for_timeout(wait_ms)
        return page.content()

    def fetch_page(self, url: str, wait_for: str | list[str] | None = None,
                   wait_ms: int = 3000, retries: int = 3) -> str:
        """Navigate to url, return HTML content.

        wait_for: CSS selector(s) to wait for. If list, tries each until one matches.
        wait_ms: fallback wait in ms after navigation.
        retries: max retry attempts on transient network errors (ERR_NETWORK_CHANGED etc.)
        """
        last_error = None
        for attempt in range(retries):
            page: Page = self._browser.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=self.timeout)
                if wait_for:
                    selectors = [wait_for] if isinstance(wait_for, str) else wait_for
                    found = False
                    for sel in selectors:
                        try:
                            page.wait_for_selector(sel, timeout=8000)
                            found = True
                            break
                        except Exception:
                            continue
                    if not found:
                        page.wait_for_timeout(wait_ms)
                else:
                    page.wait_for_timeout(wait_ms)
                return page.content()
            except Exception as e:
                last_error = e
                if attempt < retries - 1 and ("ERR_NETWORK_CHANGED" in str(e) or "ERR_INTERNET_DISCONNECTED" in str(e) or "ERR_CONNECTION" in str(e)):
                    print(f"  ⚠ 网络瞬时错误，重试 {attempt + 2}/{retries} ...")
                    import time
                    time.sleep(2)
                else:
                    raise
            finally:
                page.close()
        raise last_error

    def click_load_more(self, url: str, button_selector: str,
                        clicks: int = 3, wait_ms: int = 1500) -> str:
        """For 'load more' pagination: click button N times, return final HTML."""
        page: Page = self._browser.new_page()
        try:
            page.goto(url, wait_until="commit", timeout=self.timeout)
            page.wait_for_timeout(wait_ms)
            for _ in range(clicks):
                try:
                    btn = page.query_selector(button_selector)
                    if btn and btn.is_visible():
                        btn.click()
                        page.wait_for_timeout(wait_ms)
                    else:
                        break
                except Exception:
                    break
            return page.content()
        finally:
            page.close()

    def click_next_pages(self, url: str, link_selector: str,
                         pages: int = 3, wait_ms: int = 1500) -> list[str]:
        """For numbered pagination: return list of HTML strings for N pages."""
        results = []
        page: Page = self._browser.new_page()
        try:
            page.goto(url, wait_until="commit", timeout=self.timeout)
            page.wait_for_timeout(wait_ms)
            results.append(page.content())
            for _ in range(pages - 1):
                try:
                    next_link = page.query_selector(link_selector)
                    if next_link and next_link.is_visible():
                        next_link.click()
                        page.wait_for_timeout(wait_ms)
                        results.append(page.content())
                    else:
                        break
                except Exception:
                    break
            return results
        finally:
            page.close()

    @staticmethod
    def to_soup(html: str) -> BeautifulSoup:
        return BeautifulSoup(html, "lxml")

    @staticmethod
    def download_attachments(attachment_links: list[tuple[str, str]]) -> str:
        """Download attachment files and extract text content.

        attachment_links: list of (url, filename) tuples
        Returns extracted text appended together, or empty string.
        """
        import tempfile, os, re
        try:
            import requests as req
        except ImportError:
            print("[Scraper] requests not available, skipping attachments")
            return ""

        extracted_parts = []
        for url, filename in attachment_links:
            try:
                print(f"  [Scraper] 下载附件: {filename}")
                resp = req.get(url, timeout=30, headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
                })
                resp.raise_for_status()
                content = resp.content
                ext = os.path.splitext(filename)[1].lower()

                text = ""
                if ext in (".pdf",):
                    text = Scraper._extract_pdf(content)
                elif ext in (".xlsx", ".xls"):
                    text = Scraper._extract_xlsx(content, ext)
                elif ext in (".docx",):
                    text = Scraper._extract_docx(content)
                elif ext in (".csv", ".txt", ".md"):
                    text = content.decode("utf-8", errors="replace")[:8000]
                else:
                    # Try as text
                    try:
                        text = content.decode("utf-8")[:8000]
                    except UnicodeDecodeError:
                        print(f"  [Scraper] 无法解析: {filename}")
                        continue

                if text.strip():
                    extracted_parts.append(f"--- {filename} ---\n{text}")
            except Exception as e:
                print(f"  [Scraper] 附件下载失败 {filename}: {e}")

        return "\n\n".join(extracted_parts)

    @staticmethod
    def _extract_pdf(content: bytes) -> str:
        try:
            import pdfplumber, io
            text_parts = []
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                for page in pdf.pages[:5]:  # first 5 pages
                    t = page.extract_text()
                    if t:
                        text_parts.append(t)
            return "\n".join(text_parts)[:8000]
        except ImportError:
            pass
        try:
            from PyPDF2 import PdfReader
            import io
            reader = PdfReader(io.BytesIO(content))
            return "\n".join(p.extract_text() or "" for p in reader.pages[:5])[:8000]
        except ImportError:
            return ""

    @staticmethod
    def _extract_xlsx(content: bytes, ext: str) -> str:
        if ext == ".csv":
            return content.decode("utf-8", errors="replace")[:8000]
        try:
            import openpyxl, io
            wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
            parts = []
            for sn in wb.sheetnames[:3]:  # first 3 sheets
                ws = wb[sn]
                parts.append(f"[Sheet: {sn}]")
                rows = []
                for row in ws.iter_rows(max_row=30, values_only=True):
                    rows.append("\t".join(str(c) if c is not None else "" for c in row))
                parts.append("\n".join(rows))
            return "\n".join(parts)[:8000]
        except ImportError:
            return ""
        except Exception as e:
            print(f"  [Scraper] XLSX解析失败: {e}")
            return ""

    @staticmethod
    def _extract_docx(content: bytes) -> str:
        # Try python-docx first (handles .docx / Open XML)
        try:
            from docx import Document
            import io
            doc = Document(io.BytesIO(content))
            return "\n".join(p.text for p in doc.paragraphs[:50])[:8000]
        except ImportError:
            pass
        except Exception:
            pass  # May be old .doc format (OLE2), try fallback

        # Fallback for old .doc format (OLE2/CFB) — use macOS textutil
        if content[:4] == b'\xd0\xcf\x11\xe0':
            return Scraper._extract_ole_doc(content)
        return ""

    @staticmethod
    def _extract_ole_doc(content: bytes) -> str:
        """Extract text from old .doc (OLE2) using macOS textutil or olefile."""
        import subprocess, tempfile, os
        # Method 1: macOS textutil (built-in)
        try:
            with tempfile.NamedTemporaryFile(suffix='.doc', delete=False) as f:
                f.write(content)
                tmp = f.name
            result = subprocess.run(
                ['textutil', '-convert', 'txt', tmp, '-stdout'],
                capture_output=True, text=True, timeout=30,
            )
            os.unlink(tmp)
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout[:8000]
        except Exception:
            pass

        # Method 2: olefile + manual extraction
        try:
            import olefile
            ole = olefile.OleFileIO(content)
            if ole.exists('WordDocument'):
                # Read the WordDocument stream — crude but works for simple docs
                stream = ole.openstream('WordDocument').read()
                # Try to extract readable text (UTF-16LE encoded in OLE docs)
                text = stream.decode('utf-16-le', errors='ignore')
                # Filter to printable CJK + ASCII
                import re
                cleaned = re.sub(r'[^一-鿿　-〿＀-￯a-zA-Z0-9\s.,;:!?()（）【】《》、。，；：！？\d%+\-*/=]', '', text)
                if len(cleaned) > 100:
                    ole.close()
                    return cleaned[:8000]
                ole.close()
        except ImportError:
            pass
        except Exception:
            pass

        return ""
