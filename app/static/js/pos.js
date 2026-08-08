(function () {
  const posData = JSON.parse(document.getElementById("pos-data").textContent);
  const produits = posData.produits;
  const typeTarifs = posData.typeTarifs;
  const moyensPaiement = posData.moyensPaiement;
  const ariaryPourUnEuro = posData.ariaryPourUnEuro || 0;

  const posteButtons = Array.from(document.querySelectorAll(".poste-btn"));
  const posteParDefaut = posteButtons.length ? posteButtons[0].dataset.poste : null;

  // Le défilement tactile (doigt) fonctionne nativement grâce à
  // overflow-x/y-auto — ceci ajoute le glissement à la souris (retour
  // utilisateur du 07/08/2026 : "les catégories puissent se faire dérouler
  // ... en glissant avec le doigt ou la souris"), utile aussi hors de
  // l'écran tactile cible (dev, souris). Un simple clic (peu de mouvement)
  // continue de déclencher le bouton normalement — seul un vrai glissement
  // annule le clic qui suit, pour ne pas sélectionner la catégorie/poste
  // située sous le curseur au moment du relâchement.
  function activerDragDefilement(element, axe) {
    let enCours = false;
    let deplaceSignificatif = false;
    let depart = 0;
    let departScroll = 0;

    element.addEventListener("mousedown", (e) => {
      enCours = true;
      deplaceSignificatif = false;
      depart = axe === "y" ? e.pageY : e.pageX;
      departScroll = axe === "y" ? element.scrollTop : element.scrollLeft;
    });

    window.addEventListener("mousemove", (e) => {
      if (!enCours) return;
      const position = axe === "y" ? e.pageY : e.pageX;
      const delta = position - depart;
      if (Math.abs(delta) > 5) deplaceSignificatif = true;
      if (axe === "y") {
        element.scrollTop = departScroll - delta;
      } else {
        element.scrollLeft = departScroll - delta;
      }
    });

    window.addEventListener("mouseup", () => {
      enCours = false;
    });

    element.addEventListener(
      "click",
      (e) => {
        if (deplaceSignificatif) {
          e.stopPropagation();
          e.preventDefault();
        }
      },
      true
    );
  }

  const categoriesBar = document.getElementById("categories-bar");
  const postesRail = document.getElementById("postes-rail");
  if (categoriesBar) activerDragDefilement(categoriesBar, "x");
  if (postesRail) activerDragDefilement(postesRail, "y");

  const clients = posData.clients || [];

  function tarifParDefaut() {
    return (typeTarifs.find((t) => t.isDefault) || typeTarifs[0] || {}).code;
  }

  function nouveauTicket(nom) {
    return {
      id: null, // null tant qu'aucune ligne n'a jamais été sauvegardée côté serveur
      nom: nom,
      tarif: tarifParDefaut(),
      clientId: null,
      clientNom: null,
      cart: [], // { produitId, name, prixUnitaire, quantite, remise, offert }
    };
  }

  // Plusieurs tickets peuvent être ouverts en parallèle (plusieurs clients
  // commandent en même temps mais paient séparément) — chacun est sauvegardé
  // côté serveur (TicketAttente) à chaque modification, pour survivre à un
  // rafraîchissement, une déconnexion ou un redémarrage du poste. `categorie`
  // et `search` restent globaux : ce sont des filtres d'affichage du
  // catalogue, pas un état par ticket.
  const state = {
    poste: posteParDefaut,
    categorie: "all",
    search: "",
    tickets: [nouveauTicket("Ticket 1")],
    activeIndex: 0,
  };

  function activeTicket() {
    return state.tickets[state.activeIndex];
  }

  const productGrid = document.getElementById("product-grid");
  const noProducts = document.getElementById("no-products");
  const ticketTabs = document.getElementById("ticket-tabs");
  const ticketTitle = document.getElementById("ticket-title");
  const cartLines = document.getElementById("cart-lines");
  const cartEmpty = document.getElementById("cart-empty");
  const sousTotalEl = document.getElementById("sous-total");
  const totalEl = document.getElementById("total");
  const checkoutBtn = document.getElementById("checkout-btn");

  function formatMontant(n) {
    return n.toLocaleString("fr-FR");
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str == null ? "" : str;
    return div.innerHTML;
  }

  function prixPour(produit, tarifCode) {
    return produit.prix[tarifCode];
  }

  function tarifIdPour(code) {
    const found = typeTarifs.find((t) => t.code === code);
    return found ? found.id : null;
  }

  function tarifCodePourId(id) {
    const found = typeTarifs.find((t) => t.id === id);
    return found ? found.code : tarifParDefaut();
  }

  // --- Sauvegarde côté serveur des tickets en attente -------------------

  let saveTimer = null;

  function scheduleSaveTicket(ticket) {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => saveTicket(ticket), 500);
  }

  async function saveTicket(ticket) {
    // Un ticket jamais sauvegardé et toujours vide ne doit pas polluer la
    // liste après un rafraîchissement — on ne crée le brouillon serveur
    // qu'à la première ligne ajoutée (ou au premier renommage/client choisi).
    if (!ticket.id && ticket.cart.length === 0) return;

    const payload = {
      nom: ticket.nom,
      type_tarif_id: tarifIdPour(ticket.tarif),
      client_id: ticket.clientId,
      client_nom: ticket.clientNom,
      lignes: ticket.cart.map((line) => ({
        produit_id: line.produitId,
        quantite: line.quantite,
        remise: line.remise,
        offert: line.offert,
        // Uniquement pour un produit à prix libre (ex. Pourboire) : le
        // tarif ne permet pas de retrouver ce montant, il faut le
        // conserver tel quel dans le brouillon de ticket.
        prix_unitaire: line.prixLibre ? line.prixUnitaire : undefined,
      })),
    };

    const url = ticket.id ? `${posData.ticketsUrl}/${ticket.id}` : posData.ticketsUrl;
    try {
      const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRFToken": posData.csrfToken },
        body: JSON.stringify(payload),
      });
      const result = await response.json();
      if (result.ok && !ticket.id) {
        ticket.id = result.ticket.id;
      }
    } catch (err) {
      // Pas de blocage de la saisie si la sauvegarde réseau échoue
      // ponctuellement : on retentera à la prochaine modification.
      console.error("Échec de sauvegarde du ticket en attente", err);
    }
  }

  function construireLigneDepuisJson(ligneJson, tarifCode) {
    const produit = produits.find((p) => p.id === ligneJson.produit_id);
    if (!produit) return null;
    const prix = produit.prixLibre ? ligneJson.prix_unitaire : prixPour(produit, tarifCode);
    return {
      produitId: produit.id,
      name: produit.name,
      prixUnitaire: prix == null ? 0 : prix,
      quantite: ligneJson.quantite,
      remise: ligneJson.remise || 0,
      offert: !!ligneJson.offert,
      prixLibre: !!produit.prixLibre,
    };
  }

  async function chargerTicketsExistants() {
    try {
      const response = await fetch(posData.ticketsUrl);
      const result = await response.json();
      if (!result.ok || !result.tickets.length) return;

      state.tickets = result.tickets.map((t) => {
        const tarif = t.typeTarifId ? tarifCodePourId(t.typeTarifId) : tarifParDefaut();
        const cart = t.lignes
          .map((l) => construireLigneDepuisJson(l, tarif))
          .filter((l) => l !== null);
        return {
          id: t.id,
          nom: t.nom,
          tarif: tarif,
          clientId: t.clientId,
          clientNom: t.clientNom,
          cart: cart,
        };
      });
      state.activeIndex = 0;
    } catch (err) {
      console.error("Impossible de récupérer les tickets en attente", err);
    }
  }

  // --- Onglets de tickets --------------------------------------------------

  function renderTicketTabs() {
    ticketTabs.innerHTML = "";
    state.tickets.forEach((ticket, index) => {
      const active = index === state.activeIndex;
      const total = ticket.cart.reduce(
        (sum, l) => sum + (l.offert ? 0 : Math.max(0, l.prixUnitaire * l.quantite - l.remise)),
        0
      );

      const wrap = document.createElement("div");
      wrap.className =
        "flex items-center shrink-0 rounded-full mr-1 mb-2 " +
        (active ? "bg-primary-container" : "bg-surface-container hover:bg-surface-variant");
      wrap.innerHTML = `
        <button type="button" data-action="select" class="pl-4 pr-1 h-10 flex items-center gap-1.5 font-label-md text-label-md whitespace-nowrap ${active ? "text-on-primary-container font-bold" : "text-on-surface-variant"}">
          <span class="material-symbols-outlined text-[16px]">receipt_long</span>
          ${escapeHtml(ticket.nom)}
          ${ticket.cart.length ? `<span class="text-xs opacity-70">(${formatMontant(total)})</span>` : ""}
        </button>
        <button type="button" data-action="rename" class="w-8 h-10 flex items-center justify-center opacity-60 hover:opacity-100" title="Renommer le ticket">
          <span class="material-symbols-outlined text-[16px]">edit</span>
        </button>
        <button type="button" data-action="close" class="w-8 h-10 mr-1 flex items-center justify-center opacity-60 hover:opacity-100 hover:text-error" title="Fermer le ticket">
          <span class="material-symbols-outlined text-[16px]">close</span>
        </button>`;

      wrap.querySelector('[data-action="select"]').addEventListener("click", () => selectTicket(index));
      wrap.querySelector('[data-action="rename"]').addEventListener("click", () => renameTicket(index));
      wrap.querySelector('[data-action="close"]').addEventListener("click", () => closeTicket(index));
      ticketTabs.appendChild(wrap);
    });

    const addBtn = document.createElement("button");
    addBtn.type = "button";
    addBtn.title = "Nouveau ticket";
    addBtn.className =
      "shrink-0 w-10 h-10 mb-2 flex items-center justify-center rounded-full text-primary hover:bg-primary-container/40";
    addBtn.innerHTML = '<span class="material-symbols-outlined">add</span>';
    addBtn.addEventListener("click", addTicket);
    ticketTabs.appendChild(addBtn);
  }

  function selectTicket(index) {
    if (index === state.activeIndex) return;
    state.activeIndex = index;
    renderTicketTabs();
    renderTarifButtons();
    renderProducts();
    renderCart();
    renderClientLabel();
  }

  function addTicket() {
    const ticket = nouveauTicket(`Ticket ${state.tickets.length + 1}`);
    state.tickets.push(ticket);
    state.activeIndex = state.tickets.length - 1;
    renderTicketTabs();
    renderTarifButtons();
    renderProducts();
    renderCart();
    renderClientLabel();
  }

  function renameTicket(index) {
    const ticket = state.tickets[index];
    const nouveauNom = window.prompt("Nom du ticket", ticket.nom);
    if (nouveauNom === null) return;
    const nettoye = nouveauNom.trim().slice(0, 80);
    if (!nettoye) return;
    ticket.nom = nettoye;
    renderTicketTabs();
    if (index === state.activeIndex) ticketTitle.textContent = ticket.nom;
    scheduleSaveTicket(ticket);
  }

  function closeTicket(index) {
    const ticket = state.tickets[index];
    if (ticket.cart.length > 0) {
      const confirme = window.confirm(`Fermer « ${ticket.nom} » ? Son contenu sera définitivement supprimé.`);
      if (!confirme) return;
    }
    if (ticket.id) {
      fetch(`${posData.ticketsUrl}/${ticket.id}/supprimer`, {
        method: "POST",
        headers: { "X-CSRFToken": posData.csrfToken },
      }).catch((err) => console.error("Échec de suppression du ticket", err));
    }

    state.tickets.splice(index, 1);
    if (state.tickets.length === 0) {
      state.tickets.push(nouveauTicket("Ticket 1"));
    }
    if (state.activeIndex >= state.tickets.length) {
      state.activeIndex = state.tickets.length - 1;
    } else if (index < state.activeIndex) {
      state.activeIndex -= 1;
    }

    renderTicketTabs();
    renderTarifButtons();
    renderProducts();
    renderCart();
    renderClientLabel();
  }

  // --- Catalogue -------------------------------------------------------

  function renderTarifButtons() {
    const tarifActuel = activeTicket().tarif;
    document.querySelectorAll(".tarif-btn").forEach((btn) => {
      const active = btn.dataset.tarif === tarifActuel;
      btn.classList.toggle("bg-surface-container-lowest", active);
      btn.classList.toggle("shadow-sm", active);
      btn.classList.toggle("text-primary", active);
      btn.classList.toggle("font-bold", active);
      btn.classList.toggle("text-on-surface-variant", !active);
    });
  }

  function renderPosteButtons() {
    posteButtons.forEach((btn) => {
      const active = btn.dataset.poste === state.poste;
      btn.classList.toggle("bg-secondary-container", active);
      btn.classList.toggle("text-on-secondary-container", active);
      btn.classList.toggle("bg-surface-container", !active);
      btn.classList.toggle("text-on-surface-variant", !active);
    });
  }

  function renderCategoryButtons() {
    document.querySelectorAll(".categorie-btn").forEach((btn) => {
      // La catégorie "Tout" reste toujours visible ; les autres se filtrent
      // selon le poste sélectionné à gauche (§4.3, §6.3 spec).
      const visible = btn.dataset.categorie === "all" || btn.dataset.poste === state.poste;
      btn.classList.toggle("hidden", !visible);

      const active = btn.dataset.categorie === state.categorie;
      btn.classList.toggle("bg-secondary-container", active);
      btn.classList.toggle("text-on-secondary-container", active);
      btn.classList.toggle("bg-surface-container", !active);
      btn.classList.toggle("text-on-surface-variant", !active);
    });
  }

  function renderProducts() {
    const tarif = activeTicket().tarif;
    const term = state.search.trim().toLowerCase();
    const filtered = produits.filter((p) => {
      if (state.poste && String(p.posteId) !== state.poste) return false;
      if (state.categorie !== "all" && String(p.categorie_id) !== state.categorie) return false;
      if (term) {
        const correspondNom = p.name.toLowerCase().includes(term);
        const correspondCodeBarres = p.codeBarres && p.codeBarres.toLowerCase().includes(term);
        if (!correspondNom && !correspondCodeBarres) return false;
      }
      return true;
    });

    productGrid.innerHTML = "";
    noProducts.classList.toggle("hidden", filtered.length > 0);

    filtered.forEach((p) => {
      // Un produit à prix libre (ex. Pourboire) n'a pas de tarif fixe : il
      // reste toujours cliquable, le montant est demandé à l'ajout au panier.
      const prix = p.prixLibre ? null : prixPour(p, tarif);
      const indisponible = !p.prixLibre && prix == null;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className =
        "flex flex-col bg-surface rounded-2xl overflow-hidden border border-surface-container-highest touch-active transition-all hover:-translate-y-1 text-left" +
        (indisponible ? " opacity-40 cursor-not-allowed" : "");
      btn.disabled = indisponible;

      const stockLabel =
        p.statut_stock === "illimite"
          ? `<span class="material-symbols-outlined text-[14px]">all_inclusive</span> Illimité`
          : p.statut_stock === "rupture"
          ? `<span class="w-2 h-2 rounded-full bg-error"></span> Rupture`
          : p.statut_stock === "faible"
          ? `<span class="w-2 h-2 rounded-full bg-error"></span> Stock faible (${p.stock_quantite})`
          : `<span class="w-2 h-2 rounded-full bg-secondary"></span> En stock (${p.stock_quantite})`;

      const imageContent = p.photoUrl
        ? `<img src="${p.photoUrl}" alt="" class="w-full h-full object-cover">`
        : `<span class="material-symbols-outlined text-3xl">inventory_2</span>`;

      const prixLabel = p.prixLibre ? "Prix libre" : prix == null ? "—" : formatMontant(prix);

      btn.innerHTML = `
        <div class="h-24 w-full bg-surface-container-low flex items-center justify-center text-outline-variant relative overflow-hidden">
          ${imageContent}
          <div class="absolute top-2 right-2 bg-surface/90 px-2 py-1 rounded-lg font-label-md text-xs text-on-surface font-bold">${prixLabel}</div>
        </div>
        <div class="p-3 flex flex-col items-start flex-1 w-full">
          <span class="font-label-md text-label-md text-on-surface line-clamp-2 mb-1">${p.name}</span>
          <span class="font-body-md text-xs text-on-surface-variant mt-auto flex items-center gap-1">${stockLabel}</span>
        </div>`;

      if (!indisponible) {
        btn.addEventListener("click", () => addToCart(p));
      }
      productGrid.appendChild(btn);
    });
  }

  function addToCart(produit) {
    const ticket = activeTicket();

    if (produit.prixLibre) {
      const saisie = window.prompt(`Montant pour « ${produit.name} » (Ar)`, "");
      if (saisie === null) return;
      const montant = parseInt(saisie, 10);
      if (!montant || montant <= 0) return;

      const existing = ticket.cart.find(
        (l) => l.produitId === produit.id && !l.offert && l.prixUnitaire === montant
      );
      if (existing) {
        existing.quantite += 1;
      } else {
        ticket.cart.push({
          produitId: produit.id,
          name: produit.name,
          prixUnitaire: montant,
          quantite: 1,
          remise: 0,
          offert: false,
          prixLibre: true,
        });
      }
      renderCart();
      return;
    }

    const existing = ticket.cart.find((l) => l.produitId === produit.id && !l.offert);
    if (existing) {
      existing.quantite += 1;
    } else {
      ticket.cart.push({
        produitId: produit.id,
        name: produit.name,
        prixUnitaire: prixPour(produit, ticket.tarif),
        quantite: 1,
        remise: 0,
        offert: false,
        prixLibre: false,
      });
    }
    renderCart();
  }

  function renderCart() {
    const ticket = activeTicket();
    ticketTitle.textContent = ticket.nom;
    cartLines.innerHTML = "";
    cartEmpty.classList.toggle("hidden", ticket.cart.length > 0);

    let sousTotal = 0;
    ticket.cart.forEach((line, index) => {
      const ligneTotal = line.offert ? 0 : Math.max(0, line.prixUnitaire * line.quantite - line.remise);
      sousTotal += ligneTotal;

      const li = document.createElement("li");
      li.className = "bg-surface-container-lowest border border-outline-variant/30 rounded-xl p-3";
      li.innerHTML = `
        <div class="flex justify-between items-start mb-2 gap-2">
          <span class="font-label-md text-label-md text-on-surface leading-tight">${line.name}${line.offert ? " (offert)" : ""}</span>
          <span class="font-label-md text-label-md font-bold text-on-surface whitespace-nowrap">${formatMontant(ligneTotal)}</span>
        </div>
        <div class="flex items-center justify-between mb-2">
          <span class="font-body-md text-xs text-on-surface-variant">${formatMontant(line.prixUnitaire)} / u</span>
        </div>
        <div class="flex items-center justify-between gap-2">
          <div class="flex items-center bg-surface-container rounded-full border border-outline-variant/20">
            <button data-action="dec" class="w-touch-target-min h-touch-target-min flex items-center justify-center rounded-l-full text-on-surface-variant active:bg-outline-variant/30">
              <span class="material-symbols-outlined">remove</span>
            </button>
            <span class="w-10 text-center font-label-md text-body-md">${line.quantite}</span>
            <button data-action="inc" class="w-touch-target-min h-touch-target-min flex items-center justify-center rounded-r-full text-on-surface-variant active:bg-outline-variant/30">
              <span class="material-symbols-outlined">add</span>
            </button>
          </div>
          <div class="flex items-center gap-2">
            <button data-action="offrir" class="w-touch-target-min h-touch-target-min flex items-center justify-center rounded-full text-on-surface-variant active:bg-surface-variant" title="Offrir">
              <span class="material-symbols-outlined text-[20px]">redeem</span>
            </button>
            <button data-action="remove" class="w-touch-target-min h-touch-target-min flex items-center justify-center rounded-full text-error active:bg-error-container" title="Supprimer">
              <span class="material-symbols-outlined text-[20px]">close</span>
            </button>
          </div>
        </div>`;

      li.querySelector('[data-action="inc"]').addEventListener("click", () => {
        line.quantite += 1;
        renderCart();
      });
      li.querySelector('[data-action="dec"]').addEventListener("click", () => {
        line.quantite -= 1;
        if (line.quantite <= 0) ticket.cart.splice(index, 1);
        renderCart();
      });
      li.querySelector('[data-action="offrir"]').addEventListener("click", () => {
        line.offert = !line.offert;
        renderCart();
      });
      li.querySelector('[data-action="remove"]').addEventListener("click", () => {
        ticket.cart.splice(index, 1);
        renderCart();
      });

      cartLines.appendChild(li);
    });

    sousTotalEl.textContent = formatMontant(sousTotal);
    totalEl.textContent = formatMontant(sousTotal);
    checkoutBtn.disabled = ticket.cart.length === 0;

    renderTicketTabs();
    scheduleSaveTicket(ticket);
  }

  // Change de tarif avec des articles déjà dans le panier : recalcule le prix
  // de chaque ligne sur le nouveau tarif au lieu de garder le prix figé au
  // moment de l'ajout — sinon un changement de tarif en cours de vente (ex.
  // client qui se révèle adhérent) n'avait aucun effet sur ce qui était déjà
  // au panier. Un article dont le nouveau tarif ne propose pas de prix est
  // retiré du panier et signalé, plutôt que de rester à un prix obsolète.
  function recalculerPrixPanier() {
    const ticket = activeTicket();
    const indisponibles = [];
    ticket.cart = ticket.cart.filter((line) => {
      if (line.prixLibre) return true; // prix figé manuellement, pas de tarif à recalculer
      const produit = produits.find((p) => p.id === line.produitId);
      const nouveauPrix = produit ? produit.prix[ticket.tarif] : null;
      if (nouveauPrix == null) {
        indisponibles.push(line.name);
        return false;
      }
      line.prixUnitaire = nouveauPrix;
      return true;
    });
    if (indisponibles.length) {
      alert(
        `Retiré du panier (indisponible à ce tarif) : ${indisponibles.join(", ")}`
      );
    }
  }

  function changerTarif(code) {
    const ticket = activeTicket();
    if (ticket.tarif === code) return;
    ticket.tarif = code;
    recalculerPrixPanier();
    renderTarifButtons();
    renderProducts();
    renderCart();
  }

  document.querySelectorAll(".tarif-btn").forEach((btn) => {
    btn.addEventListener("click", () => changerTarif(btn.dataset.tarif));
  });

  posteButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.dataset.poste === state.poste) return;
      state.poste = btn.dataset.poste;
      state.categorie = "all"; // la catégorie précédente peut ne plus exister pour ce poste
      renderPosteButtons();
      renderCategoryButtons();
      renderProducts();
    });
  });

  document.querySelectorAll(".categorie-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.categorie = btn.dataset.categorie;
      renderCategoryButtons();
      renderProducts();
    });
  });

  const searchInput = document.getElementById("search-input");

  searchInput.addEventListener("input", (e) => {
    state.search = e.target.value;
    renderProducts();
  });

  // Lecteur de code-barres USB : il tape le code puis "Entrée" très
  // rapidement, comme un clavier. Sur une correspondance exacte, on ajoute
  // directement le produit au ticket et on vide la recherche — pas besoin
  // de parcourir la grille visuellement pour un scan.
  searchInput.addEventListener("keydown", (e) => {
    if (e.key !== "Enter") return;
    const code = searchInput.value.trim().toLowerCase();
    if (!code) return;
    const produit = produits.find((p) => p.codeBarres && p.codeBarres.toLowerCase() === code);
    if (produit && prixPour(produit, activeTicket().tarif) != null) {
      addToCart(produit);
      searchInput.value = "";
      state.search = "";
      renderProducts();
    }
  });

  document.getElementById("clear-cart").addEventListener("click", () => {
    activeTicket().cart = [];
    renderCart();
  });

  // --- Checkout modal ---
  const modal = document.getElementById("checkout-modal");
  const paiementRows = document.getElementById("paiement-rows");
  const modalTotal = document.getElementById("modal-total");
  const modalReste = document.getElementById("modal-reste");
  const modalError = document.getElementById("modal-error");

  function currentTotal() {
    return activeTicket().cart.reduce((sum, line) => {
      return sum + (line.offert ? 0 : Math.max(0, line.prixUnitaire * line.quantite - line.remise));
    }, 0);
  }

  // Le montant d'une ligne de paiement est toujours saisi (et envoyé au
  // serveur) dans la devise du moyen choisi pour CETTE ligne — jamais en
  // ariary "caché" derrière une devise différente. Corrige un bug où régler
  // un ticket de 14 000 Ar avec ~3 € créditait le compte Euro de
  // "14 000 €" au lieu de ~3 € : le champ représentait en réalité toujours
  // des ariary, quelle que soit la devise affichée à côté.
  function montantEnAriary(montant, devise) {
    if (devise === "€") return montant * ariaryPourUnEuro;
    return montant;
  }

  function ariaryVersDevise(montantAriary, devise) {
    // Arrondi au SUPÉRIEUR (jamais au plus proche) : un ticket de 16,05 €
    // devient 17 € à payer, jamais 16 € — la conversion ne doit jamais faire
    // perdre d'argent à Akiba, quitte à arrondir en faveur de la caisse
    // plutôt que du client (choix explicite de l'utilisateur).
    if (devise === "€" && ariaryPourUnEuro > 0) return Math.ceil(montantAriary / ariaryPourUnEuro);
    return Math.round(montantAriary);
  }

  function addPaiementRow(montantAriary) {
    const row = document.createElement("div");
    row.className = "flex flex-col gap-1";
    const options = moyensPaiement
      .map((m) => `<option value="${m.id}" data-devise="${m.devise}">${m.name}</option>`)
      .join("");
    row.innerHTML = `
      <div class="flex gap-2">
        <select class="paiement-moyen flex-1 h-12 px-3 bg-surface-container-low border border-outline-variant rounded-xl font-body-md text-body-md">${options}</select>
        <div class="relative w-32">
          <input type="number" step="1" class="paiement-montant w-full h-12 pl-3 pr-10 bg-surface-container-low border border-outline-variant rounded-xl font-body-md text-body-md" value="${montantAriary}">
          <span class="paiement-devise absolute right-3 top-1/2 -translate-y-1/2 font-body-md text-xs text-on-surface-variant pointer-events-none"></span>
        </div>
        <button type="button" class="remove-paiement w-12 h-12 flex items-center justify-center text-error"><span class="material-symbols-outlined">close</span></button>
      </div>
      <p class="hidden paiement-conversion-hint font-body-md text-xs text-on-surface-variant pl-1"></p>`;

    const select = row.querySelector(".paiement-moyen");
    const montantInput = row.querySelector(".paiement-montant");
    const deviseLabel = row.querySelector(".paiement-devise");
    const hint = row.querySelector(".paiement-conversion-hint");

    function deviseActuelle() {
      return select.options[select.selectedIndex]?.dataset.devise || "Ar";
    }

    let deviseCourante = deviseActuelle();

    function updateHint() {
      const devise = deviseActuelle();
      deviseLabel.textContent = devise;
      const montant = parseFloat(montantInput.value) || 0;
      if (devise !== "Ar" && montant > 0 && ariaryPourUnEuro > 0) {
        const ariary = montantEnAriary(montant, devise);
        hint.textContent = `≈ ${formatMontant(ariary)} Ar (1 ${devise} = ${formatMontant(ariaryPourUnEuro)} Ar)`;
        hint.classList.remove("hidden");
      } else {
        hint.classList.add("hidden");
      }
    }

    select.addEventListener("change", () => {
      // Changer de moyen change la devise attendue dans le champ : on
      // convertit la valeur déjà saisie plutôt que de la laisser telle
      // quelle dans l'ancienne devise sans que le vendeur s'en rende compte.
      const nouvelleDevise = deviseActuelle();
      if (nouvelleDevise !== deviseCourante) {
        const montantActuel = parseFloat(montantInput.value) || 0;
        const equivalentAriary = montantEnAriary(montantActuel, deviseCourante);
        montantInput.value = ariaryVersDevise(equivalentAriary, nouvelleDevise);
        deviseCourante = nouvelleDevise;
      }
      updateReste();
      updateHint();
    });
    montantInput.addEventListener("input", () => {
      updateReste();
      updateHint();
    });
    row.querySelector(".remove-paiement").addEventListener("click", () => {
      row.remove();
      updateReste();
    });
    paiementRows.appendChild(row);
    updateReste();
    updateHint();
  }

  function updateReste() {
    const total = currentTotal();
    const paye = Array.from(paiementRows.children).reduce((sum, row) => {
      const select = row.querySelector(".paiement-moyen");
      const input = row.querySelector(".paiement-montant");
      const devise = select.options[select.selectedIndex]?.dataset.devise || "Ar";
      const montant = parseFloat(input.value) || 0;
      return sum + montantEnAriary(montant, devise);
    }, 0);
    modalReste.textContent = formatMontant(total - paye);
  }

  // Monnaie à rendre : simple aide au calcul mental pour le vendeur (ex. le
  // client donne un billet de 20 000 sur un ticket à 16 000) — n'affecte pas
  // les moyens de paiement envoyés au serveur, qui restent limités au total
  // réellement dû sur le ticket.
  const montantRecu = document.getElementById("montant-recu");
  const modalRendu = document.getElementById("modal-rendu");
  const modalRenduRow = document.getElementById("modal-rendu-row");

  function updateRendu() {
    const recu = parseInt(montantRecu.value, 10) || 0;
    const rendu = recu - currentTotal();
    modalRenduRow.classList.toggle("hidden", recu <= 0 || rendu <= 0);
    if (rendu > 0) modalRendu.textContent = formatMontant(rendu);
  }
  montantRecu.addEventListener("input", updateRendu);

  checkoutBtn.addEventListener("click", () => {
    const total = currentTotal();
    modalTotal.textContent = formatMontant(total);
    paiementRows.innerHTML = "";
    modalError.classList.add("hidden");
    addPaiementRow(total);
    creditRow.classList.toggle("hidden", !activeTicket().clientId);
    creditCheckbox.checked = false;
    montantRecu.value = "";
    modalRenduRow.classList.add("hidden");
    modal.classList.remove("hidden");
  });

  document.getElementById("add-paiement").addEventListener("click", () => addPaiementRow(0));
  document.getElementById("modal-cancel").addEventListener("click", () => modal.classList.add("hidden"));

  document.getElementById("modal-confirm").addEventListener("click", async () => {
    const ticket = activeTicket();
    const paiements = Array.from(paiementRows.children).map((row) => ({
      moyen_paiement_id: parseInt(row.querySelector(".paiement-moyen").value, 10),
      montant: parseInt(row.querySelector(".paiement-montant").value, 10) || 0,
    }));

    const payload = {
      type_tarif_id: tarifIdPour(ticket.tarif),
      client_id: ticket.clientId,
      lignes: ticket.cart.map((line) => ({
        produit_id: line.produitId,
        quantite: line.quantite,
        remise: line.remise,
        offert: line.offert,
        prix_unitaire: line.prixLibre ? line.prixUnitaire : undefined,
      })),
      paiements: paiements,
      a_credit: !creditRow.classList.contains("hidden") && creditCheckbox.checked,
      ticket_attente_id: ticket.id,
    };

    const response = await fetch(posData.checkoutUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": posData.csrfToken,
      },
      body: JSON.stringify(payload),
    });

    const result = await response.json();
    if (result.ok) {
      window.location.href = result.redirect;
    } else {
      modalError.textContent = result.error || "Erreur lors de l'enregistrement.";
      modalError.classList.remove("hidden");
    }
  });

  // --- Sélection client (vente à crédit) ---
  const clientModal = document.getElementById("client-modal");
  const clientSelectBtn = document.getElementById("client-select-btn");
  const clientSelectLabel = document.getElementById("client-select-label");
  const clientSearch = document.getElementById("client-search");
  const clientList = document.getElementById("client-list");
  const creditRow = document.getElementById("credit-row");
  const creditCheckbox = document.getElementById("credit-checkbox");

  function renderClientLabel() {
    clientSelectLabel.textContent = activeTicket().clientNom || "Client de passage";
  }

  // Cocher "vente à crédit" remet les montants payés à 0 par défaut (tout à
  // crédit) : sans ça, le champ de paiement pré-rempli avec le total laissait
  // la vente enregistrée comme intégralement payée malgré la case cochée, et
  // aucun solde dû n'apparaissait ensuite sur la fiche client. Le vendeur peut
  // resaisir un acompte si le client paie une partie maintenant.
  creditCheckbox.addEventListener("change", () => {
    const inputs = Array.from(document.querySelectorAll(".paiement-montant"));
    if (creditCheckbox.checked) {
      inputs.forEach((input) => { input.value = 0; });
    } else if (inputs.length) {
      inputs[0].value = currentTotal();
      for (let i = 1; i < inputs.length; i++) inputs[i].value = 0;
    }
    updateReste();
  });

  function renderClientList() {
    const term = clientSearch.value.trim().toLowerCase();
    const filtres = clients.filter((c) => c.nom.toLowerCase().includes(term));
    clientList.innerHTML = "";
    filtres.forEach((c) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "w-full text-left h-touch-target-min px-3 rounded-xl hover:bg-surface-container-low font-body-md text-body-md text-on-surface";
      btn.textContent = c.nom;
      btn.addEventListener("click", () => {
        const ticket = activeTicket();
        ticket.clientId = c.id;
        ticket.clientNom = c.nom;
        renderClientLabel();
        clientModal.classList.add("hidden");
        scheduleSaveTicket(ticket);

        // Le type de client (adhérent, grossiste...) correspond souvent
        // directement au code d'un tarif du même nom : on bascule dessus
        // automatiquement s'il existe et est actif, sans forcer de choix
        // arbitraire sinon (le vendeur garde la main dans ce cas).
        if (c.typeClient && typeTarifs.some((t) => t.code === c.typeClient)) {
          changerTarif(c.typeClient);
        }
      });
      clientList.appendChild(btn);
    });
    if (filtres.length === 0) {
      clientList.innerHTML = '<p class="p-3 font-body-md text-sm text-on-surface-variant">Aucun client trouvé.</p>';
    }
  }

  if (clientSelectBtn) {
    clientSelectBtn.addEventListener("click", () => {
      clientSearch.value = "";
      renderClientList();
      clientModal.classList.remove("hidden");
    });
    document.getElementById("client-passage-btn").addEventListener("click", () => {
      const ticket = activeTicket();
      ticket.clientId = null;
      ticket.clientNom = null;
      renderClientLabel();
      clientModal.classList.add("hidden");
      scheduleSaveTicket(ticket);
    });
    document.getElementById("client-modal-cancel").addEventListener("click", () => {
      clientModal.classList.add("hidden");
    });
    clientSearch.addEventListener("input", renderClientList);
  }

  // --- Dernières ventes (anti double-saisie) ---
  const recentSalesBtn = document.getElementById("recent-sales-btn");
  const recentSalesPanel = document.getElementById("recent-sales-panel");
  if (recentSalesBtn && recentSalesPanel) {
    recentSalesBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      recentSalesPanel.classList.toggle("hidden");
    });
    document.addEventListener("click", (e) => {
      if (!recentSalesPanel.contains(e.target) && e.target !== recentSalesBtn) {
        recentSalesPanel.classList.add("hidden");
      }
    });
  }

  async function demarrer() {
    await chargerTicketsExistants();
    renderTicketTabs();
    renderTarifButtons();
    renderPosteButtons();
    renderCategoryButtons();
    renderProducts();
    renderCart();
    renderClientLabel();
  }

  demarrer();
})();
