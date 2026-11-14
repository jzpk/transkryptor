// Podobne zgłoszenia przy formularzu (zglos.html). Ładowany z defer po
// site.js i issues.js.
//
// Gdy ktoś wpisuje tytuł, skrypt raz pobiera listę zgłoszeń (to samo API co
// Status zgłoszeń) i pokazuje pod polem kilka najbardziej podobnych, żeby
// zamiast duplikatu można było dopisać się w istniejącym zgłoszeniu.
// Podobieństwo liczy się w przeglądarce: słowa tytułu i opisu porównywane
// po początkach (pierwsze STEM_LENGTH liter bez polskich znaków), co
// wystarcza na odmianę („zapisać”, „zapisuje”, „zapis”). Wyszukiwarka API
// GitHuba odpada - bez tokenu pozwala na 10 zapytań na minutę i nie zna
// polskiej odmiany. Odrzucone zgłoszenia (np. duplikaty) są pomijane.
(function () {
  "use strict";

  var T = window.Transkryptor;
  var box = document.querySelector("[data-similar]");
  if (!T || !T.issues || !box || !window.fetch) {
    return;
  }
  var element = T.element;
  var issues = T.issues;
  var form = box.closest("form");
  var title = form && form.elements.tytul;
  var api = box.getAttribute("data-api");
  if (!title || !api) {
    return;
  }

  var STEM_LENGTH = 5;
  var MIN_WORD = 3;
  var MAX_SHOWN = 4;
  // Część słów zapytania, która musi pasować (słowa w tytule liczą się
  // podwójnie, w opisie pojedynczo).
  var MIN_SCORE = 0.4;
  var DELAY_MS = 400;
  // Opis długich zgłoszeń wystarczy porównać po początku.
  var BODY_CHARS = 2000;
  var STOPWORDS = [
    "ale", "albo", "ani", "bez", "być", "czy", "dla", "gdy", "jak", "jest",
    "już", "lub", "mam", "może", "nie", "się", "tak", "też", "tym", "ten",
    "przy", "przez", "oraz", "żeby", "kiedy", "który", "która",
    "które", "program", "programu", "programie", "transkryptor",
  ];

  function plain(text) {
    return String(text || "")
      .toLowerCase()
      .replace(/ł/g, "l")
      .normalize("NFD")
      .replace(/[̀-ͯ]/g, "");
  }

  var STOP = {};
  STOPWORDS.forEach(function (word) {
    STOP[plain(word)] = true;
  });

  // Różne początki znaczących słów tekstu.
  function stems(text) {
    var seen = {};
    var result = [];
    plain(text)
      .split(/[^a-z0-9]+/)
      .forEach(function (word) {
        if (word.length < MIN_WORD || STOP[word]) {
          return;
        }
        var stem = word.slice(0, STEM_LENGTH);
        if (!seen[stem]) {
          seen[stem] = true;
          result.push(stem);
        }
      });
    return result;
  }

  function stemSet(text) {
    var set = {};
    stems(text).forEach(function (stem) {
      set[stem] = true;
    });
    return set;
  }

  var index = null;
  var loading = null;

  // Lista zgłoszeń z wyliczonymi słowami; po błędzie podpowiedzi
  // po prostu się nie pojawiają.
  function load() {
    if (!loading) {
      loading = issues
        .fetchIssues(api)
        .then(function (data) {
          index = data
            .filter(function (issue) {
              return issues.state(issue) !== "rejected";
            })
            .map(function (issue) {
              return {
                issue: issue,
                title: stemSet(issue.title),
                body: stemSet(String(issue.body || "").slice(0, BODY_CHARS)),
              };
            });
        })
        .catch(function () {
          index = [];
        });
    }
    return loading;
  }

  function score(query, entry) {
    var titleHits = 0;
    var points = 0;
    query.forEach(function (stem) {
      if (entry.title[stem]) {
        titleHits += 1;
        points += 2;
      } else if (entry.body[stem]) {
        points += 1;
      }
    });
    return titleHits ? points / (2 * query.length) : 0;
  }

  // Najbardziej podobne zgłoszenia; przy remisie otwarte przed zamkniętymi.
  function similar(text) {
    var query = stems(text);
    if (!index || query.length < 2) {
      return [];
    }
    return index
      .map(function (entry) {
        return { issue: entry.issue, score: score(query, entry) };
      })
      .filter(function (match) {
        return match.score >= MIN_SCORE;
      })
      .sort(function (a, b) {
        var open = (b.issue.state === "open") - (a.issue.state === "open");
        return b.score - a.score || open;
      })
      .slice(0, MAX_SHOWN)
      .map(function (match) {
        return match.issue;
      });
  }

  var list = box.querySelector("[data-similar-list]");
  var shownKey = "";

  function render() {
    var found = similar(title.value);
    var key = found
      .map(function (issue) {
        return issue.number;
      })
      .join(",");
    if (key === shownKey) {
      return;
    }
    shownKey = key;
    list.textContent = "";
    found.forEach(function (issue) {
      // Nowa karta: wpisany tekst formularza zostaje.
      list.appendChild(issues.item(issue, "_blank"));
    });
    box.hidden = !found.length;
  }

  var timer = null;
  title.addEventListener("input", function () {
    window.clearTimeout(timer);
    timer = window.setTimeout(function () {
      load().then(render);
    }, DELAY_MS);
  });
  // Pobranie listy zaczyna się, gdy ktoś zacznie pisać, a nie przy wejściu.
  title.addEventListener("focus", load, { once: true });
})();
