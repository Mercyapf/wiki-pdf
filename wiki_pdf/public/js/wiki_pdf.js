frappe.ready(function () {
    // Check if we are on a Wiki Page by looking for wiki content container
    if ($('.wiki-content').length > 0) {
        // Delay slightly to ensure navbar is fully rendered if dynamically loaded
        setTimeout(add_download_pdf_button, 500);
    }
});

function add_download_pdf_button() {
    if ($('#btn-download-wiki-pdf').length > 0) {
        return; // already added
    }

    var $navbar = $('.navbar-nav').first();
    if ($navbar.length === 0) return;

    var $container = $navbar.find('.sun-moon-container');

    var $btn = $('<a>')
        .attr('id', 'btn-download-wiki-pdf')
        .attr('href', '#')
        .addClass('navbar-link mr-2 d-print-none')
        .css({
            'white-space': 'nowrap',
            'font-weight': 'bold',
            'cursor': 'pointer'
        })
        .text('Download PDF');

    $btn.on('click', function (e) {
        e.preventDefault();

        // Get current route (strip leading slash and trailing slash)
        var current_route = window.location.pathname.replace(/^\/|\/$/g, '');

        var download_url = '/api/method/wiki_pdf.pdf.download_wiki_pdf?route=' + encodeURIComponent(current_route);

        // Use an invisible iframe to trigger the download without navigating away.
        // The server sets Content-Disposition: attachment so the browser saves the file.
        var iframe = document.createElement('iframe');
        iframe.style.display = 'none';
        iframe.src = download_url;
        document.body.appendChild(iframe);

        // Show loading feedback and remove the iframe after a reasonable delay
        $btn.text('Generating PDF…').css('opacity', '0.6');
        setTimeout(function () {
            document.body.removeChild(iframe);
            $btn.text('Download PDF').css('opacity', '');
        }, 60000); // 60 seconds max — enough for large PDFs
    });

    if ($container.length > 0) {
        $container.before($btn);
    } else {
        $navbar.append($btn);
    }
}
