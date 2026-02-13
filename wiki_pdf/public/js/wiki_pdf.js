frappe.ready(function () {
    // Check if we are on a Wiki Page by looking for wiki content container
    if ($('.wiki-content').length > 0) {
        // Delay slightly to ensure navbar is fully rendered if dynamically loaded
        setTimeout(add_download_pdf_button, 500);
    }
});

function add_download_pdf_button() {
    if ($('#btn-download-wiki-pdf').length > 0) {
        return;
    }

    // Identify the navbar container
    var $navbar = $('.navbar-nav').first();
    var $container = $navbar.find('.sun-moon-container');

    if ($navbar.length === 0) return;

    // Get the current route
    var current_route = window.location.pathname.replace(/^\//, '');

    // Construct the download URL pointing to our custom app's method
    // Note: We use 'route' parameter now, which we will support in the python method
    var download_url = "/api/method/wiki_pdf.pdf.download_wiki_pdf?route=" + encodeURIComponent(current_route);

    var $btn = $('<a>')
        .attr('id', 'btn-download-wiki-pdf')
        .attr('href', download_url)
        .addClass('navbar-link mr-2 d-print-none')
        .css({
            'white-space': 'nowrap',
            'font-weight': 'bold',
            'cursor': 'pointer'
        })
        .text('Download PDF');

    if ($container.length > 0) {
        $container.before($btn);
    } else {
        $navbar.append($btn);
    }
}
