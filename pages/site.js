// Skrypt strony projektu. Ładowany w <head> bez defer, żeby motyw i stan
// animacji były ustawione przed pierwszym malowaniem (bez mignięcia jasnej
// strony w trybie ciemnym i bez ruchu liter, które zaraz się zatrzymają).
//
// - Motyw jasny/ciemny: domyślnie taki jak w przeglądarce, przycisk
//   .theme-toggle zapamiętuje wybór. Ustawia data-theme na <html>.
// - Animacja liter w tle: przełącznik .motion-switch; domyślnie włączona,
//   chyba że system prosi o ograniczenie ruchu. Ustawia data-animation.
// - Menu na wąskich ekranach: przycisk .menu-toggle rozwija listę stron
//   pod paskiem. Ustawia data-menu (closed/open) na <html>; bez skryptu
//   atrybutu nie ma i menu zawija się do drugiego wiersza paska.
// - Karty <details>: adres z #kotwicą rozwija wskazaną kartę, a przycisk
//   [data-toggle-all] rozwija albo zwija wszystkie karty w swojej sekcji.
// - Pobieranie: karta dla systemu odwiedzającego jest wyróżniona, a główny
//   przycisk pobierania prowadzi wprost do jej pliku.
// - Formularz zgłoszeń (zglos.html): wysyła zgłoszenie do Workera
//   (zgloszenia/worker.js), który zakłada issue na GitHubie. Bez adresu
//   Workera albo bez skryptów zostaje odnośnik do zgłoszeń na GitHubie.
// - window.Transkryptor: wspólne narzędzia (Turnstile, wysyłka do Workera)
//   dla skryptów zgłoszeń - status i podobne zgłoszenia (issues.js,
//   similar-issues.js) oraz podgląd zgłoszenia z komentarzami (issue.js).
(function () {
  "use strict";

  var root = document.documentElement;
  root.setAttribute("data-menu", "closed");

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

  // Historia zmian była kiedyś sekcją strony głównej - stare odnośniki
  // (index.html#zmiany, index.html#v0.7.0) prowadzą teraz na jej stronę.
  var OLD_CHANGELOG_HASH = /^#(zmiany|v\d+\.\d+\.\d+)$/;

  function redirectOldChangelogLink() {
    var hash = window.location.hash;
    var home = document.getElementById("pobierz");
    if (home && OLD_CHANGELOG_HASH.test(hash) && !document.getElementById(hash.slice(1))) {
      window.location.replace("zmiany.html" + hash);
      return true;
    }
    return false;
  }

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

  function element(tag, className, text) {
    var node = document.createElement(tag);
    if (className) {
      node.className = className;
    }
    if (text) {
      node.textContent = text;
    }
    return node;
  }

  var REPORT_MESSAGES = {
    errors: {
      invalid: "Sprawdź pola formularza i spróbuj ponownie.",
      captcha:
        "Nie udało się potwierdzić, że nie jesteś robotem. Spróbuj ponownie.",
      "too-many":
        "Za dużo zgłoszeń w krótkim czasie. Spróbuj ponownie za kilka minut.",
    },
    failed:
      "Nie udało się wysłać zgłoszenia. Spróbuj ponownie za chwilę - " +
      "wpisany tekst nie zniknie.",
  };
  var CAPTCHA_WAIT =
    "Poczekaj chwilę, aż zakończy się sprawdzanie, czy nie jesteś robotem.";

  // Ochrona przed botami (Cloudflare Turnstile) - skrypt ładowany tylko
  // na stronach z formularzem i tylko wtedy, gdy ustawiono klucz. Zwraca
  // null bez klucza; token() jest pusty, dopóki sprawdzanie trwa.
  function captchaField(container, sitekey) {
    if (!sitekey) {
      return null;
    }
    var id = null;
    window.transkryptorCaptcha = function () {
      id = window.turnstile.render(container, {
        sitekey: sitekey,
        language: "pl",
        theme: root.getAttribute("data-theme") === "dark" ? "dark" : "light",
      });
    };
    var script = document.createElement("script");
    script.src =
      "https://challenges.cloudflare.com/turnstile/v0/api.js" +
      "?render=explicit&onload=transkryptorCaptcha";
    script.async = true;
    document.head.appendChild(script);
    var ready = function () {
      return window.turnstile && id !== null;
    };
    return {
      token: function () {
        return ready() ? window.turnstile.getResponse(id) || "" : "";
      },
      // Token Turnstile jest jednorazowy.
      reset: function () {
        if (ready()) {
          window.turnstile.reset(id);
        }
      },
    };
  }

  // Wysyła formularz do Workera zgłoszeń. Odrzucona obietnica ma zawsze
  // userMessage z messages (błąd sieci - TypeError - ma komunikat
  // przeglądarki po angielsku, więc go nie pokazujemy).
  function sendToWorker(url, payload, messages) {
    return fetch(url, {
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
              throw { userMessage: messages.errors[data.error] || messages.failed };
            }
            return data;
          });
      })
      .catch(function (error) {
        throw { userMessage: (error && error.userMessage) || messages.failed };
      });
  }

  // Napis stanu formularza ([data-*-status]); isError wyróżnia błąd.
  function statusLine(node) {
    return function (text, isError) {
      node.textContent = text;
      node.classList.toggle("error", Boolean(isError));
    };
  }

  // Pola formularza bez białych znaków na brzegach; zwraca pierwsze błędne
  // pole albo null i oznacza błędne aria-invalid.
  function firstInvalid(form, names) {
    var invalid = null;
    names.forEach(function (name) {
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

  // Rodzaje zgłoszeń (wartości pola rodzaj) i ich nazwy w Workerze.
  var REPORT_KINDS = {
    blad: "bug",
    pomysl: "idea",
    pytanie: "question",
    tekst: "text",
    strona: "webpage",
  };
  // Pola zależne od rodzaju i ich nazwy w Workerze.
  var REPORT_KIND_FIELDS = {
    obszar: "area",
    kroki: "steps",
    oczekiwane: "expected",
    faktyczne: "actual",
    czestosc: "frequency",
    problem: "problem",
  };

  // Wartość pola bez białych znaków na brzegach; pole schowane, bo nie
  // dotyczy wybranego rodzaju zgłoszenia, daje "".
  function shownValue(form, name) {
    var field = form.elements[name];
    var group = field.closest("[data-for-kind]");
    return group && group.hidden ? "" : field.value.trim();
  }

  // Nazwy wymaganych pól, które dotyczą wybranego rodzaju zgłoszenia.
  function requiredShown(form) {
    var names = [];
    Array.prototype.forEach.call(form.elements, function (field) {
      var group = field.closest("[data-for-kind]");
      if (field.required && !(group && group.hidden)) {
        names.push(field.name);
      }
    });
    return names;
  }

  function reportPayload(form, token) {
    var elements = form.elements;
    var payload = {
      kind: REPORT_KINDS[elements.rodzaj.value] || "bug",
      title: elements.tytul.value,
      description: elements.opis.value,
      version: shownValue(form, "wersja"),
      system: shownValue(form, "system"),
      website: elements.strona.value,
      token: token,
    };
    Object.keys(REPORT_KIND_FIELDS).forEach(function (name) {
      payload[REPORT_KIND_FIELDS[name]] = shownValue(form, name);
    });
    return payload;
  }

  function reportForm() {
    var form = document.querySelector("[data-report-form]");
    var endpoint = form && form.getAttribute("data-endpoint");
    if (!endpoint || !window.fetch) {
      return;
    }
    var say = statusLine(form.querySelector("[data-report-status]"));
    var submit = form.querySelector("[data-report-submit]");
    var done = document.querySelector("[data-report-done]");
    var doneLink = done.querySelector("[data-report-link]");

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
    if (Object.prototype.hasOwnProperty.call(REPORT_KINDS, params.get("rodzaj"))) {
      form.elements.rodzaj.value = params.get("rodzaj");
    }

    // Wskazówki i pola dotyczące tylko niektórych rodzajów zgłoszeń.
    function showKindFields() {
      var kind = form.elements.rodzaj.value;
      each("[data-for-kind]", function (node) {
        node.hidden = node.getAttribute("data-for-kind").split(" ").indexOf(kind) < 0;
      });
    }
    each('input[name="rodzaj"]', function (radio) {
      radio.addEventListener("change", showKindFields);
    });
    showKindFields();

    var captcha = captchaField(
      form.querySelector("[data-report-captcha]"),
      form.getAttribute("data-sitekey")
    );

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      var invalid = firstInvalid(form, requiredShown(form));
      if (invalid) {
        say(
          "Uzupełnij wymagane pola zaznaczone na czerwono: tytuł (co najmniej " +
            "5 znaków), opis (co najmniej 10 znaków) i pozostałe pola " +
            "tego rodzaju zgłoszenia.",
          true
        );
        invalid.focus();
        return;
      }
      var token = captcha ? captcha.token() : "";
      if (captcha && !token) {
        say(CAPTCHA_WAIT, true);
        return;
      }
      submit.disabled = true;
      say("Wysyłanie...", false);
      sendToWorker(endpoint, reportPayload(form, token), REPORT_MESSAGES)
        .then(function (data) {
          say("", false);
          // Pole-pułapka dostaje sukces bez numeru zgłoszenia.
          doneLink.hidden = !data.number;
          if (data.number) {
            doneLink.querySelector("a").href = "zgloszenie.html?nr=" + data.number;
          }
          form.hidden = true;
          done.hidden = false;
          done.focus();
        })
        .catch(function (error) {
          say(error.userMessage, true);
        })
        .then(function () {
          submit.disabled = false;
          if (captcha) {
            captcha.reset();
          }
        });
    });

    done.querySelector("[data-report-again]").addEventListener("click", function () {
      ["tytul", "opis"].concat(Object.keys(REPORT_KIND_FIELDS)).forEach(function (name) {
        form.elements[name].value = "";
      });
      form.elements.tytul.dispatchEvent(new Event("input"));
      done.hidden = true;
      form.hidden = false;
      form.elements.tytul.focus();
    });
  }

  // Wspólne narzędzia dla skryptów zgłoszeń (issues.js, issue.js,
  // similar-issues.js), ładowanych z defer po tym pliku.
  window.Transkryptor = {
    each: each,
    element: element,
    captchaField: captchaField,
    sendToWorker: sendToWorker,
    statusLine: statusLine,
    firstInvalid: firstInvalid,
    CAPTCHA_WAIT: CAPTCHA_WAIT,
  };

  function menu() {
    var button = document.querySelector(".menu-toggle");
    var nav = document.getElementById("menu");
    if (!button || !nav) {
      return;
    }
    var topbar = button.closest(".topbar");

    function set(open) {
      var label = open ? "Ukryj menu" : "Pokaż menu";
      root.setAttribute("data-menu", open ? "open" : "closed");
      button.setAttribute("aria-expanded", open ? "true" : "false");
      button.title = label;
      button.setAttribute("aria-label", label);
    }

    function isOpen() {
      return root.getAttribute("data-menu") === "open";
    }

    button.addEventListener("click", function () {
      set(!isOpen());
    });
    nav.addEventListener("click", function (event) {
      if (event.target.closest("a")) {
        set(false);
      }
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && isOpen()) {
        set(false);
        button.focus();
      }
    });
    document.addEventListener("click", function (event) {
      if (isOpen() && topbar && !topbar.contains(event.target)) {
        set(false);
      }
    });
    // Po poszerzeniu okna menu jest i tak widoczne w wierszu paska.
    window.matchMedia("(max-width: 820px)").addEventListener("change", function () {
      set(false);
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    menu();
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

    if (redirectOldChangelogLink()) {
      return;
    }
    highlightDownload();
    reportForm();
    openFromHash();
  });
})();
