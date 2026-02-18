(function () {
  'use strict';

  /* ─── Filter bar toggle ─────────────────────────────────────── */

  function silkFilterToggle() {
    var bar = document.getElementById('silk-filter-bar');
    var btn = document.getElementById('silk-filter-toggle');
    if (!bar) return;
    var isHidden = bar.hasAttribute('hidden');
    if (isHidden) {
      bar.removeAttribute('hidden');
      if (btn) btn.setAttribute('aria-expanded', 'true');
      try { localStorage.setItem('silk-filter-open', '1'); } catch (e) {}
    } else {
      bar.setAttribute('hidden', '');
      if (btn) btn.setAttribute('aria-expanded', 'false');
      try { localStorage.setItem('silk-filter-open', '0'); } catch (e) {}
    }
  }

  /* ─── Time preset ───────────────────────────────────────────── */

  function silkSetSeconds(btn, seconds) {
    var input = document.getElementById('silk-seconds-val');
    if (input) input.value = seconds;
    document.querySelectorAll('.silk-preset-btn').forEach(function (b) {
      b.classList.remove('silk-preset-btn--active');
    });
    if (btn) btn.classList.add('silk-preset-btn--active');
  }

  // kept for any legacy references
  function silkFilterPreset(key) {
    silkSetSeconds(null, key);
  }

  /* ─── Method toggle ─────────────────────────────────────────── */

  function silkFilterMethod(btn, method) {
    var input = document.getElementById('silk-method-value');
    var isActive = btn.classList.contains('silk-method-btn--active');
    // Deactivate all method buttons
    document.querySelectorAll('.silk-method-btn').forEach(function (b) {
      b.classList.remove('silk-method-btn--active');
    });
    if (!isActive) {
      btn.classList.add('silk-method-btn--active');
      if (input) input.value = method;
    } else {
      if (input) input.value = '';
    }
  }

  /* ─── Sort chips ────────────────────────────────────────────── */

  function _getSortList() {
    var input = document.getElementById('silk-sort-criteria');
    if (!input) return [];
    try {
      return JSON.parse(input.value) || [];
    } catch (e) {
      return [];
    }
  }

  function _setSortList(list) {
    var input = document.getElementById('silk-sort-criteria');
    if (input) input.value = JSON.stringify(list);
  }

  function _submitSortForm() {
    var form = document.getElementById('silk-sort-form');
    if (form) form.submit();
  }

  function silkSortToggleDir(btn) {
    var chip = btn.closest('.silk-sort-chip');
    if (!chip) return;
    var field = chip.dataset.field;
    var list = _getSortList();
    list = list.map(function (item) {
      if (item.field === field) {
        return { field: field, dir: item.dir === 'DESC' ? 'ASC' : 'DESC' };
      }
      return item;
    });
    _setSortList(list);
    _submitSortForm();
  }

  function silkSortRemove(btn) {
    var chip = btn.closest('.silk-sort-chip');
    if (!chip) return;
    var field = chip.dataset.field;
    var list = _getSortList().filter(function (item) {
      return item.field !== field;
    });
    _setSortList(list);
    _submitSortForm();
  }

  function silkSortToggleMenu(event) {
    event.stopPropagation();
    var menu = document.getElementById('silk-sort-menu');
    var addBtn = document.getElementById('silk-sort-add-btn');
    if (!menu) return;
    var hidden = menu.hasAttribute('hidden');
    if (hidden) {
      menu.removeAttribute('hidden');
      if (addBtn) addBtn.setAttribute('aria-expanded', 'true');
    } else {
      menu.setAttribute('hidden', '');
      if (addBtn) addBtn.setAttribute('aria-expanded', 'false');
    }
  }

  function silkSortAdd(field, label) {
    var list = _getSortList();
    // Avoid duplicates
    var exists = list.some(function (item) { return item.field === field; });
    if (!exists) {
      list.push({ field: field, dir: 'DESC' });
      _setSortList(list);
      _submitSortForm();
    }
    // Close menu
    var menu = document.getElementById('silk-sort-menu');
    if (menu) menu.setAttribute('hidden', '');
  }

  /* ─── Close sort menu on outside click ──────────────────────── */

  document.addEventListener('click', function (e) {
    var menu = document.getElementById('silk-sort-menu');
    var addWrapper = document.getElementById('silk-sort-add-wrapper');
    if (menu && !menu.hasAttribute('hidden') && addWrapper && !addWrapper.contains(e.target)) {
      menu.setAttribute('hidden', '');
      var addBtn = document.getElementById('silk-sort-add-btn');
      if (addBtn) addBtn.setAttribute('aria-expanded', 'false');
    }
  });

  /* ─── Expose helpers to window for inline onclick attributes ── */

  window.silkFilterToggle = silkFilterToggle;
  window.silkSetSeconds = silkSetSeconds;
  window.silkFilterPreset = silkFilterPreset;
  window.silkFilterMethod = silkFilterMethod;
  window.silkSortToggleDir = silkSortToggleDir;
  window.silkSortRemove = silkSortRemove;
  window.silkSortToggleMenu = silkSortToggleMenu;
  window.silkSortAdd = silkSortAdd;

  /* ─── Init ──────────────────────────────────────────────────── */

  document.addEventListener('DOMContentLoaded', function () {
    if (window.lucide) {
      lucide.createIcons();
    }

    // Restore filter bar open/closed state
    try {
      if (localStorage.getItem('silk-filter-open') === '1') {
        var bar = document.getElementById('silk-filter-bar');
        var btn = document.getElementById('silk-filter-toggle');
        if (bar) {
          bar.removeAttribute('hidden');
          if (btn) btn.setAttribute('aria-expanded', 'true');
        }
      }
    } catch (e) {}

    // Reflect current sort + per_page in the browser URL so the page is shareable.
    // Uses history.replaceState — no navigation, just updates the address bar.
    try {
      var sortInput = document.getElementById('silk-sort-criteria');
      var perPageSelect = document.querySelector('select[name="per_page"]');
      if (sortInput || perPageSelect) {
        var params = new URLSearchParams(window.location.search);
        if (sortInput && sortInput.value) {
          params.set('sort_criteria', sortInput.value);
        }
        if (perPageSelect && perPageSelect.value) {
          params.set('per_page', perPageSelect.value);
        }
        var newUrl = window.location.pathname + '?' + params.toString();
        history.replaceState(null, '', newUrl);
      }
    } catch (e) {}
  });

}());
