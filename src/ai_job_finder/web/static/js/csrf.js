(() => {
  const cookieValue = (name) => document.cookie.split("; ").find((cookie) => cookie.startsWith(`${name}=`))?.split("=").slice(1).join("=") || "";
  const csrfCookieName = document.documentElement.dataset.csrfCookieName || "ai_job_finder_csrf";
  const csrfToken = () => cookieValue(csrfCookieName);

  const addFormToken = (form) => {
    if (form.method.toUpperCase() === "GET" || form.querySelector("input[name=csrf_token]")) return;
    const input = document.createElement("input");
    input.type = "hidden";
    input.name = "csrf_token";
    input.value = csrfToken();
    form.append(input);
  };

  document.addEventListener("DOMContentLoaded", () => document.querySelectorAll("form").forEach(addFormToken));
  document.addEventListener("submit", (event) => {
    if (event.target instanceof HTMLFormElement) addFormToken(event.target);
  }, true);
  document.body?.addEventListener("htmx:configRequest", (event) => {
    if (["POST", "PUT", "PATCH", "DELETE"].includes(event.detail.verb.toUpperCase())) {
      event.detail.headers["X-CSRF-Token"] = csrfToken();
    }
  });
  window.aiJobFinderCsrfToken = csrfToken;
})();
