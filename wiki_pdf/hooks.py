app_name = "wiki_pdf"
app_title = "Wiki PDF"
app_publisher = "Mercy Selvanayagi"
app_description = "Custom App for Wiki PDF Download"
app_icon = "octicon octicon-file-directory"
app_color = "grey"
app_email = "mercy.selvanayagi@azimpremjifoundation.org"
app_license = "MIT"

web_include_js = "/assets/wiki_pdf/js/wiki_pdf.js"

doc_events = {
    "Wiki Page": {
        "after_save": "wiki_pdf.tasks.on_wiki_page_save"
    },
    "Wiki Space": {
        "after_save": "wiki_pdf.tasks.on_wiki_page_save"
    }
}

# Runs on first request after server start - auto-generates missing PDFs on cloud deploy
on_login = "wiki_pdf.tasks.ensure_pdf_caches_exist"
