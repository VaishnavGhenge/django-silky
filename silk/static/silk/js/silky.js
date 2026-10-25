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
