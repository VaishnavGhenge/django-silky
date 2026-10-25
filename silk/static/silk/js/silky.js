/* Silky shell: theme, accent, layout and sidebar behaviour shared by every page.
   The inline script in base.html applies saved choices before first paint;
   this file wires up the controls and keeps them in sync. */
(function () {
  'use strict';

  var root = document.documentElement;
  var THEMES = ['system', 'light', 'dark'];

  function read(key, fallback) { try { return localStorage.getItem(key) || fallback; } catch (e) { return fallback; } }
  function write(key, value) { try { localStorage.setItem(key, value); } catch (e) { /* private mode */ } }

  function setAttr(name, value, defaultValue) {
    if (value === defaultValue) delete root.dataset[name]; else root.dataset[name] = value;
  }

  var silky = window.silky = {
    theme: function () { return read('silky-theme', 'system'); },
    accent: function () { return read('silky-accent', 'green'); },
    layout: function () { return read('silky-layout', 'sidebar'); },

    setTheme: function (t) { write('silky-theme', t); setAttr('theme', t, 'system'); silky.sync(); },
    setAccent: function (a) { write('silky-accent', a); setAttr('accent', a, 'green'); silky.sync(); },
    setLayout: function (l) { write('silky-layout', l); setAttr('layout', l, 'sidebar'); silky.sync(); },
    setRail: function (on) { write('silky-rail', on ? '1' : '0'); setAttr('rail', on ? '1' : '0', '0'); },

    cycleTheme: function () {
      var next = THEMES[(THEMES.indexOf(silky.theme()) + 1) % THEMES.length];
      silky.setTheme(next);
      silky.toast('Theme: ' + next);
    },

    // Swap the icon drawn by an <svg data-icon> element.
    setIcon: function (svg, name) {
      svg.setAttribute('data-icon', name);
      var use = svg.querySelector('use');
      if (use) use.setAttribute('href', '#i-' + name);
    },

    toast: function (msg) {
      var el = document.getElementById('silky-toast');
      if (!el) return;
      el.textContent = msg;
      el.classList.add('is-on');
      clearTimeout(silky._toastTimer);
      silky._toastTimer = setTimeout(function () { el.classList.remove('is-on'); }, 1600);
    },

    // Reflect current choices in any controls on the page.
    sync: function () {
      document.querySelectorAll('[data-theme-label]').forEach(function (el) { el.textContent = 'Theme: ' + silky.theme(); });
      document.querySelectorAll('[data-set-theme]').forEach(function (b) { b.setAttribute('aria-pressed', String(b.dataset.setTheme === silky.theme())); });
      document.querySelectorAll('[data-set-accent]').forEach(function (b) { b.setAttribute('aria-pressed', String(b.dataset.setAccent === silky.accent())); });
      document.querySelectorAll('[data-set-layout]').forEach(function (b) { b.setAttribute('aria-pressed', String(b.dataset.setLayout === silky.layout())); });
    }
  };
  window.setIcon = silky.setIcon; // used by older page scripts

  // ── Copy to clipboard: <button data-copy-from="#id" data-copy-label="Copied"> ──
  silky.copy = function (text, label) {
    function done() { silky.toast(label || 'Copied'); }
    function fallback() {
      var t = document.createElement('textarea');
      t.value = text; document.body.appendChild(t); t.select();
      try { document.execCommand('copy'); done(); } catch (e) { silky.toast('Copy failed'); }
      t.remove();
    }
    if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(text).then(done, fallback);
    else fallback();
  };

  // ── Open-in-editor links: <a data-editor-file="/path" data-editor-line="12"> ──
  // The editor (and an optional container-to-local path mapping) are per-browser preferences.
  var EDITORS = {
    vscode: function (f, l) { return 'vscode://file' + encodeURI(f) + ':' + l; },
    cursor: function (f, l) { return 'cursor://file' + encodeURI(f) + ':' + l; },
    pycharm: function (f, l) { return 'pycharm://open?file=' + encodeURIComponent(f) + '&line=' + l; },
    sublime: function (f, l) { return 'subl://open?url=file://' + encodeURIComponent(f) + '&line=' + l; }
  };
  silky.editorHref = function (file, line) {
    var from = read('silky-path-from', ''), to = read('silky-path-to', '');
    if (from && file.indexOf(from) === 0) file = to + file.slice(from.length);
    var editor = EDITORS[read('silky-editor', 'vscode')];
    return editor ? editor(file, line) : null;
  };
  silky.linkEditors = function (scope) {
    (scope || document).querySelectorAll('[data-editor-file]').forEach(function (a) {
      var href = silky.editorHref(a.dataset.editorFile, a.dataset.editorLine || 1);
      if (href) a.setAttribute('href', href); else a.removeAttribute('href');
    });
  };
  document.addEventListener('DOMContentLoaded', function () { silky.linkEditors(); });
  document.addEventListener('htmx:afterSettle', function (e) { silky.linkEditors(e.target); });

  // Dropdown menus: <div class="menu"><button data-menu-toggle>…</button><div class="menu__list" hidden>…</div></div>
  function closeMenus(except) {
    document.querySelectorAll('.menu__list:not([hidden])').forEach(function (list) {
      if (list === except) return;
      list.hidden = true;
      var btn = list.parentNode.querySelector('[data-menu-toggle]');
      if (btn) btn.setAttribute('aria-expanded', 'false');
    });
  }
  document.addEventListener('click', function (e) {
    var copyBtn = e.target.closest('[data-copy-from]');
    if (copyBtn) {
      var src = document.querySelector(copyBtn.dataset.copyFrom);
      if (src) silky.copy(src.value !== undefined && src.tagName === 'TEXTAREA' ? src.value : src.textContent, copyBtn.dataset.copyLabel);
      return;
    }
    var toggle = e.target.closest('[data-menu-toggle]');
    if (toggle) {
      var list = toggle.parentNode.querySelector('.menu__list');
      closeMenus(list);
      list.hidden = !list.hidden;
      toggle.setAttribute('aria-expanded', String(!list.hidden));
      if (!list.hidden) { var current = list.querySelector('[aria-checked="true"]') || list.querySelector('a, button'); if (current) current.focus(); }
      return;
    }
    if (!e.target.closest('.menu__list') || e.target.closest('a, button')) closeMenus();
  });
  document.addEventListener('keydown', function (e) {
    var list = e.target.closest && e.target.closest('.menu__list');
    if (!list) return;
    var items = Array.prototype.slice.call(list.querySelectorAll('a, button')), i = items.indexOf(document.activeElement);
    if (e.key === 'ArrowDown') { e.preventDefault(); items[(i + 1) % items.length].focus(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); items[(i - 1 + items.length) % items.length].focus(); }
    else if (e.key === 'Escape') { closeMenus(); var b = list.parentNode.querySelector('[data-menu-toggle]'); if (b) b.focus(); }
  });

  document.addEventListener('click', function (e) {
    var t = e.target.closest('[data-action], [data-set-theme], [data-set-accent], [data-set-layout]');
    if (!t) return;
    if (t.dataset.setTheme) return silky.setTheme(t.dataset.setTheme);
    if (t.dataset.setAccent) return silky.setAccent(t.dataset.setAccent);
    if (t.dataset.setLayout) return silky.setLayout(t.dataset.setLayout);
    var sidebar = document.getElementById('sidebar'), scrim = document.getElementById('scrim');
    switch (t.dataset.action) {
      case 'cycle-theme': silky.cycleTheme(); break;
      case 'toggle-rail': silky.setRail(root.dataset.rail !== '1'); break;
      case 'open-nav': sidebar.classList.add('is-open'); scrim.hidden = false; break;
      case 'close-nav': sidebar.classList.remove('is-open'); scrim.hidden = true; break;
    }
  });
  document.addEventListener('keydown', function (e) {
    var sidebar = document.getElementById('sidebar');
    if (e.key === 'Escape' && sidebar && sidebar.classList.contains('is-open')) {
      sidebar.classList.remove('is-open');
      document.getElementById('scrim').hidden = true;
    }
  });
  document.addEventListener('DOMContentLoaded', silky.sync);
})();
