(function () {
  'use strict';

  var STORAGE_KEY = 'silk-theme';
  var ROOT_ID = 'silk-root';

  function applyTheme(theme) {
    var root = document.getElementById(ROOT_ID);
    if (root) {
      root.setAttribute('data-theme', theme);
    }
  }

  function getSavedTheme() {
    try {
      return localStorage.getItem(STORAGE_KEY) || 'light';
    } catch (e) {
      return 'light';
    }
  }

  function saveTheme(theme) {
    try {
      localStorage.setItem(STORAGE_KEY, theme);
    } catch (e) {}
  }

  function toggleTheme() {
    var root = document.getElementById(ROOT_ID);
    var current = root ? root.getAttribute('data-theme') : 'light';
    var next = current === 'dark' ? 'light' : 'dark';
    applyTheme(next);
    saveTheme(next);
    updateToggleButton(next);
    document.dispatchEvent(new CustomEvent('silk-theme-changed'));
  }

  function updateToggleButton(theme) {
    var btn = document.getElementById('silk-theme-toggle');
    if (!btn) return;
    var icon = btn.querySelector('[data-lucide]');
    var label = btn.querySelector('.silk-theme-label');
    if (icon) {
      icon.setAttribute('data-lucide', theme === 'dark' ? 'sun' : 'moon');
      if (window.lucide) {
        lucide.createIcons();
      }
    }
    if (label) {
      label.textContent = theme === 'dark' ? 'Light' : 'Dark';
    }
  }

  // Apply saved theme immediately (before paint) to prevent flash
  applyTheme(getSavedTheme());

  document.addEventListener('DOMContentLoaded', function () {
    var saved = getSavedTheme();
    applyTheme(saved);

    var btn = document.getElementById('silk-theme-toggle');
    if (btn) {
      btn.addEventListener('click', toggleTheme);
      updateToggleButton(saved);
    }

    if (window.lucide) {
      lucide.createIcons();
    }
  });
}());
