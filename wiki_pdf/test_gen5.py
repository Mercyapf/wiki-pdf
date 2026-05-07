import frappe
import wiki_pdf.debug_tasks as debug_tasks
def run():
    debug_tasks.generate_daily_debug()
