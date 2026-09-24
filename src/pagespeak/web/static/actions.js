// Run-form behaviour for the actions partial; external so a swapped fragment
// never needs an inline script (and so never needs the page's CSP nonce).
(function () {
  var form = document.getElementById('run-form');
  if (!form) return;
  var startEl = document.getElementById('sel-start');
  var stopEl = document.getElementById('sel-stop');
  var runBtn = document.getElementById('run-btn');
  var note = document.getElementById('no-options-note');
  var dir = form.dataset.dir;
  var phaseBtns = form.querySelectorAll('.phase-btn');
  var optGroups = form.querySelectorAll('[data-phases]');
  var selCls = 'phase-btn px-2.5 py-1 rounded text-xs bg-blue-600 text-white';
  var idleCls = 'phase-btn px-2.5 py-1 rounded text-xs bg-slate-100 text-slate-600 hover:bg-slate-200';

  function select(phase) {
    startEl.value = (phase === 'full') ? '' : phase;
    stopEl.value = (phase === 'full') ? '' : phase;
    phaseBtns.forEach(function (b) { b.className = (b.dataset.phase === phase) ? selCls : idleCls; });
    var anyVisible = false;
    optGroups.forEach(function (g) {
      var rel = g.dataset.phases.split(' ').indexOf(phase) >= 0;
      g.classList.toggle('hidden', !rel);
      if (rel) anyVisible = true;
    });
    note.classList.toggle('hidden', anyVisible);
    runBtn.textContent = (phase === 'full') ? '▶ Run full conversion' : ('▶ Run ' + phase);
    form.setAttribute('hx-confirm', phase === 'full'
      ? 'Run the full conversion on ' + dir + '?'
      : "Run the '" + phase + "' step on " + dir + '?');
  }

  phaseBtns.forEach(function (b) { b.addEventListener('click', function () { select(b.dataset.phase); }); });
  select('full');

  // --- Option dependencies (prevent invalid / meaningless combinations) ---

  // Vision is a 3-way choice mapped to the diagrams + cache-only flags. This
  // makes the invalid "skip images + reuse-cached-only" pair impossible.
  var visionMode = document.getElementById('vision-mode');
  var optDiagrams = document.getElementById('opt-diagrams');
  var optCacheOnly = document.getElementById('opt-cacheonly');
  if (visionMode && optDiagrams && optCacheOnly) {
    var syncVision = function () {
      optDiagrams.value = (visionMode.value === 'skip') ? '' : 'true';
      optCacheOnly.value = (visionMode.value === 'cached') ? 'true' : '';
    };
    visionMode.addEventListener('change', syncVision);
    syncVision();
  }

  // "group in folders" only does anything with "save each section separately".
  var optSplit = document.getElementById('opt-split');
  var optNested = document.getElementById('opt-nested');
  if (optSplit && optNested) {
    var syncSplit = function () {
      optNested.disabled = !optSplit.checked;
      if (!optSplit.checked) optNested.checked = false;
      var grp = optNested.closest('[data-phases]');
      if (grp) grp.classList.toggle('opacity-40', !optSplit.checked);
    };
    optSplit.addEventListener('change', syncSplit);
    syncSplit();
  }

  // The heading-rebuild mode only matters when "rebuild heading structure" is on.
  var optNorm = document.getElementById('opt-norm');
  var optNormMode = document.getElementById('opt-norm-mode');
  if (optNorm && optNormMode) {
    var syncNorm = function () {
      optNormMode.disabled = !optNorm.checked;
      var grp = optNormMode.closest('[data-phases]');
      if (grp) grp.classList.toggle('opacity-40', !optNorm.checked);
    };
    optNorm.addEventListener('change', syncNorm);
    syncNorm();
  }
})();

