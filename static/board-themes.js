/* ============================================================
   ChessMate &mdash; board theme picker.
   Sets the data-board attribute on <body>; CSS handles the rest.
   Persists choice in localStorage so it survives page navigation.
   ============================================================ */
(function () {
  const KEY = 'chessmate_board_theme';

  const THEMES = [
    { id: 'classic',    label: 'Classic Wood' },
    { id: 'walnut',     label: 'Walnut' },
    { id: 'autumn',     label: 'Autumn' },
    { id: 'olive',      label: 'Olive Club' },
    { id: 'parchment',  label: 'Parchment' },
    { id: 'tournament', label: 'Tournament Green' },
  ];
  const DEFAULT = 'classic';

  function apply(themeId) {
    const valid = THEMES.some((t) => t.id === themeId) ? themeId : DEFAULT;
    document.body.setAttribute('data-board', valid);
    try { localStorage.setItem(KEY, valid); } catch (_) {}
    return valid;
  }

  function get() {
    try { return localStorage.getItem(KEY) || DEFAULT; } catch (_) { return DEFAULT; }
  }

  function mount(selectEl) {
    if (!selectEl) return;
    if (selectEl.dataset.chessmateThemeBound) return;
    selectEl.dataset.chessmateThemeBound = '1';

    selectEl.innerHTML = '';
    for (const t of THEMES) {
      const opt = document.createElement('option');
      opt.value = t.id;
      opt.innerHTML = t.label;
      selectEl.appendChild(opt);
    }
    selectEl.value = get();
    selectEl.addEventListener('change', () => {
      apply(selectEl.value);
    });
  }

  // Apply stored theme immediately so the board never flashes the wrong palette.
  apply(get());

  // Mount any picker(s) already in the DOM and any added later.
  function mountAll() {
    document.querySelectorAll('#board-theme-picker').forEach(mount);
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mountAll);
  } else {
    mountAll();
  }

  // Public API.
  window.BoardThemes = { THEMES, apply, get, mount };
})();
