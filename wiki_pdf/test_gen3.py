import frappe
from wiki_pdf.tasks import generate_daily_translated_pdfs
import wiki_pdf.tasks as tasks
import traceback

def run():
    with open("debug_flow.txt", "w") as f:
        f.write("STARTING\n")
        try:
            tasks.TARGET_LANGUAGES = ["kn"]
            f.write("Calling generation\n")
            generate_daily_translated_pdfs()
            f.write("Finished generation\n")
        except Exception:
            f.write("EXCEPTION: " + traceback.format_exc() + "\n")
        f.write("DONE\n")
