document.addEventListener('DOMContentLoaded', function () {
  // Highlight all pre>code blocks
  hljs.highlightAll();

  // Post-process: wrap each line in a span and mark active lines
  document.querySelectorAll('pre[data-active-indices]').forEach(function (pre) {
    var code = pre.querySelector('code');
    if (!code) return;
    var activeIndices;
    try { activeIndices = new Set(JSON.parse(pre.dataset.activeIndices)); } catch (e) { return; }
    if (!activeIndices.size) return;

    var lines = code.innerHTML.split('\n');
    code.innerHTML = lines.map(function (line, i) {
      var cls = activeIndices.has(i) ? ' the-line' : '';
      return '<span class="silk-code-line' + cls + '">' + line + '</span>';
    }).join(''); // no \n joiner — pre preserves whitespace so \n would add blank lines
  });

  // Copy Code
  document.addEventListener('click', function (e) {
    var copyBtn = e.target.closest('.silk-pre__copy');
    if (!copyBtn) return;

    var pre = copyBtn.closest('.silk-pre');
    if (!pre) return;

    var code = pre.querySelector('code');
    if (!code) return;

    var text = code.innerText;

    // navigator.clipboard is undefined in insecure contexts (plain HTTP);
    // bail rather than throw an uncaught TypeError off the .writeText access.
    if (!navigator.clipboard) {
      console.error('Copy failed: clipboard API unavailable (requires a secure context)');
      return;
    }

    navigator.clipboard.writeText(text)
      .then(function () {
        copyBtn.classList.add('is-active');
        setTimeout(function () {
          copyBtn.classList.remove('is-active');
        }, 1000);
      })
      .catch(function (err) {
        console.error('Copy failed:', err);
      });
  });
});
