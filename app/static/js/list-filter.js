// Filtre en direct générique pour les pages listes rendues côté serveur
// (Produits, Stocks...) : bascule la classe "hidden" sur chaque ligne selon
// la recherche texte et les filtres dropdown choisis, sans rechargement de
// page ni requête serveur. Même logique simple que la recherche du PDV
// (pos.js : .toLowerCase().includes(), pas de debounce) appliquée ici à du
// HTML déjà rendu plutôt que reconstruit en JS.
function initListFilter({ searchInputId, rowSelector, filters = [], emptyMessageId }) {
  const searchInput = searchInputId ? document.getElementById(searchInputId) : null;
  const rows = Array.from(document.querySelectorAll(rowSelector));
  const emptyMessage = emptyMessageId ? document.getElementById(emptyMessageId) : null;

  function appliquerFiltres() {
    const terme = (searchInput?.value || "").toLowerCase().trim();
    let visibles = 0;

    rows.forEach((row) => {
      let visible = !terme || (row.dataset.name || "").toLowerCase().includes(terme);

      if (visible) {
        for (const f of filters) {
          const select = document.getElementById(f.selectId);
          if (!select || !select.value) continue;
          if ((row.dataset[f.dataAttr] || "") !== select.value) {
            visible = false;
            break;
          }
        }
      }

      row.classList.toggle("hidden", !visible);
      if (visible) visibles += 1;
    });

    if (emptyMessage) {
      emptyMessage.classList.toggle("hidden", visibles !== 0 || rows.length === 0);
    }
  }

  if (searchInput) searchInput.addEventListener("input", appliquerFiltres);
  filters.forEach((f) => {
    const select = document.getElementById(f.selectId);
    if (select) select.addEventListener("change", appliquerFiltres);
  });

  appliquerFiltres();
}
