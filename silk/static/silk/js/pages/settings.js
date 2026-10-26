// Settings: editor and path mapping, thresholds (cookies, so the server can use them),
// chart and sidebar preferences, and the clear-data confirmation.
(function () {
  var s = window.silky;

  function pressed(selector, attr, value) {
    document.querySelectorAll(selector).forEach(function (b) { b.setAttribute('aria-pressed', String(b.getAttribute(attr) === value)); });
  }
  function refreshEditor() {
    pressed('[data-editor]', 'data-editor', s.read('silky-editor', 'vscode'));
    s.linkEditors();
    var preview = document.getElementById('editor-preview');
    if (preview) preview.textContent = preview.getAttribute('href') || 'nothing (links are off)';
  }
  function setCookie(name, value) {
    document.cookie = name + '=' + encodeURIComponent(value) + '; path=/; max-age=31536000; SameSite=Lax';
  }

  document.addEventListener('DOMContentLoaded', function () {
    var from = document.getElementById('path-from'), to = document.getElementById('path-to');
    from.value = s.read('silky-path-from', '');
    to.value = s.read('silky-path-to', '');
    [[from, 'silky-path-from'], [to, 'silky-path-to']].forEach(function (pair) {
      pair[0].addEventListener('input', function () { s.write(pair[1], pair[0].value); refreshEditor(); });
    });
    refreshEditor();
    pressed('[data-charts]', 'data-charts', s.read('silky-charts', 'shown'));
    var rail = document.getElementById('rail-toggle');
    rail.checked = s.read('silky-rail', '0') === '1';
    rail.addEventListener('change', function () { s.setRail(rail.checked); });

    var dialog = document.getElementById('clear-dialog'), confirm = document.getElementById('clear-confirm');
    confirm.addEventListener('input', function () {
      dialog.querySelector('[name="clear_all"]').disabled = confirm.value.trim().toLowerCase() !== 'clear';
    });
  });

  // Counts on this page and in the sidebar are rendered with the old thresholds.
  function reloadSoon() { setTimeout(function () { location.reload(); }, 900); }

  document.addEventListener('click', function (e) {
    var ed = e.target.closest('[data-editor]');
    if (ed) { s.write('silky-editor', ed.dataset.editor); refreshEditor(); s.toast('Editor: ' + ed.textContent); return; }
    var ch = e.target.closest('[data-charts]');
    if (ch) {
      s.write('silky-charts', ch.dataset.charts);
      try { localStorage.removeItem('silky-hidden-charts'); } catch (err) { /* private mode */ }
      pressed('[data-charts]', 'data-charts', ch.dataset.charts);
      s.toast(ch.dataset.charts === 'hidden' ? 'Charts hidden' : 'Charts shown');
      return;
    }
    if (e.target.closest('[data-apply-thresholds]')) {
      var slow = Math.max(50, +document.getElementById('slow-ms').value || 1000);
      var ok = Math.max(10, Math.min(slow - 1, +document.getElementById('ok-ms').value || 300));
      setCookie('silky-slow-ms', slow);
      setCookie('silky-ok-ms', ok);
      document.getElementById('slow-ms').value = slow;
      document.getElementById('ok-ms').value = ok;
      s.toast('Thresholds saved: amber from ' + ok + ' ms, red from ' + slow + ' ms');
      reloadSoon();
      return;
    }
    if (e.target.closest('[data-reset-thresholds]')) {
      ['slow-ms', 'ok-ms'].forEach(function (id) { var el = document.getElementById(id); el.value = el.dataset.default; });
      setCookie('silky-slow-ms', document.getElementById('slow-ms').value);
      setCookie('silky-ok-ms', document.getElementById('ok-ms').value);
      s.toast('Thresholds reset');
      reloadSoon();
      return;
    }
    var c = e.target.closest('[data-confirm]');
    if (c && !window.confirm(c.dataset.confirm)) { e.preventDefault(); return; }
    if (e.target.closest('[data-clear-all]')) {
      var dialog = document.getElementById('clear-dialog');
      dialog.showModal();
      document.getElementById('clear-confirm').focus();
      return;
    }
    if (e.target.closest('[data-dialog-close]')) e.target.closest('dialog').close();
  });
})();
