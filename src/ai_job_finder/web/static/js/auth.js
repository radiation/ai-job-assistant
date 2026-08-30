(() => {
  const panel = document.querySelector(".sign-in-panel");
  const button = document.querySelector("#google-sign-in");
  const error = document.querySelector("#sign-in-error");
  if (!panel || !button || !window.firebase) return;

  const config = {
    apiKey: panel.dataset.firebaseApiKey,
    authDomain: panel.dataset.firebaseAuthDomain,
    appId: panel.dataset.firebaseAppId,
    projectId: panel.dataset.firebaseProjectId,
  };
  if (!config.apiKey || !config.authDomain || !config.appId || !config.projectId) {
    error.textContent = "Sign-in is not configured.";
    error.hidden = false;
    button.disabled = true;
    return;
  }

  firebase.initializeApp(config);
  const firebaseAuth = firebase.auth();
  if (panel.dataset.firebaseTenantId) firebaseAuth.tenantId = panel.dataset.firebaseTenantId;

  button.addEventListener("click", async () => {
    error.hidden = true;
    button.disabled = true;
    try {
      await firebaseAuth.setPersistence(firebase.auth.Auth.Persistence.NONE);
      const result = await firebaseAuth.signInWithPopup(new firebase.auth.GoogleAuthProvider());
      const idToken = await result.user.getIdToken();
      const response = await fetch("/api/v1/auth/session", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": window.aiJobFinderCsrfToken() },
        body: JSON.stringify({ id_token: idToken }),
      });
      if (!response.ok) throw new Error("Unable to establish a session.");
      await firebaseAuth.signOut();
      window.location.assign("/jobs");
    } catch (exception) {
      error.textContent = exception instanceof Error ? exception.message : "Unable to sign in.";
      error.hidden = false;
      button.disabled = false;
    }
  });
})();
