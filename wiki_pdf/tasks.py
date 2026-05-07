import frappe
import time

TARGET_LANGUAGES = [
    "en", "kn", "ta", "hi", "te", "mr", "bn", "gu", "ml", "ur", "pa",
    "or", "as", "sa", "gom", "doi", "mai", "mni-Mtei", "ne",
    "sat", "sd", "tcy"
]


def generate_daily_translated_pdfs():
    """
    Frappe daily scheduled task.
    Generates one translated PDF per language and saves it into the File doctype.
    The download_wiki_pdf endpoint checks these cached files first.
    """
    from wiki_pdf.pdf import (
        _find_page, _md_to_html, _clean_for_pdf, _post_process_pdf,
        translate_html, translate_text, get_normalized_lang
    )

    frappe.logger().info("Wiki PDF: Starting daily PDF generation job...")

    # Determine which Wiki Space to dump
    # Resolve this from the first available wiki group sidebar
    try:
        sidebar_parents = frappe.get_all("Wiki Group Item", fields=["parent"], limit=1)
        if not sidebar_parents:
            frappe.log_error("No Wiki Group Items found. Skipping daily PDF generation.", "Wiki PDF Task")
            return
        
        sidebar_parent = sidebar_parents[0].parent

        sidebar = frappe.get_all(
            "Wiki Group Item",
            filters={"parent": sidebar_parent},
            fields=["wiki_page", "parent_label"],
            order_by="idx asc",
            ignore_permissions=True,
            limit=0,
        )

        p_names = [s.wiki_page for s in sidebar if s.wiki_page]
        if not p_names:
            frappe.log_error("No wiki pages found in sidebar.", "Wiki PDF Task")
            return

        p_map = {
            p.name: p for p in frappe.get_all(
                "Wiki Page",
                filters={"name": ["in", p_names]},
                fields=["name", "title", "content"],
                ignore_permissions=True,
                limit=0,
            )
        }

    except Exception as e:
        frappe.log_error(f"Failed to fetch wiki content: {e}", "Wiki PDF Task")
        return

    for lang in TARGET_LANGUAGES:
        lang_code = get_normalized_lang(lang)

        frappe.logger().info(f"Wiki PDF: Generating PDF for language: {lang_code}")
        cache_fname = f"WikiPDF_DailyCache_{lang_code}.pdf"

        try:
            groups = []
            group_counter = 1
            ref_counter = 1

            for s in sidebar:
                if s.wiki_page not in p_map:
                    continue
                p = p_map[s.wiki_page]
                label = s.parent_label or ""

                if not groups or groups[-1]["label"] != label:
                    # Translate the group parent_label
                    translated_label = _safe_translate(label, lang_code) if label else label
                    groups.append({
                        "label": translated_label,
                        "number": group_counter,
                        "anchor": f"GTOC-{group_counter}",
                        "pages": []
                    })
                    group_counter += 1
                    ref_counter = 1

                raw_html = _md_to_html(p.content or "")
                translated_html = translate_html(raw_html, lang_code)
                translated_title = _safe_translate(p.title, lang_code)

                full_number = f"{groups[-1]['number']}.{ref_counter}"
                groups[-1]["pages"].append({
                    "number": full_number,
                    "title": translated_title,
                    "anchor": f"PTOC-{full_number.replace('.', '-')}",
                    "content_html": _clean_for_pdf(translated_html)
                })
                ref_counter += 1

                # Small delay to avoid rate limiting
                time.sleep(0.5)

            if not groups or not any(g["pages"] for g in groups):
                frappe.log_error(f"No content found for language {lang_code}. Skipping.", "Wiki PDF Task")
                continue

            pdf_bin = _post_process_pdf(None, groups)
            if not pdf_bin:
                frappe.log_error(f"PDF generation returned empty for lang={lang_code}", "Wiki PDF Task")
                continue

            # Save or update the cached file: delete old and insert new
            existing = frappe.db.get_value("File", {"file_name": cache_fname}, "name")
            if existing:
                frappe.delete_doc("File", existing, ignore_permissions=True, force=True)
            
            # create and insert a new file
            file_doc = frappe.get_doc({
                "doctype": "File",
                "file_name": cache_fname,
                "content": pdf_bin,
                "is_private": 0
            })
            file_doc.insert(ignore_permissions=True)
            
            frappe.db.commit()
            frappe.logger().info(f"Wiki PDF: Saved {cache_fname} successfully.")

            # Pause between languages to avoid rate-limiting
            time.sleep(3)

        except Exception as e:
            frappe.log_error(frappe.get_traceback(), f"Wiki PDF daily generation failed for lang={lang_code}")
            continue

def ensure_pdf_caches_exist():
    """
    Called on server boot (startup hook).
    If any language PDF is missing from File doctype, enqueue background generation.
    This ensures cloud deployments always have cached PDFs.
    """
    try:
        from wiki_pdf.pdf import get_normalized_lang
        missing = []
        for lang in TARGET_LANGUAGES:
            lang_code = get_normalized_lang(lang)
            cache_fname = f"WikiPDF_DailyCache_{lang_code}.pdf"
            if not frappe.db.exists("File", {"file_name": cache_fname}):
                missing.append(lang_code)

        if missing:
            frappe.logger().info(f"Wiki PDF: Missing PDFs for {missing}. Enqueueing generation...")
            frappe.enqueue(
                "wiki_pdf.tasks.generate_daily_translated_pdfs",
                queue="long",
                timeout=7200,
                enqueue_after_commit=True
            )
        else:
            frappe.logger().info("Wiki PDF: All language PDFs already cached. No action needed.")
    except Exception as e:
        frappe.logger().warning(f"Wiki PDF startup check failed: {e}")


def _safe_translate(text, lang, retries=3):
    """Translate a short text string with retry logic."""
    from wiki_pdf.pdf import translator, _recreate_translator
    import time
    if not text or lang == "en":
        return text
    for attempt in range(retries):
        try:
            result = translator.translate(text, dest=lang)
            if result and result.text:
                return result.text
            raise ValueError("None result")
        except Exception as e:
            _recreate_translator()
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
    return text  # fallback to original on all failures
