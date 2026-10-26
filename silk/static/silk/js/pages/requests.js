/* Requests page: filter chips write hidden form fields and resubmit the form,
   which htmx turns into a swap of #req-dynamic. Also keyboard navigation. */
(function () {
  'use strict';

  var SLOW_MS = 1000;
  var cursor = -1;

  function form() { return document.getElementById('req-form'); }
  function field(name) { return form().querySelector('[name="' + name + '"]'); }
  function submit() { var f = form(); if (f.requestSubmit) f.requestSubmit(); else f.submit(); }

  function readList(name) {
    var v = field(name).value;
    if (!v) return [];
    try { var parsed = JSON.parse(v); return Array.isArray(parsed) ? parsed : [parsed]; } catch (e) { return [v]; }
  }
  function writeList(name, list) { field(name).value = list.length ? JSON.stringify(list) : ''; }
  function toggle(list, v) { var i = list.indexOf(v); if (i >= 0) list.splice(i, 1); else list.push(v); return list; }

  document.addEventListener('click', function (e) {
    var chip = e.target.closest('[data-chip]');
    if (chip && form() && form().contains(chip)) {
      switch (chip.dataset.chip) {
        case 'seconds':
          field('filter-seconds-value').value = chip.dataset.value;
          break;
        case 'method':
          writeList('filter-method-value', toggle(readList('filter-method-value'), chip.dataset.value));
          break;
        case 'status': {
          // A class chip (4xx) stands for every recorded code in that class.
          var codes = JSON.parse(chip.dataset.codes), current = readList('filter-status_code-value').map(Number);
          var allOn = codes.every(function (c) { return current.indexOf(c) >= 0; });
          current = current.filter(function (c) { return codes.indexOf(c) < 0; });
          writeList('filter-status_code-value', allOn ? current : current.concat(codes));
          break;
        }
        case 'slow':
          field('filter-overalltime-value').value = field('filter-overalltime-value').value ? '' : (chip.dataset.slowMs || SLOW_MS);
          break;
        case 'flag': {
          var f = field('filter-' + chip.dataset.field + '-value');
          f.value = f.value ? '' : '1';
          break;
        }
      }
      submit();
      return;
    }
    var clear = e.target.closest('[data-clear]');
    if (clear) { field(clear.dataset.clear).value = ''; submit(); }
  });

  document.addEventListener('change', function (e) {
    if (e.target.matches('[data-submit-on-change]')) submit();
  });

  // ── Side panel: a row opens its request beside the list (htmx loads it into #req-panel) ──
  function panel() { return document.getElementById('req-panel'); }
  function split() { return document.getElementById('req-split'); }
  function markOpen(id) {
    document.querySelectorAll('#req-dynamic tbody tr').forEach(function (tr) { tr.classList.toggle('is-open', tr.dataset.id === id); });
  }
  function closePanel(push) {
    var p = panel();
    if (!p || p.hidden) return;
    p.hidden = true;
    p.innerHTML = '';
    split().classList.remove('has-detail');
    markOpen(null);
    if (push) history.pushState(null, '', split().dataset.listUrl);
  }
  // Panel tabs switch in place; the chosen tab stays chosen as you move between requests.
  var panelTab = 'overview';
  function showTab(name) {
    var p = panel();
    if (!p || !p.querySelector('[data-rp-pane="' + name + '"]')) name = 'overview';
    panelTab = name;
    p.querySelectorAll('[data-rp-tab]').forEach(function (b) { b.setAttribute('aria-selected', String(b.dataset.rpTab === name)); });
    p.querySelectorAll('[data-rp-pane]').forEach(function (pane) { pane.hidden = pane.dataset.rpPane !== name; });
  }
  // SQL tab: timeline or grouped by shape, also kept while moving between requests.
  var sqlView = 'timeline';
  function showSqlView(name) {
    var p = panel();
    if (!p) return;
    sqlView = name;
    p.querySelectorAll('.seg [data-sql-view]').forEach(function (b) { b.setAttribute('aria-pressed', String(b.dataset.sqlView === name)); });
    p.querySelectorAll('[data-sql-pane]').forEach(function (pane) { pane.hidden = pane.dataset.sqlPane !== name; });
    var axis = p.querySelector('.wf__axis');
    if (axis) axis.hidden = name !== 'timeline';
  }
  document.addEventListener('click', function (e) {
    var t = e.target.closest('[data-rp-tab]');
    if (t) showTab(t.dataset.rpTab);
    var v = e.target.closest('[data-sql-view]');
    if (v) showSqlView(v.dataset.sqlView);
  });
  document.addEventListener('htmx:afterSwap', function (e) {
    if (e.detail.target !== panel()) return;
    var p = panel(), rp = p.querySelector('.rp');
    showTab(panelTab);
    showSqlView(sqlView);
    if (window.hljs) p.querySelectorAll('pre code[class*="language-"]').forEach(function (c) { window.hljs.highlightElement(c); });
    p.hidden = false;
    p.scrollTop = 0;
    split().classList.add('has-detail');
    markOpen(rp ? rp.dataset.requestId : null);
    // Keep the keyboard cursor on the open row so j/k continue from it.
    cursor = rows().findIndex(function (tr) { return tr.classList.contains('is-open'); });
    paintOnly();
  });
  // Ctrl/Cmd/Shift/middle click keeps the browser's own behaviour (open the full page in a new tab).
  document.addEventListener('click', function (e) {
    if (e.target.closest('a.row-link') && (e.metaKey || e.ctrlKey || e.shiftKey || e.button === 1)) e.stopPropagation();
    if (e.target.closest('[data-panel-close]')) closePanel(true);
  }, true);
  // Back/forward to the list URL closes the panel.
  window.addEventListener('popstate', function () {
    if (!/\/request\//.test(location.pathname)) closePanel(false);
  });

  // Keyboard: / focuses search, j/k move between rows, Enter opens the row.

  function rows() { return Array.prototype.slice.call(document.querySelectorAll('#req-dynamic tbody tr')); }
  function paintOnly() { rows().forEach(function (tr, i) { tr.classList.toggle('is-cursor', i === cursor); }); }
  function paint() {
    rows().forEach(function (tr, i) { tr.classList.toggle('is-cursor', i === cursor); });
    var tr = rows()[cursor];
    if (!tr) return;
    tr.scrollIntoView({ block: 'nearest' });
    // With the panel open, moving the cursor opens that request.
    if (panel() && !panel().hidden) { var a = tr.querySelector('a.row-link'); if (a) a.click(); }
  }
  document.addEventListener('keydown', function (e) {
    var typing = /INPUT|SELECT|TEXTAREA/.test(document.activeElement.tagName);
    if (e.key === '/' && !typing) { e.preventDefault(); var s = document.getElementById('top-q'); s.focus(); s.select(); return; }
    if (e.key === 'Escape' && typing) { document.activeElement.blur(); return; }
    if (e.key === 'Escape' && panel() && !panel().hidden) { closePanel(true); return; }
    if (typing || e.metaKey || e.ctrlKey || e.altKey) return;
    var n = rows().length;
    if (!n) return;
    if (e.key === 'j' || e.key === 'ArrowDown') { e.preventDefault(); cursor = Math.min(n - 1, cursor + 1); paint(); }
    else if (e.key === 'k' || e.key === 'ArrowUp') { e.preventDefault(); cursor = Math.max(0, cursor - 1); paint(); }
    else if (e.key === 'Enter' && cursor >= 0) { var a = rows()[cursor].querySelector('a.row-link'); if (a) a.click(); }
  });
  document.addEventListener('htmx:afterSwap', function (e) {
    if (e.detail.target === panel()) return; // panel loads keep the cursor
    cursor = -1;
    // The search box sits outside the swapped region; keep it in step with the
    // server's filters (e.g. after "Clear filters") unless the user is typing in it.
    var dyn = document.getElementById('req-dynamic'), search = document.getElementById('top-q');
    if (dyn && search && document.activeElement !== search) search.value = dyn.dataset.search || '';
  });
})();
