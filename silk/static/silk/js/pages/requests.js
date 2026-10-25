/* Requests page: filter chips write hidden form fields and resubmit the form,
   which htmx turns into a swap of #req-dynamic. Also keyboard navigation. */
(function () {
  'use strict';

  var SLOW_MS = 1000;

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
          field('filter-overalltime-value').value = field('filter-overalltime-value').value ? '' : SLOW_MS;
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

  // Keyboard: / focuses search, j/k move between rows, Enter opens the row.
  var cursor = -1;
  function rows() { return Array.prototype.slice.call(document.querySelectorAll('#req-dynamic tbody tr')); }
  function paint() {
    rows().forEach(function (tr, i) { tr.classList.toggle('is-cursor', i === cursor); });
    var tr = rows()[cursor];
    if (tr) tr.scrollIntoView({ block: 'nearest' });
  }
  document.addEventListener('keydown', function (e) {
    var typing = /INPUT|SELECT|TEXTAREA/.test(document.activeElement.tagName);
    if (e.key === '/' && !typing) { e.preventDefault(); var s = document.getElementById('req-search'); s.focus(); s.select(); return; }
    if (e.key === 'Escape' && typing) { document.activeElement.blur(); return; }
    if (typing || e.metaKey || e.ctrlKey || e.altKey) return;
    var n = rows().length;
    if (!n) return;
    if (e.key === 'j' || e.key === 'ArrowDown') { e.preventDefault(); cursor = Math.min(n - 1, cursor + 1); paint(); }
    else if (e.key === 'k' || e.key === 'ArrowUp') { e.preventDefault(); cursor = Math.max(0, cursor - 1); paint(); }
    else if (e.key === 'Enter' && cursor >= 0) { var a = rows()[cursor].querySelector('a.row-link'); if (a) a.click(); }
  });
  document.addEventListener('htmx:afterSwap', function () {
    cursor = -1;
    // The search box sits outside the swapped region; keep it in step with the
    // server's filters (e.g. after "Clear filters") unless the user is typing in it.
    var dyn = document.getElementById('req-dynamic'), search = document.getElementById('req-search');
    if (dyn && search && document.activeElement !== search) search.value = dyn.dataset.search || '';
  });
})();
