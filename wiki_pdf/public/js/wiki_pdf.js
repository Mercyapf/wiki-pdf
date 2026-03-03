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

        // Give the user clear feedback with a 40s sequence
        $btn.text('Preparing PDF... (wait 40s)').addClass('disabled').css('opacity', '0.5').css('pointer-events', 'none');

        var current_route = window.location.pathname.replace(/^\/|\/$/g, '');
        var download_url = '/api/method/wiki_pdf.pdf.download_wiki_pdf?route=' + encodeURIComponent(current_route);

        // Simple sequence for button reset (total 40s)
        setTimeout(function () {
            $btn.text('Download Started...');
        }, 15000);

        setTimeout(function () {
            $btn.text(original_text).removeClass('disabled').css('opacity', '0.9').css('pointer-events', 'auto');
        }, 40000);

        // Immediate trigger for the browser's download manager
        window.location.href = download_url;
    });

    var $target = $navbar.find('.sun-moon-container, .navbar-search').first();
    if ($target.length > 0) {
        $target.before($btn);
    } else {
        $navbar.prepend($btn);
    }
}
