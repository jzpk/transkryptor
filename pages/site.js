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
// - Pobieranie: karta dla systemu odwiedzającego jest wyróżniona, a główny
//   przycisk pobierania prowadzi wprost do jej pliku.
// - Formularz zgłoszeń (zglos.html): wysyła zgłoszenie do Workera
//   (zgloszenia/worker.js), który zakłada issue na GitHubie. Bez adresu
//   Workera albo bez skryptów zostaje odnośnik do zgłoszeń na GitHubie.
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
  // Wybór zgodny z domyślną nie jest zapamiętywany - wtedy strona znów
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
      // Zrzuty ekranu: <source data-theme-source> ma w HTML media według
      // przeglądarki (działa bez skryptu); tu idzie za wybranym motywem.
      each("source[data-theme-source]", function (source) {
        source.media = value === "dark" ? "all" : "not all";
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

  // System odwiedzającego: "windows", "linux" albo null (macOS, telefony
  // i inne - dla nich nie ma wydania, więc strona niczego nie wyróżnia).
  function visitorOs() {
    var agent = navigator.userAgent || "";
    var platform =
      (navigator.userAgentData && navigator.userAgentData.platform) ||
      navigator.platform ||
      "";
    if (/android|iphone|ipad|ipod|cros/i.test(agent)) {
      return null;
    }
    if (/win/i.test(platform) || /windows/i.test(agent)) {
      return "windows";
    }
    if (/linux/i.test(platform) || /linux|x11/i.test(agent)) {
      return "linux";
    }
    return null;
  }

  // Wyróżnia kartę pobierania dla systemu odwiedzającego, a przycisk
  // [data-download-for-os] prowadzi od razu do jej pliku.
  function highlightDownload() {
    var os = visitorOs();
    var card = os && document.querySelector('.download[data-os="' + os + '"]');
    if (!card) {
      return;
    }
    card.classList.add("recommended");
    each("[data-download-for-os]", function (button) {
      button.href = card.href;
      button.textContent =
        "Pobierz dla " +
        card.getAttribute("data-for") +
        " (" +
        button.getAttribute("data-version") +
        ")";
    });
  }

  var REPORT_ERRORS = {
    invalid: "Sprawdź pola formularza i spróbuj ponownie.",
    captcha:
      "Nie udało się potwierdzić, że nie jesteś robotem. Spróbuj ponownie.",
    "too-many":
      "Za dużo zgłoszeń w krótkim czasie. Spróbuj ponownie za kilka minut.",
  };
  var REPORT_FAILED =
    "Nie udało się wysłać zgłoszenia. Spróbuj ponownie za chwilę - " +
    "wpisany tekst nie zniknie.";

  // Ochrona przed botami (Cloudflare Turnstile) - skrypt ładowany tylko
  // na stronie formularza i tylko wtedy, gdy ustawiono klucz.
  function loadCaptcha(container, sitekey, onReady) {
    window.transkryptorCaptcha = function () {
      onReady(
        window.turnstile.render(container, {
          sitekey: sitekey,
          language: "pl",
          theme: root.getAttribute("data-theme") === "dark" ? "dark" : "light",
        })
      );
    };
    var script = document.createElement("script");
    script.src =
      "https://challenges.cloudflare.com/turnstile/v0/api.js" +
      "?render=explicit&onload=transkryptorCaptcha";
    script.async = true;
    document.head.appendChild(script);
  }

  function reportForm() {
    var form = document.querySelector("[data-report-form]");
    var endpoint = form && form.getAttribute("data-endpoint");
    if (!endpoint || !window.fetch) {
      return;
    }
    var sitekey = form.getAttribute("data-sitekey");
    var status = form.querySelector("[data-report-status]");
    var submit = form.querySelector("[data-report-submit]");
    var done = document.querySelector("[data-report-done]");
    var captchaId = null;

    document.querySelector("[data-report-fallback]").hidden = true;
    form.hidden = false;

    // Program otwiera formularz z wersją i systemem w adresie.
    var params = new URLSearchParams(window.location.search);
    ["wersja", "system"].forEach(function (name) {
      var value = params.get(name);
      if (value) {
        var field = form.elements[name];
        field.value = value.slice(0, field.maxLength);
      }
    });
    if (params.get("rodzaj") === "pomysl") {
      form.elements.rodzaj.value = "pomysl";
    }

    function showHints() {
      var kind = form.elements.rodzaj.value;
      each("[data-hint-for]", function (hint) {
        hint.hidden = hint.getAttribute("data-hint-for") !== kind;
      });
    }
    each('input[name="rodzaj"]', function (radio) {
      radio.addEventListener("change", showHints);
    });
    showHints();

    if (sitekey) {
      var captcha = form.querySelector("[data-report-captcha]");
      loadCaptcha(captcha, sitekey, function (id) {
        captchaId = id;
      });
    }

    function say(text, isError) {
      status.textContent = text;
      status.classList.toggle("error", Boolean(isError));
    }

    // Zwraca pierwsze błędne pole albo null.
    function validate() {
      var invalid = null;
      ["tytul", "opis", "email"].forEach(function (name) {
        var field = form.elements[name];
        field.value = field.value.trim();
        var ok = field.checkValidity();
        field.setAttribute("aria-invalid", ok ? "false" : "true");
        if (!ok && !invalid) {
          invalid = field;
        }
      });
      return invalid;
    }

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      var invalid = validate();
      if (invalid) {
        say(
          invalid.name === "email"
            ? "Adres e-mail wygląda na niepoprawny - popraw go albo zostaw pole puste."
            : "Uzupełnij tytuł (co najmniej 5 znaków) i opis (co najmniej 10 znaków).",
          true
        );
        invalid.focus();
        return;
      }
      var token = "";
      if (sitekey) {
        if (window.turnstile && captchaId !== null) {
          token = window.turnstile.getResponse(captchaId) || "";
        }
        if (!token) {
          say(
            "Poczekaj chwilę, aż zakończy się sprawdzanie, czy nie jesteś robotem.",
            true
          );
          return;
        }
      }
      var elements = form.elements;
      var payload = {
        kind: elements.rodzaj.value === "pomysl" ? "idea" : "bug",
        title: elements.tytul.value,
        description: elements.opis.value,
        email: elements.email.value,
        version: elements.wersja.value.trim(),
        system: elements.system.value.trim(),
        website: elements.strona.value,
        token: token,
      };
      submit.disabled = true;
      say("Wysyłanie...", false);
      fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
        .then(function (response) {
          return response
            .json()
            .catch(function () {
              return {};
            })
            .then(function (data) {
              if (!response.ok) {
                throw { userMessage: REPORT_ERRORS[data.error] || REPORT_FAILED };
              }
              return data;
            });
        })
        .then(function (data) {
          say("", false);
          form.hidden = true;
          var number = done.querySelector("[data-report-number]");
          number.textContent = data.number ? " (nr " + data.number + ")" : "";
          if (data.url) {
            done.querySelector("[data-report-link]").href = data.url;
          }
          done.hidden = false;
          done.focus();
        })
        .catch(function (error) {
          // Błąd sieci (TypeError) ma komunikat przeglądarki po angielsku.
          say((error && error.userMessage) || REPORT_FAILED, true);
        })
        .then(function () {
          submit.disabled = false;
          // Token Turnstile jest jednorazowy.
          if (window.turnstile && captchaId !== null) {
            window.turnstile.reset(captchaId);
          }
        });
    });

    done.querySelector("[data-report-again]").addEventListener("click", function () {
      ["tytul", "opis"].forEach(function (name) {
        form.elements[name].value = "";
      });
      done.hidden = true;
      form.hidden = false;
      form.elements.tytul.focus();
    });
  }

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

    highlightDownload();
    reportForm();
    openFromHash();
  });
})();
