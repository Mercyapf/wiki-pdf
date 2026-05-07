frappe.ready(function () {
    if ($('.wiki-content').length > 0 || window.location.pathname.indexOf('/home') !== -1) {
        setTimeout(setup_wiki_pdf_download, 600);
    }
});

function get_selected_language() {
    var combo = document.querySelector('.goog-te-combo');
    if (combo && combo.value && combo.value !== '' && combo.value !== 'en') {
        return combo.value.split('-')[0];
    }
    var cookies = document.cookie.split(';');
    for (var i = 0; i < cookies.length; i++) {
        var c = cookies[i].trim();
        if (c.indexOf('googtrans=') === 0) {
            var val = c.substring('googtrans='.length).trim();
            var parts = val.split('/');
            if (parts.length >= 3 && parts[2] && parts[2] !== 'en' && parts[2] !== 'auto') {
                return parts[2];
            }
        }
    }
    return 'en';
}

function setup_wiki_pdf_download() {
    if ($('#btn-wiki-pdf-dl').length > 0) return;
    var $navbar = $('.navbar-nav').first();
    if ($navbar.length === 0) return;

    var $btn = $('<a>')
        .attr('id', 'btn-wiki-pdf-dl')
        .attr('href', '#')
        .addClass('navbar-link mr-4 d-print-none')
        .css({ 'font-weight': '600', 'cursor': 'pointer', 'color': 'var(--text-color)', 'opacity': '0.9' })
        .text('Download PDF');

    $btn.hover(
        function () { $(this).css('opacity', '1').css('text-decoration', 'underline'); },
        function () { $(this).css('opacity', '0.9').css('text-decoration', 'none'); }
    );

    $btn.on('click', function (e) {
        e.preventDefault();
        if ($btn.hasClass('disabled')) return;

        var original_text = $btn.text();
        var lang = get_selected_language();
        var current_route = window.location.pathname.replace(/^[\/]+|[\/]+$/g, '');

        $btn.text('Preparing PDF... (' + lang + ')')
            .addClass('disabled')
            .css('opacity', '0.5')
            .css('pointer-events', 'none');

        var url = '/api/method/wiki_pdf.pdf.download_wiki_pdf'
            + '?route=' + encodeURIComponent(current_route)
            + '&lang=' + encodeURIComponent(lang);

        fetch(url)
            .then(function (response) {
                if (response.ok) {
                    // PDF is ready — download it as a blob (no page navigation)
                    return response.blob().then(function (blob) {
                        var a = document.createElement('a');
                        a.href = URL.createObjectURL(blob);
                        a.download = 'Creche_Guideline.pdf';
                        document.body.appendChild(a);
                        a.click();
                        document.body.removeChild(a);
                        URL.revokeObjectURL(a.href);
                        $btn.text(original_text)
                            .removeClass('disabled')
                            .css('opacity', '0.9')
                            .css('pointer-events', 'auto');
                    });
                } else {
                    // 417 = PDF not ready yet (frappe.throw message)
                    $btn.text(original_text)
                        .removeClass('disabled')
                        .css('opacity', '0.9')
                        .css('pointer-events', 'auto');
                    frappe.msgprint({
                        title: 'PDF Not Ready',
                        message: 'The PDF for this language is being prepared in the background. Please try again in a few minutes.',
                        indicator: 'blue'
                    });
                }
            })
            .catch(function () {
                $btn.text(original_text)
                    .removeClass('disabled')
                    .css('opacity', '0.9')
                    .css('pointer-events', 'auto');
                frappe.msgprint({
                    title: 'Download Error',
                    message: 'Could not download the PDF. Please try again.',
                    indicator: 'red'
                });
            });
    });

    var $target = $navbar.find('.sun-moon-container, .navbar-search').first();
    if ($target.length > 0) { $target.before($btn); } else { $navbar.prepend($btn); }
}
