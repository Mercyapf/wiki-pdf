import frappe
from wiki_pdf.tasks import generate_daily_translated_pdfs
import wiki_pdf.tasks as tasks
import traceback

def run():
    with open("/home/merchy-selvanayagi/frappe-bench/apps/wiki_pdf/wiki_pdf/debug_ta.txt", "w") as f:
        f.write("STARTING TA\n")
        try:
            tasks.TARGET_LANGUAGES = ["ta"]
            f.write("Calling TA\n")
            generate_daily_translated_pdfs()
            f.write("FINISHED TA\n")
            if frappe.db.exists("File", {"file_name": "WikiPDF_DailyCache_ta.pdf"}):
                f.write("EXISTS IN DB\n")
            else:
                f.write("NOT IN DB\n")
        except Exception:
            f.write("EXCEPTION: " + traceback.format_exc() + "\n")

