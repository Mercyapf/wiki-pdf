import frappe
import wiki_pdf.tasks as tasks
from wiki_pdf.tasks import generate_daily_translated_pdfs

def run():
    # Delete all existing caches to force fresh generation with all fixes
    cached = frappe.get_all("File", filters={"file_name": ["like", "WikiPDF_DailyCache%"]}, fields=["name", "file_name"])
    for f in cached:
        frappe.delete_doc("File", f.name, ignore_permissions=True, force=True)
    frappe.db.commit()
    print(f"Deleted {len(cached)} old cached PDFs. Starting fresh generation...")
    
    tasks.TARGET_LANGUAGES = [
        "en", "kn", "ta", "hi", "te", "mr", "bn", "gu", "ml", "ur", "pa",
        "or", "as", "sa", "gom", "doi", "mai", "ks", "mni-Mtei", "ne", "sat", "sd", "tcy"
    ]
    generate_daily_translated_pdfs()
    print("DONE")

