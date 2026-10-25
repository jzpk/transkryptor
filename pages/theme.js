// Motyw jasny/ciemny strony. Domyślnie taki jak w przeglądarce; wybór
// przyciskiem w pasku górnym zapamiętuje się w localStorage. Skrypt jest
// ładowany w <head> bez defer, żeby motyw był ustawiony przed pierwszym
// malowaniem (bez mignięcia jasnej strony w trybie ciemnym).
(function () {
  "use strict";

  var KEY = "transkryptor-motyw";
  var root = document.documentElement;
  var system = window.matchMedia("(prefers-color-scheme: dark)");

  function stored() {
    try {
      var value = localStorage.getItem(KEY);
      return value === "light" || value === "dark" ? value : null;
    } catch (error) {
      return null;
    }
  }

  function store(value) {
    try {
      if (value) {
        localStorage.setItem(KEY, value);
      } else {
        localStorage.removeItem(KEY);
      }
    } catch (error) {
      // Bez dostępu do pamięci wybór obowiązuje do zamknięcia strony.
    }
  }

  function systemTheme() {
    return system.matches ? "dark" : "light";
  }

  function label(theme) {
    return theme === "dark" ? "Włącz motyw jasny" : "Włącz motyw ciemny";
  }

  function apply(theme) {
    root.setAttribute("data-theme", theme);
    var buttons = document.querySelectorAll(".theme-toggle");
    for (var i = 0; i < buttons.length; i++) {
      buttons[i].title = label(theme);
      buttons[i].setAttribute("aria-label", label(theme));
    }
  }

  apply(stored() || systemTheme());

  // Bez zapamiętanego wyboru strona podąża za zmianą motywu w systemie.
  system.addEventListener("change", function () {
    if (!stored()) {
      apply(systemTheme());
    }
  });

  document.addEventListener("DOMContentLoaded", function () {
    var buttons = document.querySelectorAll(".theme-toggle");
    for (var i = 0; i < buttons.length; i++) {
      buttons[i].hidden = false;
      buttons[i].addEventListener("click", function () {
        var next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
        // Wybór zgodny z przeglądarką nie jest zapamiętywany — wtedy strona
        // znów podąża za ustawieniem systemu.
        store(next === systemTheme() ? null : next);
        apply(next);
      });
    }
    apply(root.getAttribute("data-theme"));
  });
})();
