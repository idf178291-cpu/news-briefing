"""SMTP email sender for news briefing — stdlib only, no external dependencies.

Configuration via environment variables:
  SMTP_HOST  (required) — SMTP server hostname
  SMTP_PORT  (optional) — 465=SSL, 587=STARTTLS (default), 25=plain
  SMTP_USER  (optional) — login username
  SMTP_PASS  (optional) — login password
  SMTP_TO    (required) — comma-separated recipient addresses
  SMTP_CC    (optional) — comma-separated CC addresses
  SMTP_FROM  (optional) — sender address (defaults to SMTP_USER)
"""

import os
import ssl
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from email.utils import formatdate


class Mailer:
    def __init__(self):
        self.host = os.environ.get("SMTP_HOST", "")
        self.port_str = os.environ.get("SMTP_PORT", "")
        self.user = os.environ.get("SMTP_USER", "")
        self.password = os.environ.get("SMTP_PASS", "")
        self.to_addrs = os.environ.get("SMTP_TO", "")
        self.cc_addrs = os.environ.get("SMTP_CC", "")
        self.from_addr = os.environ.get("SMTP_FROM", self.user or "")

        missing = []
        if not self.host:
            missing.append("SMTP_HOST")
        if not self.to_addrs:
            missing.append("SMTP_TO")
        if missing:
            raise ValueError(
                f"缺少必需的 SMTP 环境变量: {', '.join(missing)}。"
                f"请设置 SMTP_HOST 和 SMTP_TO（可选: SMTP_PORT, SMTP_USER, SMTP_PASS, SMTP_CC, SMTP_FROM）。"
            )

    def _resolve_port(self) -> tuple[int, bool, bool]:
        """Return (port, use_ssl, use_starttls) based on SMTP_PORT."""
        port = int(self.port_str) if self.port_str else 587
        use_ssl = port == 465
        use_starttls = port == 587 or not self.port_str
        return port, use_ssl, use_starttls

    @staticmethod
    def _ssl_context():
        """Return SSL context. Use insecure only if SMTP_INSECURE_SSL=1 is explicitly set."""
        if os.environ.get("SMTP_INSECURE_SSL") == "1":
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            return ctx
        return ssl.create_default_context()

    def send(self, html_path: str, date_str: str,
             source_stats: dict[str, int], total_articles: int) -> bool:
        """Compose and send the briefing email with HTML attachment."""

        # ── build plain text summary ─────────────────────────
        lines = [f"宏观形势及金融相关管理机构动态每日简报 — {date_str}", ""]
        lines.append("数据源统计:")
        for name, count in sorted(source_stats.items()):
            lines.append(f"  {name}: {count} 篇")
        lines.append(f"合计: {total_articles} 篇")
        lines.append("")
        lines.append("完整简报内容请查看附件。")
        lines.append("本简报由AI自动生成，数据来源于各监管机构官方网站。")
        plain_text = "\n".join(lines)

        # ── read rendered HTML ───────────────────────────────
        with open(html_path, "r", encoding="utf-8") as f:
            html_content = f.read()

        # ── build multipart message ──────────────────────────
        msg = MIMEMultipart("mixed")
        msg["Subject"] = f"宏观形势及金融相关管理机构动态每日简报 — {date_str}"
        msg["From"] = self.from_addr
        msg["To"] = self.to_addrs
        if self.cc_addrs:
            msg["Cc"] = self.cc_addrs
        msg["Date"] = formatdate(localtime=True)

        # multipart/alternative: plain text + HTML inline
        alternative = MIMEMultipart("alternative")
        alternative.attach(MIMEText(plain_text, "plain", "utf-8"))
        alternative.attach(MIMEText(html_content, "html", "utf-8"))
        msg.attach(alternative)

        # attach HTML file
        html_filename = os.path.basename(html_path)
        html_att = MIMEBase("text", "html", filename=html_filename)
        with open(html_path, "rb") as f:
            html_att.set_payload(f.read())
        encoders.encode_base64(html_att)
        html_att.add_header("Content-Disposition", "attachment", filename=html_filename)
        msg.attach(html_att)

        # ── resolve recipients ───────────────────────────────
        all_recipients = [a.strip() for a in self.to_addrs.split(",") if a.strip()]
        if self.cc_addrs:
            all_recipients.extend(a.strip() for a in self.cc_addrs.split(",") if a.strip())

        # ── send ─────────────────────────────────────────────
        port, use_ssl, use_starttls = self._resolve_port()
        if use_ssl:
            with smtplib.SMTP_SSL(self.host, port, context=self._ssl_context()) as server:
                if self.user and self.password:
                    server.login(self.user, self.password)
                server.sendmail(self.from_addr, all_recipients, msg.as_string())
        else:
            with smtplib.SMTP(self.host, port) as server:
                server.ehlo()
                if use_starttls:
                    server.starttls(context=self._ssl_context())
                    server.ehlo()
                if self.user and self.password:
                    server.login(self.user, self.password)
                server.sendmail(self.from_addr, all_recipients, msg.as_string())

        return True
