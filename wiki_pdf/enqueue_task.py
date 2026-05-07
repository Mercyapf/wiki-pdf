import frappe
from wiki_pdf.tasks import generate_daily_translated_pdfs

def run():
    frappe.enqueue(
        "wiki_pdf.tasks.generate_daily_translated_pdfs",
        queue="long",
        timeout=7200
    )
    print("ENQUEUED")
