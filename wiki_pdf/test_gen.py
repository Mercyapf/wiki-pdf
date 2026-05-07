import frappe
from wiki_pdf.tasks import generate_daily_translated_pdfs
import wiki_pdf.tasks as tasks

def run():
    tasks.TARGET_LANGUAGES = ["kn"]
    generate_daily_translated_pdfs()
    if frappe.db.exists("File", {"file_name": "WikiPDF_DailyCache_kn.pdf"}):
        print("SUCCESS_KN")
    else:
        print("FAILED_KN")
