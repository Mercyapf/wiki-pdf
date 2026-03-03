import frappe
import pdfkit
import markdown2
import base64
import os
import re
import tempfile
from bs4 import BeautifulSoup
from frappe.core.doctype.file.utils import find_file_by_url
from urllib.parse import urlparse, unquote
from frappe import _

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG & HELPERS
# ─────────────────────────────────────────────────────────────────────────────

_MD_EXTRAS = ["tables", "fenced-code-blocks", "strike", "cuddled-lists", "break-on-newline", "header-ids", "footnotes"]

def _md_to_html(text):
    if not text: return ""
    return markdown2.markdown(text, extras=_MD_EXTRAS)

def _find_page(route):
    """Robust lookup for Wiki Page by route."""
    if not route: return None
    route = route.strip("/")
    # Try exact, suffix, or containing match
    for query in [route, route.split("/")[-1], f"%/{route.split('/')[-1]}", f"%{route}%"]:
        # Use get_value with LIKE if query has %
        if "%" in str(query):
            match = frappe.db.get_value("Wiki Page", {"route": ["like", query]}, "name")
        else:
            match = frappe.db.get_value("Wiki Page", {"route": query}, "name")
        if match: return match
    return None

def _inline_images(html):
    """Ensure images work in PDF by resolving local paths or inlining base64."""
    soup = BeautifulSoup(html, "html.parser")
    for img in soup.find_all("img"):
        src = img.get("src")
        if not src or src.startswith("data:"): continue
        
        # 1x1 transparent pixel fallback
        fallback = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
        
        try:
            # Handle encoded URLs (spaces, etc.)
            real_src = unquote(src)
            
            if real_src.startswith("/files/"):
                # Handle standard Frappe /files/ path
                path = frappe.get_site_path("public", "files", real_src.split("/")[-1])
                if os.path.exists(path):
                    img["src"] = os.path.abspath(path)
                    continue

            # Fallback to inlining if it's a URL or if path resolution failed
            path = real_src
            if "://" not in real_src or real_src.startswith(frappe.utils.get_url()):
                # Resolve relative or same-site URL
                path = urlparse(real_src).path
                file_doc = find_file_by_url(path)
                if file_doc and os.path.exists(file_doc.get_full_path()):
                    img["src"] = os.path.abspath(file_doc.get_full_path())
                else:
                    img["src"] = fallback
            else:
                # External images: keep as is but wkhtmltopdf might fail without network
                pass
        except Exception:
            img["src"] = fallback
    return str(soup)

def _split_tables(html, max_rows=15):
    """Splits large tables into groups of `max_rows` rows so page-break-inside:avoid works."""
    def _get_thead(table_html):
        m = re.search(r'(<thead[^>]*>.*?</thead>)', table_html, re.DOTALL | re.IGNORECASE)
        if m: return m.group(1)
        first = re.search(r'(<tr[^>]*>.*?</tr>)', table_html, re.DOTALL | re.IGNORECASE)
        return f'<thead>{first.group(1)}</thead>' if first else ''

    def _get_colgroup(table_html):
        m = re.search(r'(<colgroup[^>]*>.*?</colgroup>)', table_html, re.DOTALL | re.IGNORECASE)
        return m.group(1) if m else ''

    def _get_tbody_rows(table_html):
        tbody = re.search(r'<tbody[^>]*>(.*?)</tbody>', table_html, re.DOTALL | re.IGNORECASE)
        src = tbody.group(1) if tbody else table_html
        return re.findall(r'<tr[^>]*>.*?</tr>', src, re.DOTALL | re.IGNORECASE)

    TABLE_STYLE = 'width:100%;border-collapse:collapse;table-layout:fixed;font-size:10pt;margin:0;page-break-inside:avoid;'

    def process_table(match):
        table_html = match.group(0)
        thead, colgroup, rows = _get_thead(table_html), _get_colgroup(table_html), _get_tbody_rows(table_html)
        if len(rows) <= max_rows:
            return re.sub(r'<table([^>]*)>', lambda m: f'<table{m.group(1)} style="{TABLE_STYLE}">', table_html, 1, re.IGNORECASE)
        
        chunks = [rows[i:i + max_rows] for i in range(0, len(rows), max_rows)]
        parts = []
        for idx, chunk in enumerate(chunks):
            continued = f'<div style="font-size:9pt;color:#555;text-align:right;margin-top:4pt;">(continued...)</div>' if idx > 0 else ''
            parts.append(f'{continued}<table style="{TABLE_STYLE}">{colgroup}{thead}<tbody>{"".join(chunk)}</tbody></table>')
        return '\n<div style="margin:4pt 0;"></div>\n'.join(parts)

    return re.sub(r'<table[^>]*>.*?</table>', process_table, html, flags=re.DOTALL | re.IGNORECASE)

def _clean_for_pdf(html):
    def replace_media(match):
        src = re.search(r'src=["\']([^"\']+)["\']', match.group(0))
        if src:
            url = src.group(1)
            if "youtube.com/embed/" in url:
                video_id = url.split("embed/")[1].split("?")[0]
                url = f"https://www.youtube.com/watch?v={video_id}"
            return f'<div style="border:1px solid #ccc;background:#f9f9f9;padding:6pt 10pt;margin:6pt 0;"><a href="{url}">Watch Video: {url}</a></div>'
        return match.group(0)

    html = re.sub(r'<(iframe|video)[^>]*>.*?</\1>', replace_media, html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<details[^>]*>', '<div style="display:block;margin:6pt 0;">', html, flags=re.IGNORECASE)
    html = re.sub(r'</details>', '</div>', html, flags=re.IGNORECASE)
    html = re.sub(r'<summary[^>]*>', '<span style="font-weight:bold;">', html, flags=re.IGNORECASE)
    html = re.sub(r'</summary>', '</span><br>', html, flags=re.IGNORECASE)
    return _split_tables(html)

# ─────────────────────────────────────────────────────────────────────────────
# CSS & FOOTER
# ─────────────────────────────────────────────────────────────────────────────

PDF_CSS = """
@page { size: A4; margin: 15mm 18mm; }
body { font-family: Georgia, serif; font-size: 11pt; line-height: 1.4; color: #111; margin: 0; padding: 0; }
h1.group-name { font-size: 20pt; font-weight: bold; border-bottom: 2px solid #333; padding-bottom: 4pt; margin-bottom: 14pt; page-break-after: avoid; }
h1.page-title { color: #1a52a0; font-size: 16pt; font-weight: bold; margin-bottom: 12pt; page-break-after: avoid; }
h1, h2, h3, h4 { color: #222; margin-top: 14pt; margin-bottom: 6pt; page-break-after: avoid; }
p { margin: 4pt 0; }
img { max-width: 100%; height: auto; display: block; margin: 8pt 0; }
table { width: 100%; border-collapse: collapse; margin: 8pt 0; table-layout: fixed; font-size: 10pt; }
thead { display: table-header-group; }
th, td { border: 1px solid #aaa; padding: 4pt 6pt; vertical-align: top; word-break: break-word; line-height: 1.2; }
th { background-color: #eee; font-weight: bold; text-align: left; }
blockquote { border: 1px solid #bbb; border-left: 4pt solid #555; background: #f7f7f7; padding: 8pt 14pt; margin: 8pt 0; page-break-inside: avoid; }
pre, code { background: #f4f4f4; font-family: monospace; border-radius: 3px; }
pre { padding: 8pt; border: 1px solid #ddd; white-space: pre-wrap; margin: 6pt 0; page-break-inside: avoid; }
"""

FOOTER_HTML = """<!DOCTYPE html><html><head><script>
function subst() {
    var vars = {};
    var qs = document.location.search.substring(1).split('&');
    for (var i in qs) { if (qs.hasOwnProperty(i)) { var kv = qs[i].split('=', 2); vars[kv[0]] = decodeURI(kv[1]); } }
    var cls = ['page'];
    for (var c in cls) { if (cls.hasOwnProperty(c)) { 
        var els = document.getElementsByClassName(cls[c]);
        for (var j = 0; j < els.length; ++j) { els[j].textContent = vars[cls[c]]; }
    } }
}
</script></head><body style="margin:0;" onload="subst()">
<div style="font-family:Georgia,serif;font-size:10pt;text-align:center;width:100%;"><span class="page"></span></div>
</body></html>"""

def _write_footer():
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8") as f:
        f.write(FOOTER_HTML)
        return f.name

def _pdf_options(footer_path):
    return {
        "page-size": "A4", "margin-top": "15mm", "margin-bottom": "18mm", "margin-left": "18mm", "margin-right": "18mm",
        "encoding": "UTF-8", "quiet": "", "enable-local-file-access": "", "footer-html": footer_path, "footer-spacing": "5",
        "load-error-handling": "ignore", "load-media-error-handling": "ignore", "disable-smart-shrinking": ""
    }

def _wrap(body):
    return f"<html><head><meta charset='UTF-8'><style>{PDF_CSS}</style></head><body>{body}</body></html>"

# ─────────────────────────────────────────────────────────────────────────────
# MAIN ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

@frappe.whitelist(allow_guest=True)
def download_wiki_pdf(page_name=None, route=None):
    """Download single Wiki page or current page and its siblings in space."""
    try:
        target_name = page_name or _find_page(route)
        if not target_name: frappe.throw(f"Wiki Page not found: {route or page_name}")
        
        page_doc = frappe.get_doc("Wiki Page", target_name, ignore_permissions=True)
        wiki_group_item = frappe.db.get_value("Wiki Group Item", {"wiki_page": target_name}, ["parent"], as_dict=True)

        groups = []
        if not wiki_group_item:
            groups.append({"label": None, "pages": [{"title": page_doc.title, "content_html": _clean_for_pdf(_md_to_html(page_doc.content or ""))}]})
        else:
            sidebar = frappe.get_all("Wiki Group Item", filters={"parent": wiki_group_item.parent}, fields=["wiki_page", "parent_label"], order_by="idx asc", ignore_permissions=True, limit=0)
            p_names = [s.wiki_page for s in sidebar if s.wiki_page]
            p_map = {p.name: p for p in frappe.get_all("Wiki Page", filters={"name": ["in", p_names]}, fields=["name", "title", "content"], ignore_permissions=True, limit=0)}
            
            for s in sidebar:
                if s.wiki_page in p_map:
                    p = p_map[s.wiki_page]
                    label = s.parent_label or ""
                    if not groups or groups[-1]["label"] != label: groups.append({"label": label, "pages": []})
                    groups[-1]["pages"].append({"title": p.title, "content_html": _clean_for_pdf(_md_to_html(p.content or ""))})

        body_parts = []
        for i, group in enumerate(groups):
            g_html = f'<div style="{"page-break-before:always;" if i > 0 else ""}">'
            if group["label"]: g_html += f'<h1 class="group-name">{group["label"]}</h1>'
            for p_idx, page in enumerate(group["pages"]):
                pb = 'style="page-break-before:always;"' if p_idx > 0 else ""
                g_html += f'<div {pb}><h1 class="page-title">{page["title"]}</h1>{page["content_html"]}</div>'
            g_html += '</div>'
            body_parts.append(g_html)

        html = _inline_images(_wrap("\n".join(body_parts)))
        footer_path = _write_footer()
        try:
            pdf_bin = pdfkit.from_string(html, options=_pdf_options(footer_path))
        finally:
            if footer_path and os.path.exists(footer_path): os.remove(footer_path)

        # Build filename
        filename = page_doc.title
        if wiki_group_item:
             space_name = frappe.db.get_value("Wiki Space", wiki_group_item.parent, "space_name")
             filename = space_name or filename
        
        frappe.local.response.filename = f"{filename or 'Wiki'}.pdf".replace(" ", "_")
        frappe.local.response.filecontent = pdf_bin
        frappe.local.response.type = "download"

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Wiki PDF Error")
        frappe.throw(f"Error: {str(e)}")

@frappe.whitelist(allow_guest=True)
def download_full_wiki_space(wiki_space):
    """Download entire space by wiki_space route name."""
    try:
        root_name = frappe.get_doc("Wiki Page", {"route": wiki_space}, ignore_permissions=True).name
        
        # Front/Back Covers
        covers = {"front": "", "back": ""}
        try:
            settings = frappe.get_single("Wiki PDF Settings")
            for pos in ["front", "back"]:
                ctype = getattr(settings, f"{pos}_cover_type")
                if ctype == "Standard":
                    if pos == "front":
                        covers[pos] = f'<h1 style="text-align:center;padding-top:40%;font-size:48pt;">{wiki_space}</h1>'
                    else:
                        path = frappe.get_app_path("wiki_pdf", "public", "images", "back_cover.jpg")
                        if os.path.exists(path):
                            covers[pos] = f'<div style="width:100%;height:1100px;background-image:url(\'file://{os.path.abspath(path)}\');background-size:cover;background-position:center;"></div>'
                elif ctype == "Custom HTML":
                    covers[pos] = getattr(settings, f"{pos}_cover_html")
                elif ctype == "Image":
                    img_url = getattr(settings, f"{pos}_cover_image")
                    if img_url:
                        if img_url.startswith("/files/"):
                            path = frappe.get_site_path("public", "files", img_url.split("/")[-1])
                            if os.path.exists(path):
                                covers[pos] = f'<div style="width:100%;height:1100px;background-image:url(\'file://{os.path.abspath(path)}\');background-size:cover;background-position:center;"></div>'
        except: pass

        # Pages
        all_pages = frappe.get_all("Wiki Page", filters={"published": 1}, fields=["name", "title", "content", "parent_wiki_page"], order_by="creation asc", ignore_permissions=True, limit=0)
        pages = [p for p in all_pages if p.name == root_name or p.parent_wiki_page == root_name]
        
        body_parts = []
        if covers["front"]:
            body_parts.append(f'<div style="page-break-after:always;">{covers["front"]}</div>')
        
        for i, p in enumerate(pages):
            pb = "page-break-before:always;" if (i > 0 or covers["front"]) else ""
            html = _clean_for_pdf(_md_to_html(p.content or ""))
            body_parts.append(f'<div style="{pb}"><h1 class="page-title">{p.title}</h1>{html}</div>')
        
        if covers["back"]: 
            body_parts.append(f'<div style="page-break-before:always;">{covers["back"]}</div>')

        html = _inline_images(_wrap("\n".join(body_parts)))
        footer_path = _write_footer()
        try:
            pdf_bin = pdfkit.from_string(html, options=_pdf_options(footer_path))
        finally:
            if footer_path and os.path.exists(footer_path): os.remove(footer_path)

        frappe.local.response.filename = f"{wiki_space}.pdf".replace(" ", "_")
        frappe.local.response.filecontent = pdf_bin
        frappe.local.response.type = "download"

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Wiki Full Space PDF Error")
        frappe.throw(f"Error: {str(e)}")