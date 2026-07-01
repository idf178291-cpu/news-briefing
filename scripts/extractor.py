"""LLM-based article extraction: structured fields + Chinese summary.

API key discovery order:
1. Explicit api_key + base_url params
2. ANTHROPIC_API_KEY / ANTHROPIC_BASE_URL env vars
3. ~/.claude/settings.json → env block (ANTHROPIC_AUTH_TOKEN, ANTHROPIC_BASE_URL,
   ANTHROPIC_DEFAULT_HAIKU_MODEL)
4. Project-level .claude/settings.local.json
"""

import os
import json
import re
from sources.base import Article, BriefingItem, TAG_CATEGORIES

anthropic = None
try:
    import anthropic
except ImportError:
    pass

try:
    import requests
except ImportError:
    requests = None


EXTRACTION_PROMPT = """你是一名财经新闻分析专家。请从以下新闻文章中提取关键信息，并生成中文摘要。

## 输出格式（严格JSON）
{{
  "core_event": "一句话概括核心事件",
  "personnel": ["姓名1", "姓名2"],
  "departments": ["部门1", "部门2"],
  "key_points": ["要点1", "要点2", "要点3"],
  "summary": "2-4句中文摘要",
  "tags": ["标签1", "标签2"]
}}

## 标签分类（从以下候选中选择1-3个最匹配的）
{tag_categories}

## 提取要求
- **core_event**: 用一句话说清楚发生了什么
- **personnel**: 所有被提及的领导、发言人、负责人姓名（含职务简称如"康义局长"可写"康义"）
- **departments**: 涉及的政府部门、机构、司局名称
- **key_points**: 核心观点、政策要点、数据亮点。领导讲话的每个观点都要保留，不能遗漏
- **summary**: 2-4句完整摘要，覆盖事件+关键信息+影响。领导讲话类必须包含所有核心观点
- **tags**: 从候选标签中选择1-3个最匹配的，只返回标签名

## 特别注意
- 领导讲话/调研/会议：逐条保留观点，不得遗漏、不得扭曲原意
- 政策发布类：提取政策名称、核心内容、生效时间
- 通知公告类：提取事项、时间节点、影响范围
- 数据发布类：提取关键数据和对比变化
- 正文末尾若包含【附件内容】（Excel/PDF提取所得），需将其中的数据要点融入摘要
- 用中文输出，JSON字段全部用中文内容

## 文章信息
标题：{title}
日期：{date_str}
来源：{source_name} - {section}

正文：
{body}
"""


def _discover_credentials():
    """Find API credentials from env or .claude/settings.json.

    Priority:
    1. ANTHROPIC_API_KEY / ANTHROPIC_BASE_URL env vars
    2. ~/.claude/settings.json → env block
    3. Project-level .claude/settings.local.json → env block

    Returns (api_key, base_url, model, provider_api).
    """
    # Priority 1: explicit env vars
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    base_url = os.environ.get("ANTHROPIC_BASE_URL")
    model = os.environ.get("ANTHROPIC_MODEL")

    if api_key:
        return api_key, base_url or None, model or None, "anthropic-messages"

    # Priority 2-3: .claude/settings.json files
    for config_path in [
        os.path.expanduser("~/.claude/settings.json"),
        os.path.join(os.getcwd(), ".claude", "settings.local.json"),
    ]:
        try:
            if not os.path.exists(config_path):
                continue
            cfg = json.loads(open(config_path).read())
            env_block = cfg.get("env", {})

            key = env_block.get("ANTHROPIC_AUTH_TOKEN") or env_block.get("ANTHROPIC_API_KEY")
            url = env_block.get("ANTHROPIC_BASE_URL")
            # Use Haiku-tier model (v4-flash) for extraction — fast, cheap, sufficient
            m = (env_block.get("ANTHROPIC_DEFAULT_HAIKU_MODEL")
                 or env_block.get("CLAUDE_CODE_SUBAGENT_MODEL")
                 or env_block.get("ANTHROPIC_MODEL"))

            if key:
                return key, url or None, m or None, "anthropic-messages"

            return None, None, None, "anthropic-messages"
        except (json.JSONDecodeError, KeyError, OSError):
            continue

    return None, None, None, "anthropic-messages"


class Extractor:
    def __init__(self, api_key: str | None = None, base_url: str | None = None,
                 model: str | None = None, provider_api: str = "anthropic-messages"):
        key, url, discovered_model, discovered_api = api_key, base_url, None, provider_api
        if not key:
            key, url, discovered_model, discovered_api = _discover_credentials()

        self.api_key = key
        self.base_url = url
        self.model = model or discovered_model or "deepseek-v4-flash"
        self.provider_api = discovered_api
        print(f"[Extractor] Using model: {self.model}, api: {self.provider_api}, "
              f"base_url: {self.base_url or 'default'}")

    @property
    def available(self) -> bool:
        return self.api_key is not None

    def _call_api(self, prompt: str) -> str:
        """Call LLM API via anthropic SDK or direct HTTP.

        Supports both anthropic-messages and openai-completions provider APIs.
        """
        if self.provider_api == "openai-completions":
            return self._call_openai_api(prompt)
        return self._call_anthropic_api(prompt)

    @staticmethod
    def _extract_text_from_content_blocks(content: list) -> str:
        """Extract text from anthropic-messages content blocks, skipping thinking blocks."""
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    return block.get("text", "")
                # Also try direct text access for simple format
                if "text" in block and block.get("type") != "thinking":
                    return block["text"]
            elif hasattr(block, "type") and block.type == "text":
                # Handle SDK object
                return block.text
        # Fallback: return first block's text
        if content and isinstance(content[0], dict) and "text" in content[0]:
            return content[0]["text"]
        return ""

    def _call_anthropic_api(self, prompt: str) -> str:
        if anthropic:
            try:
                kwargs = {"api_key": self.api_key}
                if self.base_url:
                    kwargs["base_url"] = self.base_url
                client = anthropic.Anthropic(**kwargs)
                resp = client.messages.create(
                    model=self.model,
                    max_tokens=1024,
                    messages=[{"role": "user", "content": prompt}],
                )
                return self._extract_text_from_content_blocks(resp.content)
            except Exception as e:
                print(f"[Extractor] anthropic SDK failed: {e}, trying direct HTTP...")

        if not self.base_url:
            raise RuntimeError("No base_url available for API call")

        url = f"{self.base_url.rstrip('/')}/v1/messages"
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        }
        payload = {
            "model": self.model,
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": prompt}],
        }
        if requests is None:
            raise RuntimeError("requests module not available")
        resp = requests.post(url, headers=headers, json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        if "content" in data and len(data["content"]) > 0:
            return self._extract_text_from_content_blocks(data["content"])
        if "choices" in data and len(data["choices"]) > 0:
            return data["choices"][0].get("message", {}).get("content", "")
        return ""

    def _call_openai_api(self, prompt: str) -> str:
        if not self.base_url:
            raise RuntimeError("No base_url available for OpenAI-compatible API call")

        url = f"{self.base_url.rstrip('/')}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload = {
            "model": self.model,
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": prompt}],
        }
        if requests is None:
            raise RuntimeError("requests module not available")
        resp = requests.post(url, headers=headers, json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        if "choices" in data and len(data["choices"]) > 0:
            return data["choices"][0].get("message", {}).get("content", "")
        return ""

    def extract(self, article: Article, source_name: str,
                max_body_chars: int = 8000) -> BriefingItem:
        if not self.api_key:
            return BriefingItem(
                title=article.title, date_str=article.date_str,
                source=article.source, section=article.section, url=article.url,
                attachment_tables=article.attachment_tables,
            )

        body = article.body[:max_body_chars]
        prompt = EXTRACTION_PROMPT.format(
            title=article.title,
            date_str=article.date_str,
            source_name=source_name,
            section=article.section,
            body=body,
            tag_categories="、".join(TAG_CATEGORIES),
        )

        data = {}
        last_raw = ""
        for attempt in range(3):
            raw = self._call_api(prompt)
            last_raw = raw
            data = self._parse_json(raw)
            if data.get("summary") and data.get("core_event"):
                break
            if attempt < 2:
                print(f"  ⚠ 摘要缺失，重试中... (第{attempt+1}次)")
            else:
                print(f"  ⚠ 摘要缺失，已达最大重试次数")
                print(f"  ⚠ 原始响应前200字符: {last_raw[:200]}")

        return BriefingItem(
            title=article.title,
            date_str=article.date_str,
            source=article.source,
            section=article.section,
            url=article.url,
            core_event=data.get("core_event", ""),
            personnel=data.get("personnel", []),
            departments=data.get("departments", []),
            key_points=data.get("key_points", []),
            summary=data.get("summary", ""),
            tags=data.get("tags", []),
            attachment_tables=article.attachment_tables,
        )

    def _parse_json(self, raw: str) -> dict:
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            lines = [l for l in lines if not l.startswith("```")]
            raw = "\n".join(lines)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            import re
            m = re.search(r'\{.*\}', raw, re.DOTALL)
            if m:
                return json.loads(m.group())
            return {}
