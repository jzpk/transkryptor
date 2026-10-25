// Skrypt strony projektu. Ładowany w <head> bez defer, żeby motyw i stan
// animacji były ustawione przed pierwszym malowaniem (bez mignięcia jasnej
// strony w trybie ciemnym i bez ruchu liter, które zaraz się zatrzymają).
//
// - Motyw jasny/ciemny: domyślnie taki jak w przeglądarce, przycisk
//   .theme-toggle zapamiętuje wybór. Ustawia data-theme na <html>.
// - Animacja liter w tle: przełącznik .motion-switch; domyślnie włączona,
//   chyba że system prosi o ograniczenie ruchu. Ustawia data-animation.
// - Karty <details>: adres z #kotwicą rozwija wskazaną kartę, a przycisk
//   [data-toggle-all] rozwija albo zwija wszystkie karty w swojej sekcji.
(function () {
  "use strict";

  var root = document.documentElement;

  function load(key, allowed) {
    try {
      var value = localStorage.getItem(key);
      return allowed.indexOf(value) >= 0 ? value : null;
    } catch (error) {
      return null;
    }
  }

  function save(key, value) {
    try {
      if (value) {
        localStorage.setItem(key, value);
      } else {
        localStorage.removeItem(key);
      }
    } catch (error) {
      // Bez dostępu do pamięci wybór obowiązuje do zamknięcia strony.
    }
  }

  function each(selector, callback) {
    var nodes = document.querySelectorAll(selector);
    for (var i = 0; i < nodes.length; i++) {
      callback(nodes[i]);
    }
  }

  // Preferencja wyświetlania z domyślną wartością według przeglądarki.
  // Wybór zgodny z domyślną nie jest zapamiętywany — wtedy strona znów
  // podąża za ustawieniem systemu.
  function preference(key, attribute, values, query, onSystem, render) {
    var system = window.matchMedia(query);
    var otherwise = values[0] === onSystem ? values[1] : values[0];

    function systemValue() {
      return system.matches ? onSystem : otherwise;
    }

    function apply(value) {
      root.setAttribute(attribute, value);
      render(value);
    }

    apply(load(key, values) || systemValue());
    system.addEventListener("change", function () {
      if (!load(key, values)) {
        apply(systemValue());
      }
    });

    return {
      current: function () {
        return root.getAttribute(attribute);
      },
      choose: function (value) {
        save(key, value === systemValue() ? null : value);
        apply(value);
      },
      render: function () {
        render(root.getAttribute(attribute));
      },
    };
  }

  var theme = preference(
    "transkryptor-motyw",
    "data-theme",
    ["light", "dark"],
    "(prefers-color-scheme: dark)",
    "dark",
    function (value) {
      var label = value === "dark" ? "Włącz motyw jasny" : "Włącz motyw ciemny";
      each(".theme-toggle", function (button) {
        button.title = label;
        button.setAttribute("aria-label", label);
      });
    }
  );

  var animation = preference(
    "transkryptor-animacja",
    "data-animation",
    ["on", "off"],
    "(prefers-reduced-motion: reduce)",
    "off",
    function (value) {
      each(".motion-switch", function (button) {
        button.setAttribute("aria-checked", value === "on" ? "true" : "false");
      });
    }
  );

  function openFromHash() {
    var id = decodeURIComponent(window.location.hash.slice(1));
    var target = id && document.getElementById(id);
    if (!target) {
      return;
    }
    var details = target.closest("details");
    if (details && !details.open) {
      details.open = true;
      target.scrollIntoView();
    }
  }

  window.addEventListener("hashchange", openFromHash);

  document.addEventListener("DOMContentLoaded", function () {
    each(".theme-toggle", function (button) {
      button.hidden = false;
      button.addEventListener("click", function () {
        theme.choose(theme.current() === "dark" ? "light" : "dark");
      });
    });
    theme.render();

    each(".motion-switch", function (button) {
      button.hidden = false;
      button.addEventListener("click", function () {
        animation.choose(animation.current() === "on" ? "off" : "on");
      });
    });
    animation.render();

    each("[data-toggle-all]", function (button) {
      var section = document.querySelector(button.getAttribute("data-toggle-all"));
      if (!section) {
        return;
      }
      var cards = section.querySelectorAll("details");
      function update() {
        var allOpen = true;
        for (var i = 0; i < cards.length; i++) {
          allOpen = allOpen && cards[i].open;
        }
        button.textContent = allOpen ? "Zwiń wszystkie" : "Rozwiń wszystkie";
        button.setAttribute("aria-expanded", allOpen ? "true" : "false");
        return allOpen;
      }
      for (var i = 0; i < cards.length; i++) {
        cards[i].addEventListener("toggle", update);
      }
      button.hidden = false;
      button.addEventListener("click", function () {
        var open = !update();
        for (var i = 0; i < cards.length; i++) {
          cards[i].open = open;
        }
        update();
      });
      update();
    });

    openFromHash();
  });
})();
