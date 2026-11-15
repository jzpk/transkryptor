// Worker Cloudflare: przyjmuje zgłoszenia z formularza na stronie
// (pages/zglos.html) i zakłada z nich issue na GitHubie, a pod adresem
// /comment - komentarze do istniejących zgłoszeń z ich podglądu na stronie
// (pages/zgloszenie.html).
//
// Token GitHuba jest tylko tutaj (sekret Workera), a nie na stronie. Worker:
// - przyjmuje wyłącznie żądania ze strony projektu (ALLOWED_ORIGINS),
// - odrzuca ciało żądania większe niż MAX_BODY_BYTES, zanim je przeczyta,
// - sprawdza token Cloudflare Turnstile (ochrona przed botami): wynik musi
//   pochodzić ze strony projektu i z widżetu tego formularza (action),
// - ogranicza liczbę zgłoszeń i komentarzy z jednego adresu IP
//   (REPORT_LIMITER, opcjonalnie, wspólny limit); żądanie bez adresu IP
//   (Cloudflare zawsze go podaje) jest odrzucane,
// - po cichu odrzuca formularze z wypełnionym polem-pułapką,
// - pilnuje długości pól i wyłącza wzmianki @użytkownik w treści,
// - dla powtórzonego identyfikatora wysyłki (requestId) zwraca poprzedni
//   wynik zamiast zakładać drugi wpis (REPORT_DEDUP, opcjonalnie, KV).
//
// Konfiguracja: wrangler.toml (zmienne, limit, KV) i sekrety GITHUB_TOKEN
// oraz TURNSTILE_SECRET (npx wrangler secret put ...).
//
// GITHUB_TOKEN to fine-grained personal access token (albo token instalacji
// GitHub App) z dostępem WYŁĄCZNIE do repozytorium GITHUB_REPO i jednym
// uprawnieniem: „Issues: Read and write” („Metadata: Read-only” GitHub
// dodaje sam). Bez „Contents”, „Administration”, „Actions” ani innych
// repozytoriów - Worker jest publiczny, więc wyciek sekretu albo błąd w kodzie
// nie może dać dostępu do kodu, wydań ani ustawień. Ważność tokena najwyżej
// rok; przy wymianie: npx wrangler secret put GITHUB_TOKEN.

const GITHUB_API = "https://api.github.com";
const TURNSTILE_VERIFY_URL =
  "https://challenges.cloudflare.com/turnstile/v0/siteverify";

export const SOURCE_LABEL = "reported by user";

// Wartości pól wyboru z formularza (atrybuty value w pages/zglos.html)
// i ich opisy w issue. Pusta wartość oznacza „nie podano”.
export const CHOICES = {
  area: {
    asr: "Szkic z nagrania (ASR)",
    odtwarzacz: "Odtwarzacz nagrania",
    edytor: "Edytor i notacja",
    fonetyka: "Propozycje zapisu fonetycznego",
    kontrola: "Kontrola zapisu",
    wyszukiwanie: "Wyszukiwanie",
    eksport: "Metryczka, eksport i import DOCX",
    projekt: "Projekt i autozapis",
    instalacja: "Instalacja i aktualizacje",
    tekst: "Tłumaczenie lub tekst w programie",
    inne: "Inne",
  },
  frequency: {
    zawsze: "Za każdym razem",
    czasem: "Czasami",
    raz: "Zdarzyło się raz",
    "nie-wiem": "Nie wiem",
  },
};

// Sekcje issue z pól zależnych od rodzaju, w kolejności w treści.
// Pusta sekcja nie trafia do issue.
export const SECTIONS = [
  { field: "area", heading: "Czego dotyczy" },
  { field: "steps", heading: "Kroki" },
  { field: "expected", heading: "Oczekiwane zachowanie" },
  { field: "actual", heading: "Faktyczne zachowanie" },
  { field: "frequency", heading: "Jak często występuje" },
  { field: "problem", heading: "Jaki problem rozwiązuje" },
];

// Rodzaje zgłoszeń: etykiety issue, pola zależne od rodzaju (inne pola
// z żądania są pomijane), pola wymagane (atrybut required w
// pages/zglos.html), pola o stałej wartości i to, czy zgłoszenie dotyczy
// strony (bez wersji programu w informacjach technicznych).
export const KINDS = {
  bug: {
    labels: ["bug"],
    fields: ["area", "steps", "expected", "actual", "frequency"],
    required: ["area", "steps", "expected", "actual"],
  },
  idea: { labels: ["enhancement"], fields: ["problem"], required: ["problem"] },
  question: { labels: ["question"], fields: [] },
  text: { labels: ["bug"], fields: [], fixed: { area: "tekst" } },
  webpage: { labels: ["webpage"], fields: [], website: true },
};

// Najmniejsza długość wymaganego pola zależnego od rodzaju.
export const REQUIRED_MIN = 3;

export const LIMITS = {
  title: [5, 120],
  description: [10, 5000],
  version: [0, 40],
  system: [0, 120],
  steps: [0, 3000],
  expected: [0, 3000],
  actual: [0, 3000],
  problem: [0, 3000],
};

export const COMMENT_LIMITS = {
  text: [10, 5000],
};

export const COMMENT_PATH = "/comment";

// Stopki wpisów z formularzy. Podgląd zgłoszenia na stronie (pages/issue.js)
// rozpoznaje po nich wpisy z formularza i ukrywa stopkę - zmieniając
// początek napisu, popraw też FORM_FOOTER w pages/issue.js.
export const REPORT_FOOTER =
  "_Zgłoszenie z formularza na stronie programu. Osoba zgłaszająca może " +
  "nie mieć konta na GitHubie - odpowiedzi w tym wątku zobaczy w Statusie " +
  "zgłoszeń na stronie programu._";
export const COMMENT_FOOTER = "_Komentarz z formularza na stronie programu._";

// Całe żądanie - z zapasem na kodowanie JSON polskich znaków.
export const MAX_BODY_BYTES = 64 * 1024;

// Akcje widżetów Turnstile (parametr action w pages/site.js) - token z
// formularza zgłoszenia nie przejdzie jako token komentarza i odwrotnie.
export const TURNSTILE_ACTIONS = { report: "report", comment: "comment" };

// Jak długo powtórzona wysyłka z tym samym requestId dostaje poprzedni
// wynik (sekundy; KV wymaga co najmniej 60).
export const DEDUP_TTL = 600;
const REQUEST_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

export default {
  async fetch(request, env) {
    return handle(request, env, fetch);
  },
};

export async function handle(request, env, fetchImpl) {
  const origin = request.headers.get("Origin") || "";
  const allowed = allowedOrigins(env).includes(origin);
  const cors = allowed ? corsHeaders(origin) : {};

  if (request.method === "OPTIONS") {
    return new Response(null, { status: allowed ? 204 : 403, headers: cors });
  }
  if (request.method !== "POST") {
    return json({ error: "method" }, 405, { ...cors, Allow: "POST, OPTIONS" });
  }
  if (!allowed) {
    return json({ error: "origin" }, 403, cors);
  }
  if (!env.GITHUB_TOKEN || !env.GITHUB_REPO || !env.TURNSTILE_SECRET) {
    console.error("Brak konfiguracji: GITHUB_TOKEN, GITHUB_REPO albo TURNSTILE_SECRET.");
    return json({ error: "config" }, 500, cors);
  }

  const ip = request.headers.get("CF-Connecting-IP") || "";
  if (!ip) {
    return json({ error: "invalid" }, 400, cors);
  }
  if (env.REPORT_LIMITER) {
    const { success } = await env.REPORT_LIMITER.limit({ key: ip });
    if (!success) {
      return json({ error: "too-many" }, 429, cors);
    }
  }

  const data = await readJson(request);
  if (data === TOO_LARGE) {
    return json({ error: "too-large" }, 413, cors);
  }
  if (!data) {
    return json({ error: "invalid" }, 400, cors);
  }
  // Pole-pułapka: udajemy sukces, żeby bot nie próbował dalej.
  if (typeof data.website === "string" && data.website.trim() !== "") {
    return json({ ok: true }, 201, cors);
  }
  const comment = new URL(request.url).pathname.endsWith(COMMENT_PATH);
  const parsed = comment ? parseComment(data) : parseReport(data);
  if (!parsed) {
    return json({ error: "invalid" }, 400, cors);
  }

  const expected = {
    hostnames: allowedOrigins(env).map((allowedOrigin) => new URL(allowedOrigin).hostname),
    action: comment ? TURNSTILE_ACTIONS.comment : TURNSTILE_ACTIONS.report,
  };
  const human = await verifyTurnstile(env.TURNSTILE_SECRET, data.token, ip, expected, fetchImpl);
  if (!human) {
    return json({ error: "captcha" }, 403, cors);
  }

  const dedupKey = dedupKeyOf(env, expected.action, data.requestId);
  const previous = dedupKey && (await env.REPORT_DEDUP.get(dedupKey, "json"));
  if (previous) {
    return json(previous.body, previous.status, cors);
  }
  const result = comment
    ? await addComment(env, parsed, fetchImpl)
    : await createIssue(env, parsed, fetchImpl);
  if (dedupKey && result.status === 201) {
    await env.REPORT_DEDUP.put(dedupKey, JSON.stringify(result), {
      expirationTtl: DEDUP_TTL,
    });
  }
  return json(result.body, result.status, cors);
}

// Klucz KV dla identyfikatora wysyłki z formularza (crypto.randomUUID());
// null bez KV albo bez poprawnego identyfikatora.
function dedupKeyOf(env, action, requestId) {
  if (!env.REPORT_DEDUP || typeof requestId !== "string" || !REQUEST_ID.test(requestId)) {
    return null;
  }
  return `${action}:${requestId}`;
}

export function allowedOrigins(env) {
  return (env.ALLOWED_ORIGINS || "")
    .split(",")
    .map((origin) => origin.trim())
    .filter(Boolean);
}

function corsHeaders(origin) {
  return {
    "Access-Control-Allow-Origin": origin,
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
    Vary: "Origin",
  };
}

function json(body, status, headers = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", ...headers },
  });
}

const TOO_LARGE = Symbol("too-large");

// Ciało żądania jako JSON; TOO_LARGE, gdy przekracza MAX_BODY_BYTES (po
// nagłówku Content-Length od razu, a bez niego - po przeczytaniu limitu),
// null, gdy to nie jest obiekt JSON.
async function readJson(request) {
  const type = request.headers.get("Content-Type") || "";
  if (!type.startsWith("application/json")) {
    return null;
  }
  if (Number(request.headers.get("Content-Length")) > MAX_BODY_BYTES) {
    return TOO_LARGE;
  }
  const text = await readLimited(request, MAX_BODY_BYTES);
  if (text === null) {
    return TOO_LARGE;
  }
  try {
    const data = JSON.parse(text);
    return data && typeof data === "object" && !Array.isArray(data) ? data : null;
  } catch {
    return null;
  }
}

// Tekst ciała żądania czytany porcjami; null po przekroczeniu limitu
// (reszta nie jest czytana).
async function readLimited(request, limit) {
  if (!request.body) {
    return "";
  }
  const reader = request.body.getReader();
  const chunks = [];
  let size = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }
    size += value.byteLength;
    if (size > limit) {
      await reader.cancel();
      return null;
    }
    chunks.push(value);
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return new TextDecoder().decode(bytes);
}

// Usuwa znaki sterujące (poza nowym wierszem i tabulatorem) i ujednolica
// końce wierszy.
function clean(value) {
  if (typeof value !== "string") {
    return "";
  }
  return value
    .replace(/\r\n?/g, "\n")
    .replace(/[\u0000-\u0008\u000b-\u001f\u007f]/g, "")
    .trim();
}

function oneLine(value) {
  return clean(value).replace(/\s+/g, " ");
}

// Zwraca poprawione zgłoszenie albo null, gdy pola nie mieszczą się
// w limitach albo pole wyboru ma nieznaną wartość. Pola, których rodzaj
// zgłoszenia nie ma, są puste.
export function parseReport(data) {
  const kind = Object.hasOwn(KINDS, data.kind) ? data.kind : "bug";
  const spec = KINDS[kind];
  const report = {
    kind,
    title: oneLine(data.title),
    description: clean(data.description),
    version: spec.website ? "" : oneLine(data.version),
    system: oneLine(data.system),
  };
  for (const { field } of SECTIONS) {
    report[field] = spec.fields.includes(field) ? clean(data[field]) : "";
  }
  Object.assign(report, spec.fixed);
  for (const [field, [min, max]] of Object.entries(LIMITS)) {
    const length = [...report[field]].length;
    if (length < min || length > max) {
      return null;
    }
  }
  for (const field of spec.required || []) {
    if ([...report[field]].length < REQUIRED_MIN) {
      return null;
    }
  }
  for (const [field, choices] of Object.entries(CHOICES)) {
    if (report[field] !== "" && !Object.hasOwn(choices, report[field])) {
      return null;
    }
  }
  return report;
}

// Zwraca poprawiony komentarz ({ issue, text }) albo null.
export function parseComment(data) {
  const issue = data.issue;
  if (!Number.isInteger(issue) || issue < 1 || issue > 1e9) {
    return null;
  }
  const comment = { issue, text: clean(data.text) };
  for (const [field, [min, max]] of Object.entries(COMMENT_LIMITS)) {
    const length = [...comment[field]].length;
    if (length < min || length > max) {
      return null;
    }
  }
  return comment;
}

// Wzmianka @nazwa w issue powiadamia tę osobę na GitHubie - znak o zerowej
// szerokości po @ wyłącza powiadomienie, a tekst wygląda tak samo.
export function noMentions(text) {
  return text.replace(/@(?=[A-Za-z0-9])/g, "@\u200b");
}

function sectionText(report, field) {
  const value = report[field];
  return Object.hasOwn(CHOICES, field) ? CHOICES[field][value] || "" : value;
}

export function issueBody(report) {
  const sections = [["Opis", report.description]];
  for (const { field, heading } of SECTIONS) {
    const text = sectionText(report, field);
    if (text) {
      sections.push([heading, text]);
    }
  }
  const tech = [`- System: ${noMentions(report.system) || "nie podano"}`];
  if (!KINDS[report.kind].website) {
    tech.unshift(`- Wersja programu: ${noMentions(report.version) || "nie podano"}`);
  }
  sections.push(["Informacje techniczne", tech.join("\n")]);
  return [
    ...sections.flatMap(([heading, text]) => [`### ${heading}`, "", noMentions(text), ""]),
    "---",
    REPORT_FOOTER,
    "",
  ].join("\n");
}

export function commentBody(comment) {
  return [noMentions(comment.text), "", "---", COMMENT_FOOTER, ""].join("\n");
}

// Token musi być ważny, wydany na stronie projektu (hostname) i przez
// widżet tego formularza (action) - inaczej przeszedłby token z innej
// strony z tym samym kluczem witryny albo z drugiego formularza.
async function verifyTurnstile(secret, token, ip, expected, fetchImpl) {
  if (typeof token !== "string" || token === "" || token.length > 2048) {
    return false;
  }
  const form = new FormData();
  form.append("secret", secret);
  form.append("response", token);
  if (ip) {
    form.append("remoteip", ip);
  }
  try {
    const response = await fetchImpl(TURNSTILE_VERIFY_URL, {
      method: "POST",
      body: form,
    });
    const result = await response.json();
    return (
      result.success === true &&
      expected.hostnames.includes(result.hostname) &&
      result.action === expected.action
    );
  } catch (error) {
    console.error(`Turnstile niedostępny: ${error}`);
    return false;
  }
}

function github(env, path, fetchImpl, init = {}) {
  return fetchImpl(`${GITHUB_API}/repos/${env.GITHUB_REPO}${path}`, {
    ...init,
    headers: {
      Accept: "application/vnd.github+json",
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      "Content-Type": "application/json",
      "User-Agent": "transkryptor-zgloszenia",
      "X-GitHub-Api-Version": "2022-11-28",
    },
  });
}

const GITHUB_FAILED = { status: 502, body: { error: "github" } };

async function createIssue(env, report, fetchImpl) {
  const labels = [...KINDS[report.kind].labels, SOURCE_LABEL];
  try {
    const response = await github(env, "/issues", fetchImpl, {
      method: "POST",
      body: JSON.stringify({
        title: noMentions(report.title),
        body: issueBody(report),
        labels,
      }),
    });
    if (response.status !== 201) {
      console.error(`GitHub: ${response.status} ${await response.text()}`);
      return GITHUB_FAILED;
    }
    const issue = await response.json();
    return { status: 201, body: { number: issue.number, url: issue.html_url } };
  } catch (error) {
    console.error(`GitHub niedostępny: ${error}`);
    return GITHUB_FAILED;
  }
}

// Komentarz trafia tylko do istniejącego, niezablokowanego zgłoszenia
// (nie do pull requesta). Konto, do którego należy token, może mieć prawa
// pisania w zablokowanych wątkach (np. właściciel repozytorium) - dlatego
// blokadę sprawdzamy sami, niezależnie od zakresu tokena.
async function addComment(env, comment, fetchImpl) {
  try {
    const found = await github(env, `/issues/${comment.issue}`, fetchImpl);
    if (found.status === 404 || found.status === 410) {
      return { status: 404, body: { error: "not-found" } };
    }
    if (found.status !== 200) {
      console.error(`GitHub: ${found.status} ${await found.text()}`);
      return GITHUB_FAILED;
    }
    const issue = await found.json();
    if (issue.pull_request) {
      return { status: 404, body: { error: "not-found" } };
    }
    if (issue.locked) {
      return { status: 409, body: { error: "locked" } };
    }
    const response = await github(env, `/issues/${comment.issue}/comments`, fetchImpl, {
      method: "POST",
      body: JSON.stringify({ body: commentBody(comment) }),
    });
    if (response.status !== 201) {
      console.error(`GitHub: ${response.status} ${await response.text()}`);
      return GITHUB_FAILED;
    }
    const created = await response.json();
    return { status: 201, body: { id: created.id, url: created.html_url } };
  } catch (error) {
    console.error(`GitHub niedostępny: ${error}`);
    return GITHUB_FAILED;
  }
}
