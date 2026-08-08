(function () {
  // Déconnexion automatique après une période d'inactivité, sur un poste
  // partagé où plusieurs utilisateurs se connectent par code PIN (§1.5/§3 CDC).
  const timeoutMs = window.AKIBA_INACTIVITY_TIMEOUT_MS || 5 * 60 * 1000;
  const form = document.getElementById("auto-logout-form");
  if (!form) return;

  let timer;

  function seDeconnecter() {
    form.submit();
  }

  function reinitialiserMinuteur() {
    clearTimeout(timer);
    timer = setTimeout(seDeconnecter, timeoutMs);
  }

  ["click", "touchstart", "keydown", "mousemove", "scroll"].forEach((evenement) =>
    document.addEventListener(evenement, reinitialiserMinuteur, { passive: true })
  );

  reinitialiserMinuteur();
})();
