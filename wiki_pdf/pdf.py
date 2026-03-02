import frappe
from frappe.utils.pdf import get_pdf
from frappe import _
import re
import markdown2


# ─────────────────────────────────────────────────────────────────────────────
# Markdown → HTML
# ─────────────────────────────────────────────────────────────────────────────

_MD_EXTRAS = [
    "tables",
    "fenced-code-blocks",
    "strike",
    "cuddled-lists",
    "break-on-newline",
    "header-ids",
    "footnotes",
]


def _md_to_html(text):
    """Convert markdown text to HTML using markdown2."""
    if not text:
        return ""
    return markdown2.markdown(text, extras=_MD_EXTRAS)


# ─────────────────────────────────────────────────────────────────────────────
# Post-process: replace iframes / videos / details for PDF
# ─────────────────────────────────────────────────────────────────────────────

def _split_tables(html, max_rows=15):
    """
    Split large tables into groups of `max_rows` body rows.
    Each group becomes its own <table> with the original <thead> repeated
    and `page-break-inside:avoid` at the TABLE level.

    Why this works:
      - wkhtmltopdf does NOT honour page-break-inside:avoid on <tr> or <td>
        (regardless of inline vs stylesheet).
      - wkhtmltopdf DOES honour page-break-inside:avoid on a <table> element.
      - So we split large tables into small sub-tables; each sub-table fits
        on one page and stays whole.
    """

    def _get_thead(table_html):
        m = re.search(r'(<thead[^>]*>.*?</thead>)', table_html, re.DOTALL | re.IGNORECASE)
        if m:
            return m.group(1)
        # No <thead>: treat the first <tr> as the header
        first = re.search(r'(<tr[^>]*>.*?</tr>)', table_html, re.DOTALL | re.IGNORECASE)
        if first:
            return f'<thead>{first.group(1)}</thead>'
        return ''

    def _get_colgroup(table_html):
        m = re.search(r'(<colgroup[^>]*>.*?</colgroup>)', table_html, re.DOTALL | re.IGNORECASE)
        return m.group(1) if m else ''

    def _get_tbody_rows(table_html):
        tbody = re.search(r'<tbody[^>]*>(.*?)</tbody>', table_html, re.DOTALL | re.IGNORECASE)
        src = tbody.group(1) if tbody else table_html
        return re.findall(r'<tr[^>]*>.*?</tr>', src, re.DOTALL | re.IGNORECASE)

    def _get_table_open_attrs(table_html):
        m = re.match(r'<table([^>]*)>', table_html, re.IGNORECASE)
        return m.group(1) if m else ''

    TABLE_STYLE = (
        'width:100%;border-collapse:collapse;table-layout:fixed;font-size:10pt;'
        'margin:0 0 0 0;page-break-inside:avoid;break-inside:avoid;'
    )

    def process_table(match):
        table_html = match.group(0)
        thead = _get_thead(table_html)
        colgroup = _get_colgroup(table_html)
        rows = _get_tbody_rows(table_html)

        if len(rows) <= max_rows:
            # Small table: just stamp page-break-inside:avoid on the table tag
            fixed = re.sub(
                r'<table([^>]*)>',
                lambda m: f'<table{m.group(1)} style="{TABLE_STYLE}">',
                table_html, count=1, flags=re.IGNORECASE
            )
            return fixed

        # Large table: split into sub-tables of max_rows
        chunks = [rows[i:i + max_rows] for i in range(0, len(rows), max_rows)]
        parts = []
        for idx, chunk in enumerate(chunks):
            # Add "Continued..." label for continuation chunks (2nd onwards)
            continued = (
                '<div style="font-size:9pt;color:#555;text-align:right;margin-top:4pt;">'
                '(continued from previous page)</div>' if idx > 0 else ''
            )
            tbody_html = '\n'.join(chunk)
            sub_table = (
                f'{continued}'
                f'<table style="{TABLE_STYLE}">'
                f'{colgroup}'
                f'{thead}'
                f'<tbody>{tbody_html}</tbody>'
                f'</table>'
            )
            parts.append(sub_table)

        # Separate sub-tables with a tiny gap so they don't visually merge
        return '\n<div style="margin:4pt 0;"></div>\n'.join(parts)

    html = re.sub(r'<table[^>]*>.*?</table>', process_table, html, flags=re.DOTALL | re.IGNORECASE)
    return html


def _clean_for_pdf(html):
    def replace_iframe(match):
        src = re.search(r'src=["\']([^"\']+)["\']', match.group(0))
        if src:
            url = src.group(1)
            if "youtube.com/embed/" in url:
                video_id = url.split("embed/")[1].split("?")[0]
                url = f"https://www.youtube.com/watch?v={video_id}"
            return f'<div class="pdf-video-link"><a href="{url}">Watch Video: {url}</a></div>'
        return match.group(0)

    def replace_video(match):
        src = re.search(r'src=["\']([^"\']+)["\']', match.group(0))
        if src:
            url = src.group(1)
            return f'<div class="pdf-video-link"><a href="{url}">Watch Video: {url}</a></div>'
        return "<!-- video removed -->"

    html = re.sub(r'<iframe[^>]*>.*?</iframe>', replace_iframe, html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<video[^>]*>.*?</video>', replace_video, html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<details[^>]*>', '<div class="pdf-details">', html, flags=re.IGNORECASE)
    html = re.sub(r'</details>', '</div>', html, flags=re.IGNORECASE)
    html = re.sub(r'<summary[^>]*>', '<span class="pdf-summary">', html, flags=re.IGNORECASE)
    html = re.sub(r'</summary>', '</span><br>', html, flags=re.IGNORECASE)

    # Split large tables → multiple sub-tables so page-break-inside:avoid works
    html = _split_tables(html)
    return html


# ─────────────────────────────────────────────────────────────────────────────
# CSS
# ─────────────────────────────────────────────────────────────────────────────

PDF_CSS = """
@page {
    size: A4;
    margin-top: 15mm;
    margin-bottom: 18mm;
    margin-left: 18mm;
    margin-right: 18mm;
}

html, body {
    margin: 0; padding: 0;
    font-family: Georgia, serif;
    font-size: 12pt;
    line-height: 1.5;
    color: #111;
}

/* ── Group heading (Introduction / HR Structure) ── */
h1.group-name {
    font-size: 20pt;
    font-weight: bold;
    font-family: Georgia, serif;
    border-bottom: 2px solid #333;
    padding-bottom: 4pt;
    margin: 0 0 14pt 0;
    color: #111;
    page-break-after: avoid;
}

/* ── Page title ── */
h1.page-title {
    font-size: 16pt;
    font-weight: bold;
    font-family: Georgia, serif;
    margin: 0 0 12pt 0;
    color: #1a52a0;
    page-break-after: avoid;
}

/* ── Content headings (from markdown # ## ### etc.) ── */
h1 { font-size: 17pt; font-weight: bold; margin: 12pt 0 6pt 0; color: #111; page-break-after: avoid; }
h2 { font-size: 16pt; font-weight: bold; margin: 10pt 0 5pt 0; color: #111; page-break-after: avoid; }
h3 { font-size: 15pt; font-weight: bold; margin:  8pt 0 4pt 0; color: #111; page-break-after: avoid; }
h4 { font-size: 14pt; font-weight: bold; margin:  6pt 0 3pt 0; color: #111; page-break-after: avoid; }
h5, h6 { font-size: 13pt; font-weight: bold; margin: 5pt 0 2pt 0; color: #111; }

p   { margin: 4pt 0; }
li  { margin-bottom: 2pt; }
ul, ol { padding-left: 18pt; margin: 4pt 0; }

b, strong { font-weight: bold; }
em, i     { font-style: italic; }
s, del    { text-decoration: line-through; }

a { color: #1a6fa8; text-decoration: underline; }

img { max-width: 100%; height: auto; }

hr { border: 0; border-top: 1px solid #bbb; margin: 10pt 0; }

code {
    font-family: "Courier New", monospace;
    font-size: 11pt;
    background: #f4f4f4;
    padding: 1pt 3pt;
}

pre {
    font-family: "Courier New", monospace;
    font-size: 10pt;
    background: #f4f4f4;
    border: 1px solid #ddd;
    padding: 8pt;
    margin: 6pt 0;
    white-space: pre-wrap;
    word-wrap: break-word;
    page-break-inside: avoid;
}

/* ── Blockquote → full box (callout card style) ── */
blockquote {
    border: 1px solid #bbb;
    border-left: 4pt solid #555;
    border-radius: 3pt;
    background: #f7f7f7;
    margin: 8pt 0;
    padding: 8pt 14pt;
    page-break-inside: avoid;
}

/* ── Tables ── */
table {
    width: 100%;
    border-collapse: collapse;
    margin: 8pt 0;
    table-layout: fixed;        /* columns share width evenly → no overflow */
    font-size: 10pt;            /* smaller font → shorter rows → cleaner breaks */
}

/* Repeat header on every page when table spans multiple pages */
thead {
    display: table-header-group;
}

th {
    background-color: #eee;
    font-weight: bold;
    border: 1px solid #aaa;
    padding: 2pt 5pt;
    text-align: left;
    vertical-align: top;
    word-break: break-word;
    overflow-wrap: break-word;
    line-height: 1.2;
}

td {
    border: 1px solid #aaa;
    padding: 2pt 5pt;
    vertical-align: top;
    word-break: break-word;
    overflow-wrap: break-word;
    line-height: 1.2;
}

/* ── Video links ── */
.pdf-video-link {
    border: 1px solid #ccc;
    background: #f9f9f9;
    padding: 6pt 10pt;
    margin: 6pt 0;
    display: block;
}

.pdf-details { display: block; margin: 6pt 0; }
.pdf-summary { font-weight: bold; }
"""

def _pdf_options():
    return {
        "enable-local-file-access": "",
        "disable-smart-shrinking": "",
        "quiet": None,
        "encoding": "UTF-8",
        "page-size": "A4",
        "margin-top": "15mm",
        "margin-bottom": "18mm",
        "margin-left": "18mm",
        "margin-right": "18mm",
        "footer-center": "[page]",
        "footer-font-name": "Georgia",
        "footer-font-size": "10",
        "footer-spacing": "5",
        # Prevent wkhtmltopdf from aborting on network errors in cloud/server environments
        "load-error-handling": "ignore",
        "load-media-error-handling": "ignore",
        "disable-javascript": "",
    }


def _wrap(body):
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>{PDF_CSS}</style>
</head>
<body>{body}</body>
</html>"""


# ─────────────────────────────────────────────────────────────────────────────
# PRIMARY ENDPOINT – called by the Download PDF button
# ─────────────────────────────────────────────────────────────────────────────

@frappe.whitelist(allow_guest=True)
def download_wiki_pdf(page_name=None, route=None):
    """
    Download all pages of the Wiki Space that contains `page_name` as one PDF.

    PDF structure:
        Introduction              ← group heading (h1.group-name)
          Home                    ← page title (h1.page-title)
          [Content with headings rendered from markdown]
          ---page break---
          Design
          [Content …]
        ---page break---
        HR Structure
          Roles
          [Content …]

    Tables are kept whole on a single page.
    """
    if not page_name and not route:
        frappe.throw(_("Page Name or Route is required"))

    if not page_name and route:
        if route.endswith("/"):
            route = route[:-1]
        page_name = frappe.db.get_value("Wiki Page", {"route": route}, "name")
        if not page_name:
            frappe.throw(_("Wiki Page not found for route: {0}").format(route))

    page_doc = frappe.get_doc("Wiki Page", page_name)
    page_doc.check_permission("read")

    # ── 1. Find the Wiki Space ────────────────────────────────────────────────
    wiki_group_item = frappe.db.get_value(
        "Wiki Group Item", {"wiki_page": page_name}, ["parent"], as_dict=True
    )

    # ── 2. Build ordered group → pages structure ──────────────────────────────
    groups = []   # [{"label": str, "pages": [{"title":, "content_html":}]}]

    if not wiki_group_item:
        content_html = _clean_for_pdf(_md_to_html(page_doc.content or ""))
        groups.append({"label": None, "pages": [{"title": page_doc.title, "content_html": content_html}]})
    else:
        space_name = wiki_group_item.parent

        sidebar_items = frappe.get_all(
            "Wiki Group Item",
            filters={"parent": space_name},
            fields=["wiki_page", "parent_label", "idx"],
            order_by="idx asc",
        )

        page_names = [item.wiki_page for item in sidebar_items if item.wiki_page]
        pages_data = frappe.get_list(
            "Wiki Page",
            filters={"name": ["in", page_names]},
            fields=["name", "title", "content"],
            limit=len(page_names) + 10,
        )
        pages_map = {row.name: row for row in pages_data}

        for item in sidebar_items:
            if item.wiki_page not in pages_map:
                continue
            p = pages_map[item.wiki_page]
            label = item.parent_label or ""

            if not groups or groups[-1]["label"] != label:
                groups.append({"label": label, "pages": []})

            content_html = _clean_for_pdf(_md_to_html(p.content or ""))
            groups[-1]["pages"].append({"title": p.title, "content_html": content_html})

    # ── 3. Build HTML body ────────────────────────────────────────────────────
    body_parts = []
    first_block = True

    for group in groups:
        pb = "" if first_block else "page-break-before: always;"

        g_html = f'<div style="{pb}">'

        if group["label"]:
            g_html += f'<h1 class="group-name">{group["label"]}</h1>'

        for p_idx, page in enumerate(group["pages"]):
            if p_idx == 0:
                # First page in group: flows directly under group heading
                g_html += f'<h1 class="page-title">{page["title"]}</h1>'
                g_html += page["content_html"]
            else:
                # Subsequent pages: new page
                g_html += f'<div style="page-break-before: always;">'
                g_html += f'<h1 class="page-title">{page["title"]}</h1>'
                g_html += page["content_html"]
                g_html += '</div>'

        g_html += '</div>'
        body_parts.append(g_html)
        first_block = False

    html = _wrap("\n".join(body_parts))

    # ── 4. Filename ───────────────────────────────────────────────────────────
    if wiki_group_item and frappe.db.exists("Wiki Space", wiki_group_item.parent):
        space = frappe.get_doc("Wiki Space", wiki_group_item.parent)
        filename = space.space_name or space.route or page_doc.title
    else:
        filename = page_doc.title

    if not str(filename).lower().endswith(".pdf"):
        filename = f"{filename}.pdf"

    # ── 5. Render PDF ─────────────────────────────────────────────────────────
    frappe.local.response.filecontent = get_pdf(html, options=_pdf_options())
    frappe.local.response.filename = filename
    frappe.local.response.type = "pdf"


# ─────────────────────────────────────────────────────────────────────────────
# SECONDARY ENDPOINT – download entire Wiki Space by route
# ─────────────────────────────────────────────────────────────────────────────

@frappe.whitelist(allow_guest=True)
def download_full_wiki_space(wiki_space):
    """wiki_space = route of the root wiki page, e.g. 'creche-manual'."""
    root = frappe.get_doc("Wiki Page", {"route": wiki_space})

    all_pages = frappe.get_all(
        "Wiki Page",
        filters={"published": 1},
        fields=["name", "title", "content", "route", "parent_wiki_page", "creation"],
        order_by="creation asc",
    )

    pages = [p for p in all_pages if p.name == root.name or p.parent_wiki_page == root.name]

    if not pages:
        frappe.throw(_("No wiki pages found"))

    body_parts = []

    for i, page in enumerate(pages):
        pb = "" if i == 0 else "page-break-before: always;"
        content_html = _clean_for_pdf(_md_to_html(page.content or ""))
        body_parts.append(
            f'<div style="{pb}"><h1 class="page-title">{page.title}</h1>{content_html}</div>'
        )

    html = _wrap("\n".join(body_parts))

    pdf = get_pdf(html, options=_pdf_options())

    space_doc = frappe.db.get_value("Wiki Space", {"route": wiki_space}, ["space_name"], as_dict=True)
    filename = (space_doc.space_name if space_doc else None) or root.title or wiki_space
    if not filename.lower().endswith(".pdf"):
        filename += ".pdf"

    frappe.local.response.filename = filename
    frappe.local.response.filecontent = pdf
    frappe.local.response.type = "pdf"
