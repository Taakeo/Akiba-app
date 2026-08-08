/**
 * Filtre dynamiquement un <select> enfant selon la valeur d'un <select>
 * parent — utilisé pour Poste → Catégorie et pour Catégorie → Sous-catégorie
 * (les deux cascades peuvent être chaînées sur la même page : le <select>
 * enfant d'une cascade est alors le parent de la suivante).
 *
 * @param {string} categorieSelectId - id du <select> parent (ex. Poste, Catégorie)
 * @param {string} sousCategorieSelectId - id du <select> enfant à filtrer (ex. Catégorie, Sous-catégorie)
 * @param {string} mappingScriptId - id du <script type="application/json"> contenant
 *   { "<parent_id>": [{"id": ..., "name": ...}, ...], ... }
 * @param {string|number|null} valeurInitiale - valeur à présélectionner dans le <select> enfant (édition)
 */
function initCascadeSousCategorie(categorieSelectId, sousCategorieSelectId, mappingScriptId, valeurInitiale) {
  const categorieSelect = document.getElementById(categorieSelectId);
  const sousSelect = document.getElementById(sousCategorieSelectId);
  const mappingEl = document.getElementById(mappingScriptId);
  if (!categorieSelect || !sousSelect || !mappingEl) return;

  const mapping = JSON.parse(mappingEl.textContent);
  let premierRendu = true;

  function render() {
    const options = mapping[categorieSelect.value] || [];
    const valeurAConserver = premierRendu ? String(valeurInitiale || "0") : "0";

    sousSelect.innerHTML = "";
    const optionVide = document.createElement("option");
    optionVide.value = "0";
    optionVide.textContent = "—";
    sousSelect.appendChild(optionVide);

    options.forEach((sc) => {
      const opt = document.createElement("option");
      opt.value = sc.id;
      opt.textContent = sc.name;
      sousSelect.appendChild(opt);
    });

    if (options.some((sc) => String(sc.id) === valeurAConserver)) {
      sousSelect.value = valeurAConserver;
    }
    premierRendu = false;

    // Répercute le changement sur une éventuelle cascade chaînée en aval
    // (ex. Poste → Catégorie → Sous-catégorie) : sans ceci, changer le Poste
    // ne rafraîchirait pas la liste des Sous-catégories qui dépend, elle, de
    // la Catégorie que ce rendu vient de modifier.
    sousSelect.dispatchEvent(new Event("change"));
  }

  categorieSelect.addEventListener("change", render);
  render();
}
