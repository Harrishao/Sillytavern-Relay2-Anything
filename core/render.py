"""
Markdown → 图片渲染模块
将列表文本渲染为暗色主题 PNG 图片，用于 QQ 等不支持富文本的平台
"""
import os
import re
import markdown

from . import browser as _browser_mod

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    width: {width}px;
    font-family: "Microsoft YaHei", "PingFang SC", "Noto Sans SC", sans-serif;
    font-size: 16px;
    line-height: 1.75;
    color: #e0e0e0;
    background: #2b2b2b;
    padding: 24px 20px;
    word-break: break-word;
}
h1 { font-size: 1.5em; margin: 16px 0 8px; border-bottom: 2px solid #4A90D9; padding-bottom: 4px; }
h2 { font-size: 1.3em; margin: 14px 0 6px; }
h3 { font-size: 1.15em; margin: 12px 0 4px; }
p { margin: 6px 0; }
ul, ol { padding-left: 24px; margin: 6px 0; }
li { margin: 2px 0; }
blockquote {
    border-left: 4px solid #4A90D9;
    padding: 4px 12px;
    margin: 8px 0;
    background: #1e1e1e;
    color: #aaa;
}
code {
    background: #1e1e1e;
    padding: 1px 5px;
    border-radius: 3px;
    font-family: "Cascadia Code", "Fira Code", "Consolas", monospace;
    font-size: 0.9em;
}
pre {
    background: #2d2d2d;
    color: #f8f8f2;
    padding: 14px 16px;
    border-radius: 6px;
    overflow-x: auto;
    margin: 8px 0;
    font-size: 0.88em;
    line-height: 1.5;
}
pre code { background: none; padding: 0; color: inherit; }
table { border-collapse: collapse; width: 100%; margin: 8px 0; }
th, td { border: 1px solid #444; padding: 8px 10px; text-align: left; }
th { background: #1e1e1e; font-weight: 600; }
hr { border: none; border-top: 1px solid #444; margin: 12px 0; }
a { color: #6db3f2; }
strong { font-weight: 600; }
.rendered-html { margin: 8px 0; padding: 0; }
.rendered-html > * { margin: 4px 0; }
</style>
</head>
<body>
{body}
</body>
</html>"""


def _clean_message(text: str) -> str:
    """清洗 CQ 码和 XML 标签残留"""
    text = re.sub(r'\[CQ:[^\]]*\]', '', text)
    text = re.sub(r'<\?xml[^?]*\?>', '', text)
    text = re.sub(r'<UpdateVariable>.*?</UpdateVariable>', '', text, flags=re.DOTALL)
    text = re.sub(r'<JSONPatch>.*?</JSONPatch>', '', text, flags=re.DOTALL)
    text = re.sub(r'<div[^>]*TH-collapse-code-block-button[^>]*>[^<]*</div>', '', text)
    return text.strip()


def _sanitize_html_block(html_block: str) -> str:
    """剥离外层 html/head/body 标签，保留 style 和 body 内容"""
    has_doctype = bool(re.search(r'<!DOCTYPE\s+html', html_block, re.IGNORECASE))
    has_html_tag = bool(re.search(r'<html[\s>]', html_block, re.IGNORECASE))
    if not has_doctype and not has_html_tag:
        return html_block

    styles = re.findall(r'<style[^>]*>(.*?)</style>', html_block, re.DOTALL | re.IGNORECASE)
    body_match = re.search(r'<body[^>]*>(.*?)</body>', html_block, re.DOTALL | re.IGNORECASE)
    if body_match:
        inner = body_match.group(1).strip()
    else:
        inner = html_block
        for tag in ['<!DOCTYPE[^>]*>', '</?html[^>]*>', '</?head[^>]*>',
                     '</?body[^>]*>', '<meta[^>]*>', '<title[^>]*>.*?</title>']:
            inner = re.sub(tag, '', inner, flags=re.DOTALL | re.IGNORECASE)
        inner = inner.strip()

    inner = re.sub(r'<script[^>]*>.*?</script>', '', inner, flags=re.DOTALL | re.IGNORECASE)
    inner = re.sub(r'<link[^>]*>', '', inner, flags=re.IGNORECASE)

    if styles:
        scoped_styles = []
        for s in styles:
            s = re.sub(r'body\s*\{[^}]*\}', '', s)
            s = re.sub(r'html\s*\{[^}]*\}', '', s)
            s = re.sub(r'\*\s*\{[^}]*\}', '', s)
            if s.strip():
                scoped_styles.append(s)
        if scoped_styles:
            style_block = '<style>\n' + '\n'.join(scoped_styles) + '\n</style>'
            inner = style_block + '\n' + inner

    return inner


def _markdown_to_html(text: str) -> str:
    html_blocks = []

    def _extract(m):
        html_blocks.append(_sanitize_html_block(m.group(1)))
        return f"<!--HTML_BLOCK_{len(html_blocks) - 1}-->"

    processed = re.sub(
        r'```html\s*\n(.*?)```', _extract, text, flags=re.DOTALL
    )

    md = markdown.Markdown(extensions=['fenced_code', 'tables', 'codehilite', 'nl2br'])
    html = md.convert(processed)

    for i, block in enumerate(html_blocks):
        html = html.replace(
            f'<!--HTML_BLOCK_{i}-->',
            f'<div class="rendered-html">{block}</div>'
        )

    return html


async def render_to_image(markdown_text: str, output_dir: str, width: int = 600) -> str | None:
    """将 markdown 文本渲染为 PNG 图片"""
    if not markdown_text or not markdown_text.strip():
        return None

    os.makedirs(output_dir, exist_ok=True)

    cleaned = _clean_message(markdown_text)
    html_body = _markdown_to_html(cleaned)
    html = HTML_TEMPLATE.format(width=width, body=html_body)

    filename = "nc_render.png"
    output_path = os.path.join(output_dir, filename)

    tmp_html = os.path.join(output_dir, "_tmp_render.html")
    with open(tmp_html, "w", encoding="utf-8") as f:
        f.write(html)

    try:
        if _browser_mod._browser is None:
            print("[core] 渲染需要浏览器但浏览器未初始化", flush=True)
            return None
        page = await _browser_mod._browser.new_page(viewport={"width": width + 40, "height": 600})
        await page.goto(f"file:///{tmp_html.replace(os.sep, '/')}", wait_until="networkidle")
        await page.screenshot(path=output_path, full_page=True)
        await page.close()
        print(f"[core] 渲染图片已保存: {output_path}", flush=True)
        return output_path
    except Exception as e:
        print(f"[core] 渲染失败: {e}", flush=True)
        return None
    finally:
        try:
            os.remove(tmp_html)
        except OSError:
            pass
