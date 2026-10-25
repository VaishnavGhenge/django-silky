// Call graph for a request's cProfile data. viz-lite is 1.8 MB, so it and
// svg-pan-zoom load only when the user asks for the graph.
(function () {
  var loaded = null;

  function loadScript(src) {
    return new Promise(function (resolve, reject) {
      var s = document.createElement('script');
      s.src = src; s.onload = resolve; s.onerror = function () { reject(new Error('Could not load ' + src)); };
      document.head.appendChild(s);
    });
  }

  function loadLibs(root) {
    if (!loaded) {
      loaded = loadScript(root.dataset.vizSrc).then(function () { return loadScript(root.dataset.panSrc); });
    }
    return loaded;
  }

  function draw(root) {
    var box = root.querySelector('[data-graph-box]');
    var cutoff = root.querySelector('[data-graph-cutoff]').value || '5';
    box.innerHTML = '<div class="graph__empty">Drawing the call graph…</div>';
    return loadLibs(root)
      .then(function () { return fetch(root.dataset.dotUrl + '?cutoff=' + encodeURIComponent(cutoff), { credentials: 'same-origin' }); })
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function (data) {
        box.innerHTML = window.Viz(data.dot);
        var svg = box.querySelector('svg');
        if (svg) { svg.removeAttribute('width'); svg.removeAttribute('height'); window.svgPanZoom(svg, { controlIconsEnabled: true }); }
      })
      .catch(function (e) { box.innerHTML = '<div class="graph__empty">Could not draw the graph: ' + e.message + '</div>'; });
  }

  document.addEventListener('click', function (e) {
    var btn = e.target.closest('[data-graph-draw]');
    if (!btn) return;
    var root = btn.closest('[data-callgraph]');
    root.querySelector('[data-graph-cutoff]').disabled = false;
    btn.textContent = 'Redraw';
    draw(root);
  });

  document.addEventListener('change', function (e) {
    var input = e.target.closest('[data-graph-cutoff]');
    if (input && loaded) draw(input.closest('[data-callgraph]'));
  });
})();
