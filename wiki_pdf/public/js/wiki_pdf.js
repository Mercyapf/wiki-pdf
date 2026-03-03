frappe.ready(function () {
    // Only attempt to add the button if we are in the Wiki
    if ($('.wiki-content').length > 0 || window.location.pathname.indexOf('/home') !== -1) {
        setTimeout(setup_wiki_pdf_download, 600);
    }
});

function setup_wiki_pdf_download() {
    if ($('#btn-wiki-pdf-dl').length > 0) return;

    var $navbar = $('.navbar-nav').first();
    if ($navbar.length === 0) return;

    var $btn = $('<a>')
        .attr('id', 'btn-wiki-pdf-dl')
        .attr('href', '#')
        .addClass('navbar-link mr-4 d-print-none')
        .css({
            'font-weight': '600',
            'cursor': 'pointer',
            'color': 'var(--text-color)',
            'opacity': '0.9',
            'transition': 'opacity 0.2s'
        })
        .text('Download PDF');

    $btn.hover(
        function () { $(this).css('opacity', '1').css('text-decoration', 'underline'); },
        function () { $(this).css('opacity', '0.9').css('text-decoration', 'none'); }
    );

    $btn.on('click', function (e) {
        e.preventDefault();
        if ($btn.hasClass('disabled')) return;

        var original_text = $btn.text();

        // Give the user clear feedback that generation is happening
        $btn.text('Preparing PDF... (wait 60s)').addClass('disabled').css('opacity', '0.5').css('pointer-events', 'none');

        var current_route = window.location.pathname.replace(/^\/|\/$/g, '');
        var download_url = '/api/method/wiki_pdf.pdf.download_wiki_pdf?route=' + encodeURIComponent(current_route);

        // Trigger download via window.location.href
        // This causes the browser to fetch the file. 
        // Because the server returns "Content-Disposition: attachment", the current page stays open.
        window.location.href = download_url;

        // Reset after 90 seconds (generations can take up to 45s+)
        setTimeout(function () {
            $btn.text(original_text).removeClass('disabled').css('opacity', '0.9').css('pointer-events', 'auto');
        }, 90000);
    });

    var $target = $navbar.find('.sun-moon-container, .navbar-search').first();
    if ($target.length > 0) {
        $target.before($btn);
    } else {
        $navbar.prepend($btn);
    }
}
