// Command palette (Ctrl/Cmd+K), the shortcuts sheet (?) and global keys:
// g then a letter goes to a page, t cycles the theme, / focuses the page search.
// Page elements marked data-palette="Label" show up as actions and are clicked when chosen.
(function () {
  var NAV = [['r', 'Requests'], ['s', 'SQL'], ['h', 'Hotspots'], ['d', 'Summary'], ['p', 'Profiling'], ['c', 'Compare'], [',', 'Settings']];
  var urls = {}, overlay, pending = null;

  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function go(key) { if (urls[key]) location.href = urls[key]; }
  function hide() { overlay.hidden = true; overlay.innerHTML = ''; }
  function typing(el) { return el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName)); }

  function commands() {
    var list = NAV.map(function (n) { return { group: 'Go to', label: n[1], hint: 'g ' + n[0], run: function () { go(n[0]); } }; });
    document.querySelectorAll('[data-palette]').forEach(function (el) {
      list.push({ group: 'On this page', label: el.dataset.palette, run: function () { el.click(); } });
    });
    var s = window.silky;
    list.push(
      { group: 'Appearance', label: 'Toggle theme', hint: 't', run: function () { s.cycleTheme(); } },
      { group: 'Appearance', label: 'Light theme', run: function () { s.setTheme('light'); } },
      { group: 'Appearance', label: 'Dark theme', run: function () { s.setTheme('dark'); } },
      { group: 'Appearance', label: 'Switch to ' + (s.layout() === 'top' ? 'sidebar' : 'top tabs'), run: function () { s.setLayout(s.layout() === 'top' ? 'sidebar' : 'top'); } }
    );
    ['green', 'blue', 'violet', 'graphite'].forEach(function (a) {
      list.push({ group: 'Appearance', label: 'Accent: ' + a, run: function () { s.setAccent(a); } });
    });
    list.push({ group: 'Help', label: 'Keyboard shortcuts', hint: '?', run: showHelp });
    return list;
  }

  function showPalette() {
    var all = commands(), shown = all, on = 0;
    overlay.innerHTML = '<div class="pal" role="dialog" aria-label="Command palette"><input class="pal__input" placeholder="Go to a page or run a command" aria-label="Command" autocomplete="off" spellcheck="false">' +
      '<div class="pal__list" role="listbox"></div><div class="pal__foot"><span><kbd>↑</kbd><kbd>↓</kbd>move</span><span><kbd>↵</kbd>run</span><span><kbd>esc</kbd>close</span></div></div>';
    overlay.hidden = false;
    var input = overlay.querySelector('.pal__input'), box = overlay.querySelector('.pal__list');
    function render() {
      var q = input.value.trim().toLowerCase();
      shown = all.filter(function (c) { return !q || (c.group + ' ' + c.label).toLowerCase().indexOf(q) >= 0; });
      on = Math.min(on, Math.max(0, shown.length - 1));
      var group = '';
      box.innerHTML = shown.length ? shown.map(function (c, i) {
        var head = c.group !== group ? '<div class="pal__group">' + esc(group = c.group) + '</div>' : '';
        return head + '<button type="button" class="pal__item' + (i === on ? ' is-on' : '') + '" data-i="' + i + '" role="option"><span>' + esc(c.label) + '</span>' + (c.hint ? '<kbd>' + esc(c.hint) + '</kbd>' : '') + '</button>';
      }).join('') : '<div class="pal__empty">No command matches.</div>';
      var cur = box.querySelector('.is-on'); if (cur) cur.scrollIntoView({ block: 'nearest' });
    }
    function run(i) { var c = shown[i]; if (!c) return; hide(); c.run(); }
    input.addEventListener('input', function () { on = 0; render(); });
    input.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowDown') { e.preventDefault(); on = (on + 1) % Math.max(1, shown.length); render(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); on = (on - 1 + shown.length) % Math.max(1, shown.length); render(); }
      else if (e.key === 'Enter') { e.preventDefault(); run(on); }
    });
    box.addEventListener('click', function (e) { var b = e.target.closest('[data-i]'); if (b) run(+b.dataset.i); });
    render();
    input.focus();
  }

  function showHelp() {
    var keys = [['⌘K / Ctrl K', 'Command palette'], ['/', 'Focus the page search'], ['j / k', 'Next or previous request (Requests)'], ['↵', 'Open the selected request'], ['esc', 'Close a panel or dialog']]
      .concat(NAV.map(function (n) { return ['g ' + n[0], 'Go to ' + n[1]]; }), [['t', 'Toggle theme'], ['?', 'This help']]);
    overlay.innerHTML = '<div class="pal pal--help" role="dialog" aria-label="Keyboard shortcuts"><div class="pal__title">Keyboard shortcuts</div><div class="keys">' +
      keys.map(function (k) { return '<kbd>' + esc(k[0]) + '</kbd><span>' + esc(k[1]) + '</span>'; }).join('') + '</div></div>';
    overlay.hidden = false;
  }

  document.addEventListener('DOMContentLoaded', function () {
    overlay = document.getElementById('silky-overlay');
    try { urls = JSON.parse(document.getElementById('silky-nav').textContent); } catch (e) { urls = {}; }
    overlay.addEventListener('mousedown', function (e) { if (e.target === overlay) hide(); });
  });
  document.addEventListener('click', function (e) { if (e.target.closest('[data-action="shortcuts"]')) showHelp(); });

  document.addEventListener('keydown', function (e) {
    if (!overlay) return;
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); if (overlay.hidden) showPalette(); else hide(); return; }
    if (!overlay.hidden) { if (e.key === 'Escape') { e.preventDefault(); e.stopImmediatePropagation(); hide(); } return; }
    if (e.metaKey || e.ctrlKey || e.altKey || typing(e.target) || document.querySelector('dialog[open]')) return;
    if (pending) { clearTimeout(pending); pending = null; if (urls[e.key]) { e.preventDefault(); go(e.key); } return; }
    if (e.key === 'g') { pending = setTimeout(function () { pending = null; }, 1200); return; }
    if (e.key === '?') { e.preventDefault(); showHelp(); return; }
    if (e.key === 't') { window.silky.cycleTheme(); return; }
    if (e.key === '/') {
      var search = document.querySelector('.search input, input[type="search"]');
      if (search) { e.preventDefault(); search.focus(); search.select(); }
    }
  }, true);
})();
