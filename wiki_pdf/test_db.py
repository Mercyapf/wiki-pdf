import frappe
def run():
    docs = frappe.get_all("File", filters={"file_name": ["like", "%WikiPDF%"]}, fields=["name", "file_name", "file_url"])
    print(docs)
    
    docs2 = frappe.get_all("File", filters={"file_name": ["like", "%kn%"]}, fields=["name", "file_name", "file_url"])
    print("Files with kn: ", docs2)
