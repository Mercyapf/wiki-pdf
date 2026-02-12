import frappe
from frappe.utils.pdf import get_pdf
from frappe.utils import cint
from frappe import _
import tempfile
import os
import re

@frappe.whitelist(allow_guest=True)
def download_wiki_pdf(page_name=None, route=None):
	if not page_name and not route:
		frappe.throw(_("Page Name or Route is required"))
	
	if not page_name and route:
		# Lookup page name from route
		page_name = frappe.db.get_value("Wiki Page", {"route": route}, "name")
		if not page_name:
			frappe.throw(_("Wiki Page not found for route: {0}").format(route))

	page_doc = frappe.get_doc("Wiki Page", page_name)
	page_doc.check_permission("read")

	# 1. Identify Wiki Space
	# Wiki Pages are linked to a Space via "Wiki Group Item" (parent field)
	# We need to find the root space or common parent.
	# Based on wiki_page.py logic, `get_space_route` or `Wiki Group Item` usage.
	
	wiki_group_item = frappe.db.get_value("Wiki Group Item", {"wiki_page": page_name}, ["parent"], as_dict=True)
	
	if not wiki_group_item:
		# Fallback if page is not in a group/space (orphan?) - just render single page
		final_content = f"<h1>{page_doc.title}</h1>{page_doc.content}"
	else:
		space_name = wiki_group_item.parent
		
		# 2. Fetch all pages in this space
		# We need to respect the sidebar order. 
		# Wiki Group Items define the structure.
		sidebar_items = frappe.get_all(
			"Wiki Group Item",
			filters={"parent": space_name},
			fields=["wiki_page", "idx"],
			order_by="idx asc"
		)
		
		final_content = ""
		# Bulk fetch all pages to avoid N+1 queries
		page_names = [item.wiki_page for item in sidebar_items if item.wiki_page]
		
		# Fetch pages user has permission to read
		pages_data = frappe.get_list(
			"Wiki Page",
			filters={"name": ["in", page_names]},
			fields=["name", "title", "content"],
			limit=len(page_names) + 10
		)
		
		# Create a lookup map
		pages_map = {row.name: row for row in pages_data}
		
		final_content = ""
		for item in sidebar_items:
			try:
				if item.wiki_page not in pages_map:
					continue
					
				p_data = pages_map[item.wiki_page]
				
				# Append Content - No forced page break, just a separator
				final_content += f"\n\n<hr style='margin: 20px 0; border: 0; border-top: 1px solid #eee;'>\n\n" if final_content else ""
				final_content += f"# {p_data.title}\n\n"
				final_content += p_data.content or ""
			except Exception:
				continue

	# 3. Prepare Context
	# We use the requested page_doc as the "host" for the template (styles, etc)
	# But we override the content.
	
	context = frappe._dict(page_doc.as_dict())
	context.doc = page_doc
	page_doc.get_context(context)
	
	# OVERRIDE CONTENT
	# The template show.html uses `content` variable.
	context.content = final_content

	html = frappe.render_template(
		"wiki/wiki/doctype/wiki_page/templates/wiki_page.html", context
	)

	# 4. Post-Render Modifications
	# Apply regex replacements on the FINAL HTML to ensure we catch all iframes/videos/details generated from Markdown
	
	def replace_iframe(match):
		src = re.search(r'src=["\'](.*?)["\']', match.group(0))
		if src:
			url = src.group(1)
			# transform youtube embed to watch link
			if "youtube.com/embed/" in url:
				video_id = url.split("embed/")[1].split("?")[0]
				url = f"https://www.youtube.com/watch?v={video_id}"
				
			# Light blue link #03a9f4 as requested
			return f'<div class="pdf-video-link" style="margin: 10px 0;"><a href="{url}" style="color: #03a9f4; text-decoration: underline;">Watch Video: {url}</a></div>'
		return match.group(0)

	def replace_video(match):
		# Try to find src in video tag or nested source tag
		src = re.search(r'src=["\'](.*?)["\']', match.group(0))
		if src:
			url = src.group(1)
			# transform youtube embed to watch link
			if "youtube.com/embed/" in url:
				video_id = url.split("embed/")[1].split("?")[0]
				url = f"https://www.youtube.com/watch?v={video_id}"
				
			return f'<div class="pdf-video-link" style="margin: 10px 0;"><a href="{url}" style="color: #03a9f4; text-decoration: underline;">Watch Video: {url}</a></div>'
		return "<!-- Video without src removed for PDF -->"
	
	# Remove iframes (youtube etc) and replace with link
	html = re.sub(r'<iframe[^>]*>.*?</iframe>', replace_iframe, html, flags=re.DOTALL | re.IGNORECASE)
	# Remove video tags and replace with link
	html = re.sub(r'<video[^>]*>.*?</video>', replace_video, html, flags=re.DOTALL | re.IGNORECASE)

	# Expand details/summary for PDF so content like "Foundation Vision" is visible
	html = re.sub(r'<details[^>]*>', '<div class="pdf-details" style="display: block; margin: 10px 0; font-family: \'Times New Roman\', serif;">', html, flags=re.IGNORECASE)
	html = re.sub(r'</details>', '</div>', html, flags=re.IGNORECASE)
	html = re.sub(r'<summary[^>]*>', '<div class="pdf-summary" style="font-weight: bold; margin-bottom: 5px; font-family: \'Times New Roman\', serif;">', html, flags=re.IGNORECASE)
	html = re.sub(r'</summary>', '</div>', html, flags=re.IGNORECASE)

	# Inject print styles globally to ensure content visibility and proper layout
	# We remove @media print to force these styles regardless of how the PDF generator interprets the view
	html += """
	<style>
			@page {
				size: A4;
				margin-top: 10mm;
				margin-bottom: 30mm; /* MUST be >= footer height */
				margin-left: 10mm;
				margin-right: 10mm;
			}
			
			html, body {
				width: 100%;
				font-family: "Times New Roman", Times, serif !important;
				line-height: 1.35 !important;
				font-size: 14pt !important;
				
				/* ❌ DO NOT ZERO OUT MARGINS */
				margin: 0;
				padding: 0;
			}

			/* Explicitly hide the page title from show.html template and other UI */
			.admin-banner, .sidebar-column, .page-toc, .wiki-footer, .wiki-page-meta, .navbar, .page-head, .modal, .wiki-editor { 
				display: none !important; 
			}
			
			/* Reset all elements related to layout */
			.wiki-content,
			.wiki-page-content,
			.content-view {
				margin: 0 !important;
				padding: 5mm !important;
				width: 100% !important;
				max-width: 100% !important;
				font-family: "Times New Roman", Times, serif !important;
				font-size: 14pt !important;
			}
			
			p, li, div {
				text-align: left !important;
				text-justify: none !important;
				letter-spacing: normal !important;
				word-spacing: normal !important;
				font-family: "Times New Roman", Times, serif !important;
			}

			* {
				font-family: "Times New Roman", Times, serif !important;
				box-sizing: border-box !important;
				max-width: 100% !important;
			}

			/* Unset Bootstrap/Frappe container widths */
			.container, .container-fluid, .page-container {
				width: 100% !important;
				max-width: none !important;
				padding: 0 !important;
				margin: 0 !important;
			}

			/* Block display to kill flexbox constraints */
			.main-column, .doc-main, .row, [class*="col-"] {
				display: block !important;
				width: 100% !important;
				max-width: none !important;
				flex: none !important;
				padding: 0 !important;
				margin: 0 !important;
				float: none !important;
			}
			
			img { max-width: 100% !important; height: auto !important; }
			
			 /* Tables */
			table { width: 100% !important; table-layout: fixed !important; border-collapse: collapse !important; }
			td, th { border: 1px solid #ddd !important; padding: 8px !important; background-color: transparent !important; }
			
			/* Text content visibility */
			p, h1, h2, h3, h4, h5, h6, li, span, div {
				color: black !important;
				opacity: 1 !important;
			}

			/* Bold Headings */
			h1, h2, h3, h4, h5, h6 {
				font-weight: bold !important;
				font-size: 16pt !important;
				font-family: "Times New Roman", Times, serif !important;
			}

			/* Links */
			a { text-decoration: underline !important; color: black !important; }
			
			/* Video Link Box specific styling to look good in B&W or Color */
			.pdf-video-link {
				border: 1px solid #ccc !important;
				padding: 10px !important;
				margin: 10px 0 !important;
				display: block !important;
				background-color: #f5f5f5 !important;
			}
	</style>
	"""

	# CORRECTED FOOTER HTML - with proper wkhtmltopdf script tags
	footer_html = """<!DOCTYPE html>
<html>
<head>
	<script>
		function subst() {
			var vars = {};
			var query_strings_from_url = document.location.search.substring(1).split('&');
			for (var query_string in query_strings_from_url) {
				if (query_strings_from_url.hasOwnProperty(query_string)) {
					var temp_var = query_strings_from_url[query_string].split('=', 2);
					vars[temp_var[0]] = decodeURI(temp_var[1]);
				}
			}
			var css_selector_classes = ['page', 'frompage', 'topage', 'webpage', 'section', 'subsection', 'date', 'isodate', 'time', 'title', 'doctitle', 'sitepage', 'sitepages'];
			for (var css_class in css_selector_classes) {
				if (css_selector_classes.hasOwnProperty(css_class)) {
					var element = document.getElementsByClassName(css_selector_classes[css_class]);
					for (var j = 0; j < element.length; ++j) {
						element[j].textContent = vars[css_selector_classes[css_class]];
					}
				}
			}
		}
	</script>
</head>
<body style="border:0; margin: 0;" onload="subst()">
	<div style="font-family: 'Times New Roman', Times, serif; font-size: 10pt; text-align: center; width: 100%;">
		<span class="page"></span>
	</div>
</body>
</html>"""

	# Write footer HTML to a temporary file
	footer_path = ""
	with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8") as f:
		f.write(footer_html)
		footer_path = f.name

	options = {
		"enable-local-file-access": "",
		"disable-smart-shrinking": "",
		"quiet": None,
		"encoding": "UTF-8",

		# Page setup
		"page-size": "A4",
		
		# Margins - footer needs space at bottom
		"margin-top": "10mm",
		"margin-bottom": "30mm",  # Must be enough for footer
		"margin-left": "10mm",
		"margin-right": "10mm",

		# Footer configuration
		"footer-html": footer_path,
		"footer-spacing": "5",  # Space between content and footer
	}

	# 5. Set Filename
	# Use Space Name if available, else Page Title
	if wiki_group_item and frappe.db.exists("Wiki Space", wiki_group_item.parent):
		space = frappe.get_doc("Wiki Space", wiki_group_item.parent)
		filename = f"{space.space_name}.pdf"
	else:
		filename = f"{page_doc.title}.pdf"

	try:
		frappe.local.response.filecontent = get_pdf(html, options=options)
	finally:
		# cleanup temp file
		if footer_path and os.path.exists(footer_path):
			os.remove(footer_path)

	frappe.local.response.filename = filename
	frappe.local.response.type = "pdf"



@frappe.whitelist(allow_guest=True)
def download_full_wiki_space(wiki_space):
	"""
	wiki_space = route of the root wiki page
	example: creche-manual
	"""

	# -------------------------------------------------
	# 1. Get root wiki page
	# -------------------------------------------------
	root = frappe.get_doc("Wiki Page", {"route": wiki_space})

	# -------------------------------------------------
	# 2. Fetch ALL published wiki pages
	# -------------------------------------------------
	all_pages = frappe.get_all(
		"Wiki Page",
		filters={"published": 1},
		fields=[
			"name",
			"title",
			"content",
			"route",
			"parent_wiki_page",
			"creation",
		],
		order_by="creation asc",
	)

	# -------------------------------------------------
	# 3. Keep only pages belonging to this wiki space
	# -------------------------------------------------
	pages = []
	for p in all_pages:
		if p.name == root.name or p.parent_wiki_page == root.name:
			pages.append(p)

	if not pages:
		frappe.throw(_("No wiki pages found"))

	# -------------------------------------------------
	# 4. Build ONE HTML for ALL pages
	# -------------------------------------------------
	html = """
	<html>
	<head>
		<style>
			body { 
				font-family: "Times New Roman", Times, serif; 
				font-size: 14pt;
				line-height: 1.35;
			}
			h1 { 
				page-break-before: always; 
				font-weight: bold;
			}
			img { max-width: 100%; height: auto; }
		</style>
	</head>
	<body>
	"""

	for page in pages:
		html += f"""
		<h1>{page.title}</h1>
		<div>{page.content}</div>
		"""

	html += "</body></html>"

	# -------------------------------------------------
	# 5. Footer HTML with page numbers
	# -------------------------------------------------
	footer_html = """<!DOCTYPE html>
<html>
<head>
	<script>
		function subst() {
			var vars = {};
			var query_strings_from_url = document.location.search.substring(1).split('&');
			for (var query_string in query_strings_from_url) {
				if (query_strings_from_url.hasOwnProperty(query_string)) {
					var temp_var = query_strings_from_url[query_string].split('=', 2);
					vars[temp_var[0]] = decodeURI(temp_var[1]);
				}
			}
			var css_selector_classes = ['page', 'frompage', 'topage', 'webpage', 'section', 'subsection', 'date', 'isodate', 'time', 'title', 'doctitle', 'sitepage', 'sitepages'];
			for (var css_class in css_selector_classes) {
				if (css_selector_classes.hasOwnProperty(css_class)) {
					var element = document.getElementsByClassName(css_selector_classes[css_class]);
					for (var j = 0; j < element.length; ++j) {
						element[j].textContent = vars[css_selector_classes[css_class]];
					}
				}
			}
		}
	</script>
</head>
<body style="border:0; margin: 0;" onload="subst()">
	<div style="font-family: 'Times New Roman', Times, serif; font-size: 10pt; text-align: center; width: 100%;">
		<span class="page"></span>
	</div>
</body>
</html>"""

	footer_path = ""
	with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8") as f:
		f.write(footer_html)
		footer_path = f.name

	options = {
		"enable-local-file-access": "",
		"disable-smart-shrinking": "",
		"quiet": None,
		"encoding": "UTF-8",
		"page-size": "A4",
		"margin-top": "10mm",
		"margin-bottom": "30mm",
		"margin-left": "10mm",
		"margin-right": "10mm",
		"footer-html": footer_path,
		"footer-spacing": "5",
	}

	# -------------------------------------------------
	# 6. Convert HTML → PDF
	# -------------------------------------------------
	try:
		pdf = get_pdf(html, options=options)
	finally:
		if footer_path and os.path.exists(footer_path):
			os.remove(footer_path)

	# -------------------------------------------------
	# 7. Send PDF as download
	# -------------------------------------------------
	frappe.local.response.filename = f"{wiki_space}.pdf"
	frappe.local.response.filecontent = pdf
	frappe.local.response.type = "download"
