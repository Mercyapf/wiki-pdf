import frappe
from wiki_pdf.tasks import generate_daily_translated_pdfs
import wiki_pdf.tasks as tasks

def run():
    tasks.TARGET_LANGUAGES = [
        "en", "kn", "ta", "hi", "te", "mr", "bn", "gu", "ml", "ur", "pa",
        "or", "as", "sa", "gom", "doi", "mai", "ks", "mni-Mtei", "ne", "sat", "sd", "tcy"
    ]
    generate_daily_translated_pdfs()

