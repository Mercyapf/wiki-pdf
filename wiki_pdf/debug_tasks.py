import frappe
from wiki_pdf.pdf import _find_page, _md_to_html, _clean_for_pdf, _post_process_pdf, translate_html, translate_text, get_normalized_lang
import time

def generate_daily_debug():
    with open("/home/merchy-selvanayagi/frappe-bench/apps/wiki_pdf/wiki_pdf/debug_deep.txt", "w") as f:
        f.write("A\n")
        TARGET_LANGUAGES = ["kn"]
        sidebar_parents = frappe.get_all("Wiki Group Item", fields=["parent"], limit=1)
        sidebar_parent = sidebar_parents[0].parent
        sidebar = frappe.get_all("Wiki Group Item", filters={"parent": sidebar_parent}, fields=["wiki_page", "parent_label"], order_by="idx asc", ignore_permissions=True, limit=0)
        p_names = [s.wiki_page for s in sidebar if s.wiki_page]
        p_map = {p.name: p for p in frappe.get_all("Wiki Page", filters={"name": ["in", p_names]}, fields=["name", "title", "content"], ignore_permissions=True, limit=0)}
        f.write("B\n")

        for lang in TARGET_LANGUAGES:
            f.write(f"C lang={lang}\n")
            lang_code = get_normalized_lang(lang)
            groups = []
            group_counter = 1
            ref_counter = 1

            for s in sidebar:
                if s.wiki_page not in p_map: continue
                p = p_map[s.wiki_page]
                label = s.parent_label or ""
                if not groups or groups[-1]["label"] != label:
                    groups.append({"label": label, "number": group_counter, "anchor": f"GTOC-{group_counter}", "pages": []})
                    group_counter += 1
                    ref_counter = 1

                f.write(f"D translating {p.title}\n")
                raw_html = _md_to_html(p.content or "")
                translated_html = translate_html(raw_html, lang_code)
                groups[-1]["pages"].append({
                    "number": f"{groups[-1]['number']}.{ref_counter}",
                    "title": p.title,
                    "anchor": "PTOC-1",
                    "content_html": _clean_for_pdf(translated_html)
                })
                ref_counter += 1

            f.write("E pre pdf\n")
            try:
                pdf_bin = _post_process_pdf(None, groups)
                f.write("F post pdf\n")
            except Exception as e:
                f.write(f"G pdf EXCEPTION: {repr(e)}\n")

