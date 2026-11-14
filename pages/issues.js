// Zgłoszenia z GitHuba na stronie projektu. Ładowany z defer po site.js
// (korzysta z window.Transkryptor) na stronach zgłoszeń.
//
// - Transkryptor.issues: stan zgłoszenia z etykiet i plakietka stanu,
//   pobieranie kolejnych stron API i adres podglądu zgłoszenia - wspólne
//   dla listy, podglądu (issue.js) i podobnych zgłoszeń (similar-issues.js).
// - Status zgłoszeń (zgloszenia.html): pobiera zgłoszenia z API GitHuba
//   i pokazuje ich stan z filtrami i podziałem na strony (?pokaz=&strona=
//   w adresie); legenda opisuje stany z wybranego filtra. Tytuł prowadzi
//   do podglądu zgłoszenia na stronie. Po błędzie zostaje odnośnik do GitHuba.
(function () {
  "use strict";

  var T = window.Transkryptor;
  if (!T) {
    return;
  }
  var each = T.each;
  var element = T.element;

  // Stan zgłoszenia na stronie statusu. Zamknięte jako „not planned” albo
  // duplikat są odrzucone, pozostałe zamknięte - zrobione: wydane, gdy mają
  // etykietę wersji (nadaje ją workflow wydania), inaczej niewydane.
  // Zgłoszenia strony (ISSUE_WEBPAGE_LABEL) nie czekają na wydanie programu:
  // są wdrożone, gdy mają etykietę ISSUE_DEPLOYED_LABEL (nadaje ją workflow
  // strony), inaczej niewdrożone; etykieta wersji ma pierwszeństwo. Otwarte
  // są „w toku”, gdy mają etykietę ISSUE_PROGRESS_LABELS albo przypisaną
  // osobę. Kolejność kluczy to kolejność na liście: najpierw sprawy w toku
  // i otwarte. Do napisu wydanych dochodzi numer wersji.
  var ISSUE_STATES = {
    progress: "W toku",
    open: "Otwarte",
    unreleased: "Zrobione, niewydane",
    undeployed: "Niewdrożone",
    released: "Wydane",
    deployed: "Wdrożone",
    rejected: "Odrzucone",
  };
  var ISSUE_VERSION_LABEL = /^v?(\d+)\.(\d+)\.(\d+)$/;
  var ISSUE_WEBPAGE_LABEL = "webpage";
  // Małymi literami - labelNames() porównuje nazwy etykiet bez wielkości liter.
  var ISSUE_DEPLOYED_LABEL = "deployed";
  var ISSUE_PROGRESS_LABELS = ["w-toku", "in progress"];
  var ISSUE_KINDS = { bug: "Błąd", enhancement: "Pomysł" };
  var ISSUE_PAGE = "zgloszenie.html";
  var ISSUES_FAILED =
    "Nie udało się pobrać listy zgłoszeń. Spróbuj ponownie za chwilę " +
    "albo sprawdź je w ";

  function labelNames(issue) {
    return (issue.labels || []).map(function (label) {
      return String(typeof label === "string" ? label : label.name).toLowerCase();
    });
  }

  // Najwyższa wersja z etykiet zgłoszenia (bez „v”) albo null.
  function issueRelease(issue) {
    var best = null;
    labelNames(issue).forEach(function (name) {
      var match = ISSUE_VERSION_LABEL.exec(name);
      if (!match) {
        return;
      }
      var parts = match.slice(1).map(Number);
      var newer = best
        ? parts[0] - best[0] || parts[1] - best[1] || parts[2] - best[2]
        : 1;
      if (newer > 0) {
        best = parts;
      }
    });
    return best && best.join(".");
  }

  function closedState(issue) {
    if (issueRelease(issue)) {
      return "released";
    }
    var labels = labelNames(issue);
    if (labels.indexOf(ISSUE_WEBPAGE_LABEL) < 0) {
      return "unreleased";
    }
    return labels.indexOf(ISSUE_DEPLOYED_LABEL) >= 0 ? "deployed" : "undeployed";
  }

  function issueState(issue) {
    if (issue.state === "closed") {
      if (
        issue.state_reason === "not_planned" ||
        issue.state_reason === "duplicate"
      ) {
        return "rejected";
      }
      return closedState(issue);
    }
    var labels = labelNames(issue);
    var inProgress = ISSUE_PROGRESS_LABELS.some(function (name) {
      return labels.indexOf(name) >= 0;
    });
    return inProgress || (issue.assignees && issue.assignees.length)
      ? "progress"
      : "open";
  }

  // „Błąd”, „Pomysł” albo "" według etykiet.
  function issueKind(issue) {
    var labels = labelNames(issue);
    for (var name in ISSUE_KINDS) {
      if (labels.indexOf(name) >= 0) {
        return ISSUE_KINDS[name];
      }
    }
    return "";
  }

  // Plakietka stanu; wersja wydanych prowadzi do jej sekcji w historii zmian.
  function stateBadge(issue) {
    var state = issueState(issue);
    var badge;
    if (state === "released") {
      var version = issueRelease(issue);
      badge = element("a", "issue-state", ISSUE_STATES[state] + " " + version);
      badge.href = "zmiany.html#v" + version;
      badge.title = "Historia zmian wersji " + version;
    } else {
      badge = element("span", "issue-state", ISSUE_STATES[state]);
    }
    badge.setAttribute("data-state", state);
    return badge;
  }

  function issueUrl(issue) {
    return ISSUE_PAGE + "?nr=" + issue.number;
  }

  // Wiersz listy zgłoszeń: stan, tytuł (do podglądu) i rodzaj. Bez numeru
  // zgłoszenia: numeracja GitHuba (wspólna z pull requestami) ma przerwy,
  // które osobom spoza projektu wyglądają na zgubione zgłoszenia.
  function issueItem(issue, linkTarget) {
    var item = element("li", "issue");
    item.appendChild(stateBadge(issue));
    var link = element("a", "issue-title", issue.title);
    link.href = issueUrl(issue);
    if (linkTarget) {
      link.target = linkTarget;
      link.rel = "noopener";
    }
    item.appendChild(link);
    item.appendChild(element("span", "issue-meta small", issueKind(issue)));
    return item;
  }

  // Kolejne strony odpowiedzi API (nagłówek Link z rel="next"), najwyżej
  // requestsLeft zapytań. accept wybiera postać treści (np. z body_html).
  function fetchPages(url, requestsLeft, accept) {
    // no-cache: API pozwala trzymać odpowiedź w pamięci podręcznej minutę,
    // a świeżo wysłane zgłoszenie ma się pojawić od razu. Przeglądarka pyta
    // z ETagiem, więc niezmienionej listy nie pobiera ponownie.
    return fetch(url, {
      headers: { Accept: accept || "application/vnd.github+json" },
      cache: "no-cache",
    }).then(function (response) {
      if (!response.ok) {
        throw { status: response.status };
      }
      var next = /<([^>]+)>;\s*rel="next"/.exec(response.headers.get("Link") || "");
      return response.json().then(function (items) {
        if (!next || requestsLeft <= 1) {
          return items;
        }
        return fetchPages(next[1], requestsLeft - 1, accept).then(function (more) {
          return items.concat(more);
        });
      });
    });
  }

  // Bez tokenu API pozwala na 60 zapytań na godzinę z jednego adresu, więc
  // pobieramy najwyżej tyle stron po 100 ostatnio zmienionych zgłoszeń.
  var ISSUES_MAX_REQUESTS = 3;

  // Zgłoszenia z listy API bez pull requestów (API zwraca też je).
  function fetchIssues(url) {
    return fetchPages(url, ISSUES_MAX_REQUESTS).then(function (data) {
      return data.filter(function (issue) {
        return !issue.pull_request;
      });
    });
  }

  T.issues = {
    STATES: ISSUE_STATES,
    state: issueState,
    kind: issueKind,
    badge: stateBadge,
    item: issueItem,
    url: issueUrl,
    fetchPages: fetchPages,
    fetchIssues: fetchIssues,
  };

  // Filtry listy: nazwa w adresie (?pokaz=) → stany zgłoszeń. Pierwszy
  // jest domyślny.
  var ISSUE_FILTERS = {
    aktywne: ["progress", "open"],
    zrobione: ["unreleased", "undeployed", "released", "deployed"],
    niewydane: ["unreleased", "undeployed"],
    odrzucone: ["rejected"],
    wszystkie: Object.keys(ISSUE_STATES),
  };
  var ISSUES_PER_PAGE = 20;

  // Numery stron do pokazania: pierwsza, ostatnia i sąsiedzi bieżącej;
  // null oznacza przerwę („…”). Przerwa nie zastępuje jednej strony.
  function pageNumbers(current, count) {
    var pages = [];
    for (var page = 1; page <= count; page++) {
      var distance = Math.abs(page - current);
      var edge = page <= 2 || page >= count - 1;
      if (page === 1 || page === count || distance <= 1 || (edge && distance === 2)) {
        pages.push(page);
      } else if (pages[pages.length - 1] !== null) {
        pages.push(null);
      }
    }
    return pages;
  }

  // API sortuje od ostatnio zmienionych; to zostaje w obrębie stanu.
  function sortByState(data) {
    var order = Object.keys(ISSUE_STATES);
    return data
      .map(function (issue, index) {
        return { issue: issue, rank: order.indexOf(issueState(issue)), index: index };
      })
      .sort(function (a, b) {
        return a.rank - b.rank || a.index - b.index;
      })
      .map(function (entry) {
        return entry.issue;
      });
  }

  function issueStatus() {
    var container = document.querySelector("[data-issues]");
    var api = container && container.getAttribute("data-api");
    if (!api || !window.fetch) {
      return;
    }
    var filters = document.querySelector("[data-issues-filters]");
    var pager = document.querySelector("[data-issues-pager]");
    var fallback = container.querySelector("[data-issues-status]");
    var githubLink = fallback.querySelector("a").cloneNode(true);
    var issues = [];
    var params = new URLSearchParams(window.location.search);
    var filter = ISSUE_FILTERS[params.get("pokaz")]
      ? params.get("pokaz")
      : Object.keys(ISSUE_FILTERS)[0];
    var page = parseInt(params.get("strona"), 10) || 1;

    fallback.textContent = "Wczytywanie zgłoszeń...";
    container.setAttribute("aria-busy", "true");

    function remember() {
      var query = new URLSearchParams(window.location.search);
      query.set("pokaz", filter);
      if (page > 1) {
        query.set("strona", String(page));
      } else {
        query.delete("strona");
      }
      try {
        history.replaceState(null, "", "?" + query.toString() + window.location.hash);
      } catch (error) {
        // Bez historii (np. plik otwarty z dysku) stan widać tylko na stronie.
      }
    }

    function pagerButton(label, target, current) {
      var button = element("button", "button compact", label);
      button.type = "button";
      button.setAttribute("aria-label", "Strona " + label);
      if (current) {
        button.setAttribute("aria-current", "page");
      }
      if (target === null) {
        button.disabled = true;
      } else {
        button.addEventListener("click", function () {
          page = target;
          render();
          filters.scrollIntoView({ block: "start" });
        });
      }
      return button;
    }

    // Na wąskim ekranie zostaje sama strzałka (słowo ukrywa style.css).
    function stepButton(arrow, word, target) {
      var button = pagerButton("", target);
      button.setAttribute("aria-label", word + " strona");
      var next = arrow === "›";
      var label = element("span", "issues-pager-word", next ? word + " " : " " + word);
      button.appendChild(element("span", "", arrow));
      button.insertBefore(label, next ? button.firstChild : null);
      return button;
    }

    function inFilter(name) {
      return function (issue) {
        return ISSUE_FILTERS[name].indexOf(issueState(issue)) >= 0;
      };
    }

    function renderFilters() {
      each("[data-filter]", function (button) {
        var name = button.getAttribute("data-filter");
        var count = issues.filter(inFilter(name)).length;
        button.textContent = button.getAttribute("data-label") + " (" + count + ")";
        button.setAttribute("aria-pressed", name === filter ? "true" : "false");
      });
      // Legenda opisuje tylko stany widoczne w bieżącym filtrze.
      each("[data-issues-legend] li", function (item) {
        var state = item.querySelector("[data-state]").getAttribute("data-state");
        item.hidden = ISSUE_FILTERS[filter].indexOf(state) < 0;
      });
    }

    function renderPager(pages) {
      pager.textContent = "";
      pager.hidden = pages < 2;
      pager.appendChild(stepButton("‹", "Poprzednia", page > 1 ? page - 1 : null));
      pageNumbers(page, pages).forEach(function (number) {
        if (number === null) {
          pager.appendChild(element("span", "issues-gap", "…"));
        } else {
          pager.appendChild(pagerButton(String(number), number, number === page));
        }
      });
      pager.appendChild(stepButton("›", "Następna", page < pages ? page + 1 : null));
    }

    function render() {
      var shown = issues.filter(inFilter(filter));
      var pages = Math.max(1, Math.ceil(shown.length / ISSUES_PER_PAGE));
      page = Math.min(Math.max(page, 1), pages);
      remember();
      renderFilters();

      container.textContent = "";
      if (!shown.length) {
        container.appendChild(
          element("p", "issues-fallback", "Brak zgłoszeń w tym widoku.")
        );
      } else {
        var list = element("ul", "issues-items");
        shown
          .slice((page - 1) * ISSUES_PER_PAGE, page * ISSUES_PER_PAGE)
          .forEach(function (issue) {
            list.appendChild(issueItem(issue));
          });
        container.appendChild(list);
      }
      renderPager(pages);
    }

    each("[data-filter]", function (button) {
      button.setAttribute("data-label", button.textContent.trim());
      button.addEventListener("click", function () {
        filter = button.getAttribute("data-filter");
        page = 1;
        render();
      });
    });

    fetchIssues(api)
      .then(function (data) {
        if (!data.length) {
          fallback.textContent = "Nie ma jeszcze żadnych zgłoszeń.";
          return;
        }
        issues = sortByState(data);
        filters.hidden = false;
        render();
      })
      .catch(function () {
        fallback.textContent = ISSUES_FAILED;
        fallback.appendChild(githubLink);
        fallback.appendChild(document.createTextNode("."));
        fallback.classList.add("error");
      })
      .then(function () {
        container.setAttribute("aria-busy", "false");
      });
  }

  issueStatus();
})();
