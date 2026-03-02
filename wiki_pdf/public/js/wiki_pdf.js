frappe.ready(function () {
    // Check if we are on a Wiki Page by looking for wiki content container
    if ($('.wiki-content').length > 0) {
        // Delay slightly to ensure navbar is fully rendered if dynamically loaded
        setTimeout(add_download_pdf_button, 500);
    }
});

function add_download_pdf_button() {
    var $btn = $('#btn-download-wiki-pdf');

    // Get the current route
    var current_route = window.location.pathname.replace(/^\//, '');

    // Strip trailing slash if present
    if (current_route.endsWith('/')) {
        current_route = current_route.slice(0, -1);
    }

    // Construct the download URL
    var download_url = "/api/method/wiki_pdf.pdf.download_wiki_pdf?route=" + encodeURIComponent(current_route);

    if ($btn.length > 0) {
        // If button exists, just update the href (in case of SPA navigation)
        $btn.attr('href', download_url);
        return;
    }

    // Identify the navbar container
    var $navbar = $('.navbar-nav').first();
    var $container = $navbar.find('.sun-moon-container');

    if ($navbar.length === 0) return;

    $btn = $('<a>')
        .attr('id', 'btn-download-wiki-pdf')
        .attr('href', download_url)
        .attr('target', '_blank')
        .attr('rel', 'noopener noreferrer')
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
