import frappe
from wiki_pdf.tasks import generate_daily_translated_pdfs
import wiki_pdf.tasks as tasks

def run():
    print("STARTING")
    tasks.TARGET_LANGUAGES = ["kn"]
    try:
        generate_daily_translated_pdfs()
    except Exception as e:
        print("EXCEPTION:", repr(e))
    print("FINISHED")
