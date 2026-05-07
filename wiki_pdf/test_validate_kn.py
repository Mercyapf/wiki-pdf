import frappe
def run():
    doc = frappe.get_doc("File", {"file_name": "WikiPDF_DailyCache_kn.pdf"})
    print("SIZE OF KN PDF:", len(doc.get_content()))
