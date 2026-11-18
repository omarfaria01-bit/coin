(() => {
  "use strict";
  const header = document.querySelector(".nav");
  const btn = document.querySelector(".nav-toggle");
  const menu = document.getElementById("site-nav");
  if (btn && header && menu) {
    btn.addEventListener("click", () => {
      const open = header.classList.toggle("open");
      btn.setAttribute("aria-expanded", open ? "true" : "false");
    });
    menu.querySelectorAll("a").forEach((link) => {
      link.addEventListener("click", () => {
        header.classList.remove("open");
        btn.setAttribute("aria-expanded", "false");
      });
    });
  }
  let file = (location.pathname.split("/").pop() || "index.html").toLowerCase();
  if (!file || file === "/") file = "index.html";
  document.querySelectorAll("#site-nav a").forEach((link) => {
    const href = (link.getAttribute("href") || "").toLowerCase();
    if (href === file) link.classList.add("active");
    if (link.classList.contains("active")) link.setAttribute("aria-current", "page");
  });
})();
