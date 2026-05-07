import frappe
import time

TARGET_LANGUAGES = [
    "en", "kn", "ta", "hi", "te", "mr", "bn", "gu", "ml", "ur", "pa",
    "or", "as", "sa", "gom", "doi", "mai", "mni-Mtei", "ne",
    "sat", "sd", "tcy"
]


def generate_pdf_for_single_language(lang):
    """
    Generates and caches the PDF for one language.
    Called as a separate background job per language so:
    - Each language runs independently (one failure doesn't kill others)
    - The DB connection is fresh per job (avoids MySQL gone-away after long translation)
    """
    from wiki_pdf.pdf import (
        _md_to_html, _clean_for_pdf, _post_process_pdf,
        translate_html, get_normalized_lang, _save_pdf_to_cache
    )

    lang_code = get_normalized_lang(lang)
    cache_fname = f"WikiPDF_DailyCache_{lang_code}.pdf"
    frappe.logger().info(f"Wiki PDF: Starting generation for lang={lang_code}")

    try:
        sidebar_parents = frappe.get_all("Wiki Group Item", fields=["parent"], limit=1)
        if not sidebar_parents:
            frappe.logger().warning("Wiki PDF: No Wiki Group Items found.")
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
            frappe.logger().warning("Wiki PDF: No wiki pages found in sidebar.")
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

        groups = []
        group_counter = 1
        ref_counter = 1

        for s in sidebar:
            if s.wiki_page not in p_map:
                continue
            p = p_map[s.wiki_page]
            label = s.parent_label or ""

            if not groups or groups[-1]["label"] != label:
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
            time.sleep(0.5)

        if not groups or not any(g["pages"] for g in groups):
            frappe.logger().warning(f"Wiki PDF: No content for lang={lang_code}. Skipping.")
            return

        pdf_bin = _post_process_pdf(None, groups, lang_code=lang_code)
        if not pdf_bin:
            frappe.logger().warning(f"Wiki PDF: Empty PDF for lang={lang_code}")
            return

        _save_pdf_to_cache(cache_fname, pdf_bin)
        frappe.logger().info(f"Wiki PDF: Saved {cache_fname} successfully.")

    except Exception:
        frappe.logger().error(f"Wiki PDF generation failed for lang={lang_code}: {frappe.get_traceback()}")
        try:
            frappe.log_error(frappe.get_traceback(), f"Wiki PDF generation failed for lang={lang_code}")
        except Exception:
            pass


def generate_daily_translated_pdfs():
    """
    Frappe daily scheduled task.
    Enqueues one background job per language so each runs independently.
    """
    frappe.logger().info("Wiki PDF: Enqueueing per-language PDF generation jobs...")
    for lang in TARGET_LANGUAGES:
        from wiki_pdf.pdf import get_normalized_lang
        lang_code = get_normalized_lang(lang)
        job_name = f"wiki_pdf_generate_{lang_code}"
        frappe.enqueue(
            "wiki_pdf.tasks.generate_pdf_for_single_language",
            lang=lang,
            queue="long",
            timeout=7200,
            job_name=job_name,
        )
    frappe.logger().info(f"Wiki PDF: Enqueued {len(TARGET_LANGUAGES)} language jobs.")


def ensure_pdf_caches_exist():
    """
    Called on login (on_login hook).
    - Clears stuck/orphaned wiki_pdf jobs from Redis (fixes RQ Job list SIGALRM crash).
    - For PDFs already on disk: ensures their File doctype record exists.
    - For missing PDFs: enqueues generation.
    """
    import os
    try:
        from wiki_pdf.pdf import get_normalized_lang, _ensure_pdf_file_record, _clear_stuck_pdf_jobs
        _clear_stuck_pdf_jobs()
        missing = []
        for lang in TARGET_LANGUAGES:
            lang_code = get_normalized_lang(lang)
            cache_fname = f"WikiPDF_DailyCache_{lang_code}.pdf"
            file_path = os.path.join(frappe.get_site_path("public", "files"), cache_fname)
            if os.path.exists(file_path):
                # File is on disk — make sure it has a File doctype record.
                try:
                    _ensure_pdf_file_record(cache_fname, os.path.getsize(file_path))
                except Exception as e:
                    frappe.logger().warning(f"Wiki PDF: Could not fix File record for {cache_fname}: {e}")
            else:
                missing.append(lang)

        if missing:
            frappe.logger().info(f"Wiki PDF: Missing PDFs for {[get_normalized_lang(l) for l in missing]}. Enqueueing...")
            for lang in missing:
                lang_code = get_normalized_lang(lang)
                job_name = f"wiki_pdf_generate_{lang_code}"
                already_queued = frappe.db.exists("RQ Job", {
                    "job_name": job_name,
                    "status": ["in", ["queued", "started"]]
                })
                if not already_queued:
                    frappe.enqueue(
                        "wiki_pdf.tasks.generate_pdf_for_single_language",
                        lang=lang,
                        queue="long",
                        timeout=7200,
                        job_name=job_name,
                        enqueue_after_commit=True,
                    )
        else:
            frappe.logger().info("Wiki PDF: All language PDFs cached and File records verified.")
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
