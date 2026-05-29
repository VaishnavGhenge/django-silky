(function () {
  'use strict';

  var STORAGE_KEY = 'silk-header';
  var ROOT_ID     = 'silk-root';

  /* ─── Core helpers ───────────────────────────────────────────── */

  function applyHeader(mode) {
    var root = document.getElementById(ROOT_ID);
    if (!root) return;
    root.setAttribute('data-header', mode);
  }

  function save(mode) {
    try { localStorage.setItem(STORAGE_KEY, mode); } catch (e) {}
  }

  function getActive() {
    try {
      return localStorage.getItem(STORAGE_KEY) || 'normal';
    } catch (e) {
      return 'normal';
    }
  }

  /* ─── Apply saved header mode immediately (before paint) ──────── */
  applyHeader(getActive());

  /* ─── DOMContentLoaded init ─────────────────────────────────── */
  document.addEventListener('DOMContentLoaded', function () {
    var saved = getActive();
    applyHeader(saved);

    // Refresh settings-page cards when mode changes
    document.addEventListener('silk-header-changed', function () {
      refreshCards();
    });

    refreshCards();
  });

  /* ─── Settings page card highlight ──────────────────────────── */

  function refreshCards() {
    var active = getActive();
    document.querySelectorAll('.silk-scheme-card[data-header]').forEach(function (card) {
      card.classList.toggle('is-active', card.dataset.header === active);
    });
  }

  /* ─── Expose for settings page ──────────────────────────────── */
  window.silkApplyHeader = function (mode) {
    applyHeader(mode);
    save(mode);
    refreshCards();
    document.dispatchEvent(new CustomEvent('silk-header-changed', { detail: mode }));
  };

}());
