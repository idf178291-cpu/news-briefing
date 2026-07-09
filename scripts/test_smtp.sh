#!/bin/bash
# 快速 SMTP 测试 — 发一封纯文本测试邮件
set -e

export SMTP_HOST="smtp.qiye.aliyun.com"
export SMTP_PORT="465"
export SMTP_USER="wangkangyu@bank-risk.cn"
export SMTP_PASS="wangkangyu123"
export SMTP_FROM="wangkangyu@bank-risk.cn"
export SMTP_TO="wangkangyu.zh@ccb.com"

TMP_HTML=$(mktemp /tmp/news_briefing_test_XXXXXX.html)
cat > "$TMP_HTML" << 'HTMLEOF'
<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"></head>
<body><h2>SMTP 测试邮件</h2><p>新闻简报邮件配置测试，连接正常。</p></body></html>
HTMLEOF

cd /Users/idf/.openclaw/workspace/skills/news-briefing/scripts
/Users/idf/.openclaw/workspace/skills/news-briefing/venv/bin/python3 -c "
from mailer import Mailer
m = Mailer()
print(f'连接 {m.host}:{m._resolve_port()[0]} ...')
m.send(
    html_path='$TMP_HTML',
    date_str='SMTP Test',
    source_stats={'测试': 1},
    total_articles=0,
)
print('✅ SMTP 发送成功!')
"

rm -f "$TMP_HTML"
