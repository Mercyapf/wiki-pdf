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
        console.log('Detected language:', lang);
        $btn.text('Preparing PDF... (' + lang + ')')
            .addClass('disabled')
            .css('opacity', '0.5')
            .css('pointer-events', 'none');
        var current_route = window.location.pathname.replace(/^[\/]+|[\/]+$/g, '');
        console.log('Detected route for PDF download:', current_route);
        var $form = $('<form>')
            .attr('method', 'GET')
            .attr('action', '/api/method/wiki_pdf.pdf.download_wiki_pdf')
            .attr('target', '_self')
            .css('display', 'none');
        $form.append($('<input>').attr('type', 'hidden').attr('name', 'route').attr('value', current_route));
        $form.append($('<input>').attr('type', 'hidden').attr('name', 'lang').attr('value', lang));
        $('body').append($form);
        setTimeout(function () { $form[0].submit(); }, 200);
        setTimeout(function () {
            $btn.text(original_text).removeClass('disabled').css('opacity', '0.9').css('pointer-events', 'auto');
        }, 40000);
    });
    var $target = $navbar.find('.sun-moon-container, .navbar-search').first();
    if ($target.length > 0) { $target.before($btn); } else { $navbar.prepend($btn); }
}
