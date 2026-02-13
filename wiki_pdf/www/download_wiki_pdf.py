import frappe
from frappe.utils.pdf import get_pdf
from frappe import _

@frappe.whitelist(allow_guest=True)
def get_context(context):
    wiki = frappe.form_dict.get("wiki")
    if not wiki:
        frappe.throw(_("Wiki space not provided"))

    # Get all published wiki pages under this space
    pages = frappe.get_all(
        "Wiki Page",
        filters={
            "route": ["like", f"{wiki}/%"],
            "published": 1,
        },
        fields=["name", "title", "route"],
        order_by="idx asc",
    )

    html = ""
    for p in pages:
        doc = frappe.get_doc("Wiki Page", p.name)
        html += f"<h1>{doc.title}</h1>"
        html += doc.content or ""
        html += "<hr>"

    pdf = get_pdf(html)

    frappe.local.response.filename = f"{wiki}.pdf"
    frappe.local.response.filecontent = pdf
    frappe.local.response.type = "pdf"
