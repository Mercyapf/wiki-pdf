import frappe
import pdfkit
import markdown2
import base64
import os
import re
import tempfile
import io
from bs4 import BeautifulSoup
from pypdf import PdfReader, PdfWriter
from frappe.core.doctype.file.utils import find_file_by_url
from urllib.parse import urlparse, unquote
from frappe import _

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG & HELPERS
# ─────────────────────────────────────────────────────────────────────────────

_MD_EXTRAS = ["tables", "fenced-code-blocks", "strike", "cuddled-lists", "break-on-newline", "header-ids", "footnotes"]

def _md_to_html(text):
    """Robust markdown to HTML conversion with table-hiding to avoid markdown2 crashes."""
    if not text: return ""
    try:
        # Standard attempt
        return markdown2.markdown(text, extras=_MD_EXTRAS)
    except AssertionError:
        # Markdown2 failed (likely due to a large HTML table). 
        # Hide tables, parse the rest, then re-insert.
        import re
        tables = []
        def _hide(match):
            tables.append(match.group(0))
            return f"\n\nPROTECTEDTABLE{len(tables)-1}\n\n"
        
        hidden_md = re.sub(r'(<table[^>]*>.*?</table>)', _hide, text, flags=re.DOTALL | re.IGNORECASE)
        try:
            html = markdown2.markdown(hidden_md, extras=_MD_EXTRAS)
            for i, table_html in enumerate(tables):
                placeholder = f"PROTECTEDTABLE{i}"
                # Handle potential markdown wrapping
                html = html.replace(f"<p>{placeholder}</p>", table_html)
                html = html.replace(placeholder, table_html)
            return html
        except Exception:
            return f"<pre>{frappe.utils.escape_html(text)}</pre>"
    except Exception as e:
        frappe.log_error(f"Markdown parsing error: {str(e)}", "Wiki PDF Markdown Error")
        return f"<div>Error parsing content: {frappe.utils.escape_html(text[:100])}...</div>"

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
    if not html: return html
    soup = BeautifulSoup(html, "html.parser")
    for img in soup.find_all("img"):
        src = img.get("src")
        if not src or src.startswith("data:"): continue

        # 1x1 transparent pixel fallback
        fallback = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="

        try:
            # Handle encoded URLs (spaces, etc.)
            real_src = unquote(src).strip()
            
            resolved_path = None
            # 1. Try to resolve via find_file_by_url for any local-looking path
            if not real_src.startswith("http") or real_src.startswith(frappe.utils.get_url()):
                # Get the path part (e.g., /files/foo.jpg)
                url_path = urlparse(real_src).path
                file_doc = find_file_by_url(url_path)
                if file_doc and os.path.exists(file_doc.get_full_path()):
                    resolved_path = os.path.abspath(file_doc.get_full_path())
            
            # 2. Fallback for standard /files/ if find_file_by_url failed
            if not resolved_path and real_src.startswith("/files/"):
                fname = real_src.split("/")[-1]
                path = frappe.get_site_path("public", "files", fname)
                if os.path.exists(path):
                    resolved_path = os.path.abspath(path)
                else:
                    # Try direct site path if get_site_path/public/files is tricky
                    alt_path = os.path.join(frappe.get_site_path(), "public", "files", fname)
                    if os.path.exists(alt_path):
                        resolved_path = os.path.abspath(alt_path)

            if resolved_path:
                # Use file:// prefix for absolute paths to be extremely clear for wkhtmltopdf
                img["src"] = f"file://{resolved_path}"
            else:
                # If it's a relative path, maybe try to join with site path
                if not real_src.startswith("/") and not real_src.startswith("http"):
                    test_path = frappe.get_site_path("public", real_src)
                    if os.path.exists(test_path):
                        img["src"] = f"file://{os.path.abspath(test_path)}"

        except Exception as e:
            frappe.log_error(f"Image resolution error for {src}: {str(e)}", "Wiki PDF Image Error")
            img["src"] = fallback
    return str(soup)

def _split_tables(html, max_rows=25):
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

    # Force each chunk to stay on one page if possible (Atomic Chunks)
    TABLE_STYLE = 'width:100%;border-collapse:collapse;table-layout:fixed;font-size:10pt;margin:0;page-break-inside:avoid !important;'

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
h1.group-name { font-size: 22pt; font-weight: bold; border-bottom: 2px solid #333; padding-bottom: 4pt; margin-bottom: 14pt; page-break-after: avoid !important; }
h1.page-title, h2.page-title { color: #1a52a0; font-size: 22pt; font-weight: bold; margin-bottom: 12pt; page-break-after: avoid !important; }
h1 { font-size: 18pt; color: #222; margin-top: 14pt; margin-bottom: 6pt; page-break-after: avoid !important; }
h2 { font-size: 16pt; color: #222; margin-top: 14pt; margin-bottom: 6pt; page-break-after: avoid !important; }
h3 { font-size: 14pt; color: #222; margin-top: 12pt; margin-bottom: 4pt; page-break-after: avoid !important; }
h4 { font-size: 12pt; color: #222; margin-top: 10pt; margin-bottom: 4pt; page-break-after: avoid !important; }
p { margin: 4pt 0; }
img { max-width: 100%; height: auto; display: block; margin: 8pt 0; }
table { width: 100%; border-collapse: collapse; margin: 8pt 0; table-layout: fixed; font-size: 10pt; page-break-inside: auto; }
thead { display: table-header-group !important; }
tr { page-break-inside: avoid; }
th, td { border: 1px solid #aaa; padding: 4pt 6pt; vertical-align: top; word-break: break-word; line-height: 1.2; }
th { background-color: #eee; font-weight: bold; text-align: left; }
blockquote { border: 1px solid #bbb; border-left: 4pt solid #555; background: #f7f7f7; padding: 8pt 14pt; margin: 8pt 0; page-break-inside: avoid; }
pre, code { background: #f4f4f4; font-family: monospace; border-radius: 3px; }
pre { padding: 8pt; border: 1px solid #ddd; white-space: pre-wrap; margin: 6pt 0; page-break-inside: avoid; }
"""

# डिजाइन टोकन for manual TOC
TOC_STYLE = """
<style>
    body { font-family: Georgia, serif; padding: 20mm; margin: 0; color: #111; }
    h1 { font-size: 24pt; font-weight: bold; border-bottom: 2px solid #333; padding-bottom: 10px; margin-bottom: 30px; }
    .toc-container { width: 100%; }
    .toc-item { clear: both; overflow: hidden; margin-bottom: 12pt; line-height: 1.2; }
    .toc-title { float: left; white-space: nowrap; padding-right: 5px; }
    .toc-page { float: right; white-space: nowrap; padding-left: 5px; font-weight: bold; color: #1a52a0; }
    /* This block fills the exactly gap between the floating title and floating page number */
    .toc-line { overflow: hidden; border-bottom: 1px solid #999; height: 1.0em; }
    .level-0 .toc-title { font-weight: bold; font-size: 13pt; }
    .level-1 { padding-left: 25px; }
    .level-1 .toc-title { font-size: 11pt; color: #444; }
</style>
"""

FOOTER_STYLE = """
<style>
    body { font-family: Georgia, serif; font-size: 10pt; text-align: center; margin: 0; padding: 0; background: transparent !important; }
</style>
"""

def _add_page_numbers(pdf_bin, skip_first=False, skip_last=False):
    """Adds page numbers using a single pdfkit call for all pages (prevents worker timeout on large docs)."""
    try:
        reader = PdfReader(io.BytesIO(pdf_bin))
        total_pages = len(reader.pages)

        # Build ONE html document with all footer pages
        footer_divs = []
        for i in range(total_pages):
            page_break = "page-break-after:always;" if i < total_pages - 1 else ""
            if (skip_first and i == 0) or (skip_last and i == total_pages - 1):
                footer_divs.append(f'<div style="{page_break}width:210mm;height:20mm;"></div>')
            else:
                page_num = i + 1
                footer_divs.append(
                    f'<div style="{page_break}width:210mm;height:20mm;position:relative;font-family:Georgia,serif;font-size:10pt;">'
                    f'<div style="position:absolute;bottom:2mm;width:100%;text-align:center;">{page_num}</div>'
                    f'</div>'
                )

        all_footers_html = (
            "<html><head><meta charset='UTF-8'>"
            "<style>body{{margin:0;padding:0;background:transparent !important;}}</style>"
            "</head><body>"
            + "".join(footer_divs)
            + "</body></html>"
        )

        footer_pdf_bin = pdfkit.from_string(all_footers_html, False, options={
            "page-height": "20mm", "page-width": "210mm",
            "margin-top": "0", "margin-bottom": "0", "margin-left": "0", "margin-right": "0",
            "quiet": ""
        })

        if not footer_pdf_bin:
            return pdf_bin

        footer_reader = PdfReader(io.BytesIO(footer_pdf_bin))
        writer = PdfWriter()

        for i in range(total_pages):
            content_page = reader.pages[i]
            # CRITICAL: Don't merge if it's a skipped page (prevents white bar on covers)
            is_skipped = (skip_first and i == 0) or (skip_last and i == total_pages - 1)
            if not is_skipped and i < len(footer_reader.pages):
                content_page.merge_page(footer_reader.pages[i])
            writer.add_page(content_page)

        output = io.BytesIO()
        writer.write(output)
        return output.getvalue()
    except Exception as e:
        frappe.log_error(f"Page numbering error: {str(e)}", "Wiki PDF Error")
        return pdf_bin

def _post_process_pdf(main_html, groups):
    """Generates PDF with manual TOC post-processing."""
    # 1. Add invisible anchors to groups and pages
    anchor_html = []
    for g_idx, group in enumerate(groups):
        g_id = f"GTOC-{g_idx}"
        group["anchor"] = g_id
        # Apply page break to the group container itself (except for the first group)
        gb = 'style="page-break-before:always;"' if g_idx > 0 else ""
        
        parts = [f'<div {gb}>']
        # Invisible anchor
        parts.append(f'<div style="color:#ffffff;font-size:1px;position:absolute;z-index:-1;">{g_id}</div>')
        
        if group["label"]:
            parts.append(f'<h1 class="group-name">{group["label"]}</h1>')
            
        for p_idx, page in enumerate(group["pages"]):
            p_id = f"PTOC-{g_idx}-{p_idx}"
            page["anchor"] = p_id
            p_div = f'<div style="color:#ffffff;font-size:1px;position:absolute;z-index:-1;">{p_id}</div>'
            # If we already had a group label/header, we don't need another break for the first page
            pb = 'style="page-break-before:always;"' if (p_idx > 0 or (g_idx > 0 and not group["label"])) else ""
            tag = "h2" if group["label"] else "h1"
            parts.append(f'<div {pb}>{p_div}<{tag} class="page-title">{page["title"]}</{tag}>{page["content_html"]}</div>')
        
        parts.append('</div>')
        anchor_html.append("\n".join(parts))

    full_body = "\n".join(anchor_html)
    content_html = _inline_images(_wrap(full_body))
    
    # 2. Generate Cover PDF
    def _get_base64_image(src):
        """Helper to force base64 inlining for cloud reliability (covers)."""
        try:
            real_src = unquote(src).strip()
            # If it's already base64, return it
            if real_src.startswith("data:"): return real_src
            
            fname = real_src.split("/")[-1]
            path = None
            
            # 1. Try find_file_by_url
            try:
                file_doc = find_file_by_url(real_src)
                if file_doc:
                    test_path = file_doc.get_full_path()
                    if os.path.exists(test_path):
                        path = test_path
            except: pass

            if not path:
                # 2. Aggressive search in both public and private folders
                for folder in ["public", "private"]:
                    files_dir = frappe.get_site_path(folder, "files")
                    if os.path.exists(files_dir):
                        # List all files and do a case-insensitive check
                        for f in os.listdir(files_dir):
                            if f.lower() == fname.lower():
                                path = os.path.join(files_dir, f)
                                break
                    if path: break

            if path and os.path.exists(path):
                with open(path, "rb") as f:
                    data = base64.b64encode(f.read()).decode()
                    ext = path.split(".")[-1].lower()
                    mime = "image/jpeg" if ext in ["jpg", "jpeg"] else "image/png"
                    return f"data:{mime};base64,{data}"
            else:
                frappe.log_error(f"Image NOT FOUND for {src}. Checked {fname} in public/private folders.", "Wiki PDF Cover Debug")
        except Exception as e:
            frappe.log_error(f"Cover image Base64 error for {src}: {str(e)}", "Wiki PDF Cover Error")
        
        # Return original if all else fails (wkhtmltopdf might still try to load it)
        return src

    front_img = _get_base64_image("/files/Creche Frontpage.jpg")
    front_html = f"""
    <html>
    <head>
        <meta charset='UTF-8'>
        <style>
            html, body {{ margin: 0; padding: 0; width: 100%; height: 100%; overflow: hidden; background-color: white; }}
            .cover-img {{ width: 100%; height: 100%; display: block; margin: 0; padding: 0; border: none; }}
        </style>
    </head>
    <body style="margin: 0; padding: 0;">
        <img src="{front_img}" class="cover-img">
    </body>
    </html>
    """
    
    cover_pdf_bin = pdfkit.from_string(front_html, False, options={
        "page-size": "A4", "margin-top": "0", "margin-bottom": "0", "margin-left": "0", "margin-right": "0",
        "enable-local-file-access": "", "quiet": ""
    })
    
    # 3. Generate Back Cover PDF
    back_img = _get_base64_image("/files/creche backpage.jpg")
    back_html = f"""
    <html>
    <head>
        <meta charset='UTF-8'>
        <style>
            html, body {{ margin: 0; padding: 0; width: 100%; height: 100%; overflow: hidden; background-color: white; }}
            .cover-img {{ width: 100%; height: 100%; display: block; margin: 0; padding: 0; border: none; }}
        </style>
    </head>
    <body style="margin: 0; padding: 0;">
        <img src="{back_img}" class="cover-img">
    </body>
    </html>
    """
    back_pdf_bin = pdfkit.from_string(back_html, False, options={
        "page-size": "A4", "margin-top": "0", "margin-bottom": "0", "margin-left": "0", "margin-right": "0",
        "enable-local-file-access": "", "quiet": ""
    })

    # 4. Generate content PDF
    content_pdf = pdfkit.from_string(content_html, False, options=_pdf_options(None))
    if not content_pdf:
        frappe.log_error("Content PDF generation failed (empty result)")
        return b""
    
    # 3. Index pages
    reader = PdfReader(io.BytesIO(content_pdf))
    page_map = {}
    for i, page in enumerate(reader.pages):
        text = page.extract_text()
        matches = re.findall(r'[GP]TOC-\d+(?:-\d+)?', text)
        for m in matches:
            if m not in page_map:
                page_map[m] = i + 1 
    
    if not page_map:
        frappe.log_error("PDF manual indexing failed: No anchors found in content PDF")
                
    # 4. Generate TOC PDF
    def build_toc(shift=0):
        toc_lines = ['<h1>Table of Contents</h1><div class="toc-container">']
        for g_idx, group in enumerate(groups):
            if group["label"]:
                p_num = page_map.get(group["anchor"], 1) + shift
                title = f"{group['number']}. {group['label']}"
                toc_lines.append(f'<div class="toc-item level-0"><span class="toc-page">{p_num}</span><span class="toc-title">{title}</span><div class="toc-line"></div></div>')
            for p_idx, page in enumerate(group["pages"]):
                p_num = page_map.get(page["anchor"], 1) + shift
                title = f"{page['number']} {page['title']}"
                level = "level-1" if group["label"] else "level-0"
                toc_lines.append(f'<div class="toc-item {level}"><span class="toc-page">{p_num}</span><span class="toc-title">{title}</span><div class="toc-line"></div></div>')
        toc_lines.append('</div>')
        return f"<html><head><meta charset='UTF-8'>{TOC_STYLE}</head><body>{''.join(toc_lines)}</body></html>"

    # Pass 1: Estimate TOC size
    toc_pdf = pdfkit.from_string(build_toc(0), False, options=_pdf_options(None))
    toc_page_count = len(PdfReader(io.BytesIO(toc_pdf)).pages)
    
    # Pass 2: Final TOC with correct page shifts (Cover + TOC pages)
    shift_amount = 1 + toc_page_count
    toc_pdf = pdfkit.from_string(build_toc(shift_amount), False, options=_pdf_options(None))
    toc_reader = PdfReader(io.BytesIO(toc_pdf))
    
    # 5. Merge
    writer = PdfWriter()
    
    # Add Cover
    if cover_pdf_bin:
        cover_reader = PdfReader(io.BytesIO(cover_pdf_bin))
        for page in cover_reader.pages: writer.add_page(page)

    # Add TOC
    for page in toc_reader.pages: writer.add_page(page)
    
    # Add Content
    for page in reader.pages: writer.add_page(page)

    # Add Back Cover
    if back_pdf_bin:
        back_reader = PdfReader(io.BytesIO(back_pdf_bin))
        for page in back_reader.pages: writer.add_page(page)
    
    output = io.BytesIO()
    writer.write(output)
    
    # 6. Final Pass: Add Page Numbers (skip cover and backpage)
    return _add_page_numbers(output.getvalue(), skip_first=True, skip_last=True)

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
    return None # Unpatched QT doesn't support this

def _write_toc_xsl():
    return None # Unpatched QT doesn't support this

def _pdf_options(footer_path, toc_xsl_path=None):
    opts = {
        "page-size": "A4", "margin-top": "15mm", "margin-bottom": "18mm", "margin-left": "18mm", "margin-right": "18mm",
        "encoding": "UTF-8", "quiet": "", "enable-local-file-access": "", 
        "load-error-handling": "ignore", "load-media-error-handling": "ignore"
    }
    return opts

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

            group_counter = 1
            for s in sidebar:
                if s.wiki_page in p_map:
                    p = p_map[s.wiki_page]
                    label = s.parent_label or ""
                    
                    if not groups or groups[-1]["label"] != label:
                        groups.append({"label": label, "number": group_counter, "anchor": f"GTOC-{group_counter}", "pages": []})
                        group_counter += 1
                        ref_counter = 1
                    
                    full_number = f"{groups[-1]['number']}.{ref_counter}"
                    groups[-1]["pages"].append({
                        "number": full_number,
                        "title": p.title,
                        "anchor": f"PTOC-{full_number.replace('.', '-')}",
                        "content_html": _clean_for_pdf(_md_to_html(p.content or ""))
                    })
                    ref_counter += 1

        if not groups or not any(g["pages"] for g in groups):
            frappe.throw(_("No content found to generate PDF"))

        pdf_bin = _post_process_pdf(None, groups)

        # Build filename
        filename = "Creche Guideline"

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

        # Pages
        all_pages = frappe.get_all("Wiki Page", filters={"published": 1}, fields=["name", "title", "content", "parent_wiki_page"], order_by="creation asc", ignore_permissions=True, limit=0)
        pages = [p for p in all_pages if p.name == root_name or p.parent_wiki_page == root_name]

        if not pages:
            frappe.throw(_("No content found to generate PDF"))

        pdf_bin = _post_process_pdf(None, [{"label": None, "pages": pages}])

        frappe.local.response.filename = f"Creche Guideline.pdf".replace(" ", "_")
        frappe.local.response.filecontent = pdf_bin
        frappe.local.response.type = "download"

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Wiki Full Space PDF Error")
        frappe.throw(f"Error: {str(e)}")