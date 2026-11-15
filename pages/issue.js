// Podgląd zgłoszenia (zgloszenie.html?nr=N). Ładowany z defer po site.js
// i issues.js.
//
// Pobiera zgłoszenie i komentarze z publicznego API GitHuba (z HTML-em
// treści, który GitHub składa z Markdownu) i pokazuje je na stronie, żeby
// osoba bez konta na GitHubie mogła przeczytać odpowiedzi. HTML z API
// przechodzi jeszcze przez listę dozwolonych znaczników i atrybutów
// (sanitize) - strona nie wstawia cudzego HTML-a bez sprawdzenia.
//
// Formularz pod zgłoszeniem wysyła komentarz do Workera zgłoszeń
// (zgloszenia/worker.js, ścieżka /comment), który dodaje go na GitHubie.
// Wpisy z formularzy Worker kończy stopką (FORM_FOOTER) - po niej strona
// rozpoznaje je i podpisuje „Osoba zgłaszająca” albo „Użytkownik programu”
// zamiast konta, z którego Worker je wysyła, a samą stopkę ukrywa.
(function () {
  "use strict";

  var T = window.Transkryptor;
  var view = document.querySelector("[data-issue]");
  if (!T || !T.issues || !view || !window.fetch) {
    return;
  }
  var element = T.element;
  var issues = T.issues;

  var HTML_ACCEPT = "application/vnd.github.full+json";
  var COMMENTS_MAX_REQUESTS = 3;
  var FORM_FOOTER =
    /\n---\s*\n+_(Zgłoszenie|Komentarz) z formularza na stronie programu\.[^\n]*_\s*$/;
  var FORM_FOOTER_TEXT = /^(Zgłoszenie|Komentarz) z formularza na stronie programu\./;
  var TEAM = { OWNER: "Autor programu", MEMBER: "Zespół", COLLABORATOR: "Zespół" };
  var COMMENT_MESSAGES = {
    errors: {
      invalid: "Komentarz musi mieć od 10 do 5000 znaków.",
      captcha:
        "Nie udało się potwierdzić, że nie jesteś robotem. Spróbuj ponownie.",
      "too-many":
        "Za dużo wiadomości w krótkim czasie. Spróbuj ponownie za kilka minut.",
      "not-found": "To zgłoszenie już nie istnieje.",
      locked: "Dyskusja nad tym zgłoszeniem jest zamknięta.",
    },
    failed:
      "Nie udało się wysłać komentarza. Spróbuj ponownie za chwilę - " +
      "wpisany tekst nie zniknie.",
  };

  // Znaczniki z treści GitHuba, które zostają (pozostałe zostają zastąpione
  // swoją treścią), atrybuty dozwolone dla każdego z nich i znaczniki
  // usuwane razem z treścią.
  var ALLOWED = {
    A: ["href", "title"],
    IMG: ["src", "alt", "title", "width", "height"],
    TD: ["align"],
    TH: ["align"],
    OL: ["start"],
    DETAILS: ["open"],
  };
  [
    "P", "BR", "HR", "STRONG", "B", "EM", "I", "DEL", "S", "INS", "CODE",
    "PRE", "KBD", "SUP", "SUB", "BLOCKQUOTE", "UL", "LI", "H1", "H2", "H3",
    "H4", "H5", "H6", "TABLE", "THEAD", "TBODY", "TR", "SUMMARY", "SPAN",
    "DIV",
  ].forEach(function (tag) {
    ALLOWED[tag] = [];
  });
  var DROPPED = [
    "SCRIPT", "STYLE", "IFRAME", "OBJECT", "EMBED", "FORM", "INPUT", "BUTTON",
    "SELECT", "TEXTAREA", "SVG", "MATH", "VIDEO", "AUDIO", "SOURCE", "LINK",
    "META", "BASE", "TEMPLATE", "NOSCRIPT",
  ];

  // Adres z http(s) albo mailto (bez javascript: i podobnych) albo null.
  // Odnośniki do kotwic (#...) nic by nie dały - identyfikatory są usuwane.
  function safeUrl(value, allowMail) {
    if (!value || value.charAt(0) === "#") {
      return null;
    }
    try {
      var url = new URL(value, "https://github.com/");
      var ok =
        url.protocol === "https:" ||
        url.protocol === "http:" ||
        (allowMail && url.protocol === "mailto:");
      return ok ? url.href : null;
    } catch (error) {
      return null;
    }
  }

  // Obrazki tylko z pełnego adresu https na hostach GitHuba - GitHub
  // przepisuje obrazki ze zgłoszeń na camo.githubusercontent.com i swoje
  // serwery, więc obcy host oznacza piksel śledzący odwiedzających. Te same
  // hosty dopuszcza CSP strony (IMAGE_SOURCES w packaging/site_csp.py).
  function imageUrl(value) {
    var url = /^https:\/\//i.test(value) && safeUrl(value, false);
    if (!url) {
      return null;
    }
    var host = new URL(url).hostname;
    return host === "github.com" || /\.githubusercontent\.com$/.test(host) ? url : null;
  }

  function cleanAttributes(node) {
    var allowed = ALLOWED[node.tagName];
    Array.prototype.slice.call(node.attributes).forEach(function (attribute) {
      var name = attribute.name;
      var keep = allowed.indexOf(name) >= 0;
      if (keep && (name === "href" || name === "src")) {
        var url =
          name === "href" ? safeUrl(attribute.value, true) : imageUrl(attribute.value);
        keep = Boolean(url);
        if (keep) {
          node.setAttribute(name, url);
        }
      }
      if (!keep) {
        node.removeAttribute(name);
      }
    });
    if (node.tagName === "A" && node.hasAttribute("href")) {
      node.rel = "nofollow ugc noopener";
    }
    if (node.tagName === "IMG") {
      node.loading = "lazy";
      node.referrerPolicy = "no-referrer";
    }
  }

  function sanitizeChildren(parent) {
    Array.prototype.slice.call(parent.childNodes).forEach(function (node) {
      if (node.nodeType === Node.TEXT_NODE) {
        return;
      }
      if (node.nodeType !== Node.ELEMENT_NODE) {
        parent.removeChild(node);
        return;
      }
      var tag = node.tagName.toUpperCase();
      if (DROPPED.indexOf(tag) >= 0) {
        parent.removeChild(node);
        return;
      }
      sanitizeChildren(node);
      if (ALLOWED[tag]) {
        cleanAttributes(node);
        // Obrazek bez bezpiecznego adresu byłby pustą ramką.
        if (tag === "IMG" && !node.hasAttribute("src")) {
          parent.removeChild(node);
        }
        return;
      }
      while (node.firstChild) {
        parent.insertBefore(node.firstChild, node);
      }
      parent.removeChild(node);
    });
  }

  // Bezpieczny fragment z HTML-a treści. DOMParser niczego nie uruchamia
  // ani nie pobiera, więc obce znaczniki można sprawdzić przed wstawieniem.
  // Sprawdzone węzły są przenoszone (adoptNode), a nie serializowane
  // ponownie do HTML-a - dlatego nie grozi tu mutation XSS. Gdyby coś
  // jednak przeszło, skryptu nie uruchomi CSP strony (site_csp.py).
  function sanitize(html) {
    var doc = new DOMParser().parseFromString(String(html || ""), "text/html");
    sanitizeChildren(doc.body);
    var fragment = document.createDocumentFragment();
    while (doc.body.firstChild) {
      fragment.appendChild(document.adoptNode(doc.body.firstChild));
    }
    return fragment;
  }

  // Ukrywa stopkę formularza (ostatni akapit po linii poziomej).
  function dropFormFooter(body) {
    var last = body.lastElementChild;
    var rule = last && last.previousElementSibling;
    if (last && FORM_FOOTER_TEXT.test(last.textContent.trim()) && rule) {
      if (rule.tagName === "HR") {
        body.removeChild(rule);
        body.removeChild(last);
      }
    }
  }

  function formatTime(iso) {
    return new Date(iso).toLocaleString("pl-PL", {
      day: "numeric",
      month: "long",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  // Podpis wpisu: kto napisał i ewentualna rola w projekcie.
  function authorOf(post, isIssue) {
    if (FORM_FOOTER.test(post.body || "")) {
      return { name: isIssue ? "Osoba zgłaszająca" : "Użytkownik programu" };
    }
    var user = post.user || {};
    if (user.type === "Bot") {
      return { name: "Automat projektu" };
    }
    return { name: user.login || "Nieznany autor", role: TEAM[post.author_association] };
  }

  function postHeader(author, iso, note) {
    var header = element("header", "issue-post-header small");
    header.appendChild(element("strong", "", author.name));
    if (author.role) {
      header.appendChild(element("span", "issue-post-role", author.role));
    }
    var time = element("time", "", note || formatTime(iso));
    if (iso) {
      time.dateTime = iso;
    }
    header.appendChild(time);
    return header;
  }

  function postItem(post, isIssue) {
    var item = element("li", "issue-post");
    item.appendChild(postHeader(authorOf(post, isIssue), post.created_at));
    var body = element("div", "issue-post-body");
    body.appendChild(sanitize(post.body_html));
    dropFormFooter(body);
    if (!body.childNodes.length) {
      body.appendChild(element("p", "small", "(bez opisu)"));
    }
    item.appendChild(body);
    return item;
  }

  // Własny komentarz zaraz po wysłaniu - GitHub może pokazać go w API
  // dopiero po chwili, więc tekst wstawiamy taki, jak został wpisany.
  function ownComment(text) {
    var item = element("li", "issue-post own");
    item.appendChild(postHeader({ name: "Twój komentarz" }, null, "przed chwilą"));
    var body = element("div", "issue-post-body");
    body.appendChild(element("p", "issue-post-plain", text));
    item.appendChild(body);
    return item;
  }

  function summary(issue) {
    var meta = element("p", "issue-summary small");
    meta.appendChild(issues.badge(issue));
    var kind = issues.kind(issue);
    var text = (kind ? kind + " · " : "") + "zgłoszone " + formatTime(issue.created_at);
    meta.appendChild(element("span", "", text));
    return meta;
  }

  function setTitle(text) {
    document.querySelector("[data-issue-title]").textContent = text;
    var parts = document.title.split(" - ");
    document.title = text + " - " + parts[parts.length - 1];
  }

  function commentForm(issue, posts) {
    var form = document.querySelector("[data-comment-form]");
    var endpoint = form && form.getAttribute("data-endpoint");
    if (!endpoint) {
      return;
    }
    if (issue.locked) {
      view.appendChild(
        element("p", "small", "Dyskusja nad tym zgłoszeniem jest zamknięta.")
      );
      return;
    }
    form.querySelector("[data-comment-closed]").hidden = issue.state !== "closed";
    form.hidden = false;
    var say = T.statusLine(form.querySelector("[data-comment-status]"));
    var submit = form.querySelector("[data-comment-submit]");
    var captcha = T.captchaField(
      form.querySelector("[data-comment-captcha]"),
      form.getAttribute("data-sitekey"),
      "comment"
    );
    var url = endpoint.replace(/\/+$/, "") + "/comment";
    var id = T.requestId();

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      var invalid = T.firstInvalid(form, ["komentarz"]);
      if (invalid) {
        say(COMMENT_MESSAGES.errors.invalid, true);
        invalid.focus();
        return;
      }
      var token = captcha ? captcha.token() : "";
      if (captcha && !token) {
        say(T.CAPTCHA_WAIT, true);
        return;
      }
      var text = form.elements.komentarz.value;
      submit.disabled = true;
      say("Wysyłanie...", false);
      T.sendToWorker(
        url,
        {
          issue: issue.number,
          text: text,
          website: form.elements.strona.value,
          token: token,
          requestId: id,
        },
        COMMENT_MESSAGES
      )
        .then(function () {
          id = T.requestId();
          posts.appendChild(ownComment(text));
          form.elements.komentarz.value = "";
          say("Komentarz został dodany. Dziękujemy!", false);
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
  }

  function render(issue, comments) {
    setTitle(issue.title);
    view.textContent = "";
    view.appendChild(summary(issue));
    var posts = element("ol", "issue-posts");
    posts.setAttribute("aria-label", "Opis i komentarze");
    posts.appendChild(postItem(issue, true));
    comments.forEach(function (comment) {
      posts.appendChild(postItem(comment, false));
    });
    view.appendChild(posts);
    var github = element("p", "small issue-github");
    var link = element("a", "", "Zobacz to zgłoszenie na GitHubie");
    link.href = issue.html_url;
    github.appendChild(link);
    view.appendChild(github);
    commentForm(issue, posts);
  }

  // Komunikat zamiast zgłoszenia z odnośnikiem (np. do listy).
  function fail(text, href, label) {
    var status = element("p", "issues-fallback error", text + " ");
    var link = element("a", "", label);
    link.href = href;
    status.appendChild(link);
    status.appendChild(document.createTextNode("."));
    view.textContent = "";
    view.appendChild(status);
  }

  function show() {
    var api = view.getAttribute("data-api");
    var number = Number(new URLSearchParams(window.location.search).get("nr"));
    if (!api || !(number > 0) || Math.floor(number) !== number) {
      fail(
        "W adresie brakuje numeru zgłoszenia. Wybierz je z listy:",
        "zgloszenia.html",
        "Status zgłoszeń"
      );
      return;
    }
    var url = api + "/" + number;
    view.setAttribute("aria-busy", "true");
    view.querySelector("[data-issue-status]").textContent = "Wczytywanie zgłoszenia...";
    issues
      .fetchPages(url, 1, HTML_ACCEPT)
      .then(function (issue) {
        // API zgłoszeń obsługuje też pull requesty - te nie są zgłoszeniami.
        if (issue.pull_request) {
          throw { status: 404 };
        }
        if (!issue.comments) {
          return [issue, []];
        }
        return issues
          .fetchPages(url + "/comments?per_page=100", COMMENTS_MAX_REQUESTS, HTML_ACCEPT)
          .then(function (comments) {
            return [issue, comments];
          });
      })
      .then(function (result) {
        render(result[0], result[1]);
      })
      .catch(function (error) {
        if (error && (error.status === 404 || error.status === 410)) {
          fail("Nie ma takiego zgłoszenia. Sprawdź listę:", "zgloszenia.html", "Status zgłoszeń");
        } else {
          fail(
            "Nie udało się pobrać zgłoszenia. Spróbuj ponownie za chwilę albo zobacz je",
            view.getAttribute("data-github") + "/" + number,
            "na GitHubie"
          );
        }
      })
      .then(function () {
        view.setAttribute("aria-busy", "false");
      });
  }

  show();
})();
