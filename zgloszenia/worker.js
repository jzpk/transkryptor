// Worker Cloudflare: przyjmuje zgłoszenia z formularza na stronie
// (pages/zglos.html) i zakłada z nich issue na GitHubie.
//
// Token GitHuba jest tylko tutaj (sekret Workera), a nie na stronie. Worker:
// - przyjmuje wyłącznie żądania ze strony projektu (ALLOWED_ORIGINS),
// - sprawdza token Cloudflare Turnstile (ochrona przed botami),
// - ogranicza liczbę zgłoszeń z jednego adresu IP (REPORT_LIMITER, opcjonalnie),
// - po cichu odrzuca formularze z wypełnionym polem-pułapką,
// - pilnuje długości pól i wyłącza wzmianki @użytkownik w treści,
// - adres e-mail zapisuje prywatnie w KV (CONTACTS) pod numerem zgłoszenia -
//   nigdy nie trafia do publicznego issue.
//
// Konfiguracja: wrangler.toml (zmienne, KV, limit) i sekrety GITHUB_TOKEN
// oraz TURNSTILE_SECRET (npx wrangler secret put ...).

const GITHUB_API = "https://api.github.com";
const TURNSTILE_VERIFY_URL =
  "https://challenges.cloudflare.com/turnstile/v0/siteverify";

export const LABELS = {
  bug: "bug",
  idea: "enhancement",
  source: "od-uzytkownika",
};

export const LIMITS = {
  title: [5, 120],
  description: [10, 5000],
  email: [0, 200],
  version: [0, 40],
  system: [0, 120],
};

// Całe żądanie - z zapasem na kodowanie JSON polskich znaków.
const MAX_BODY_BYTES = 32 * 1024;
// Adres e-mail do odpowiedzi trzymamy rok, potem KV usuwa go sam.
const CONTACT_TTL_SECONDS = 365 * 24 * 60 * 60;
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

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
  if (env.REPORT_LIMITER) {
    const { success } = await env.REPORT_LIMITER.limit({ key: ip || "brak-ip" });
    if (!success) {
      return json({ error: "too-many" }, 429, cors);
    }
  }

  const data = await readJson(request);
  if (!data) {
    return json({ error: "invalid" }, 400, cors);
  }
  // Pole-pułapka: udajemy sukces, żeby bot nie próbował dalej.
  if (typeof data.website === "string" && data.website.trim() !== "") {
    return json({ ok: true }, 201, cors);
  }
  const report = parseReport(data);
  if (!report) {
    return json({ error: "invalid" }, 400, cors);
  }

  const human = await verifyTurnstile(env.TURNSTILE_SECRET, data.token, ip, fetchImpl);
  if (!human) {
    return json({ error: "captcha" }, 403, cors);
  }

  const issue = await createIssue(env, report, fetchImpl);
  if (!issue) {
    return json({ error: "github" }, 502, cors);
  }
  if (report.email && env.CONTACTS) {
    try {
      await env.CONTACTS.put(
        `issue-${issue.number}`,
        JSON.stringify({ email: report.email, created: new Date().toISOString() }),
        { expirationTtl: CONTACT_TTL_SECONDS }
      );
    } catch (error) {
      // Zgłoszenie już jest - brak adresu do odpowiedzi nie powinien go cofać.
      console.error(`Nie zapisano adresu e-mail dla #${issue.number}: ${error}`);
    }
  }
  return json({ number: issue.number, url: issue.html_url }, 201, cors);
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

async function readJson(request) {
  const type = request.headers.get("Content-Type") || "";
  if (!type.startsWith("application/json")) {
    return null;
  }
  const text = await request.text();
  if (new TextEncoder().encode(text).length > MAX_BODY_BYTES) {
    return null;
  }
  try {
    const data = JSON.parse(text);
    return data && typeof data === "object" && !Array.isArray(data) ? data : null;
  } catch {
    return null;
  }
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

// Zwraca poprawione zgłoszenie albo null, gdy pola nie mieszczą się w limitach.
export function parseReport(data) {
  const report = {
    kind: data.kind === "idea" ? "idea" : "bug",
    title: oneLine(data.title),
    description: clean(data.description),
    email: oneLine(data.email),
    version: oneLine(data.version),
    system: oneLine(data.system),
  };
  for (const [field, [min, max]] of Object.entries(LIMITS)) {
    const length = [...report[field]].length;
    if (length < min || length > max) {
      return null;
    }
  }
  if (report.email && !EMAIL_RE.test(report.email)) {
    return null;
  }
  return report;
}

// Wzmianka @nazwa w issue powiadamia tę osobę na GitHubie - znak o zerowej
// szerokości po @ wyłącza powiadomienie, a tekst wygląda tak samo.
export function noMentions(text) {
  return text.replace(/@(?=[A-Za-z0-9])/g, "@​");
}

export function issueBody(report) {
  const tech = [
    `- Wersja programu: ${noMentions(report.version) || "nie podano"}`,
    `- System: ${noMentions(report.system) || "nie podano"}`,
  ];
  const footer = [
    "Zgłoszenie z formularza na stronie programu. Osoba zgłaszająca może " +
      "nie mieć konta na GitHubie i nie zobaczy odpowiedzi w tym wątku.",
  ];
  if (report.email) {
    footer.push(
      `Podano adres e-mail do kontaktu - jest zapisany prywatnie ` +
        `(KV \`CONTACTS\`, klucz \`issue-<numer>\`).`
    );
  }
  return [
    "### Opis",
    "",
    noMentions(report.description),
    "",
    "### Informacje techniczne",
    "",
    ...tech,
    "",
    "---",
    `_${footer.join(" ")}_`,
    "",
  ].join("\n");
}

async function verifyTurnstile(secret, token, ip, fetchImpl) {
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
    return result.success === true;
  } catch (error) {
    console.error(`Turnstile niedostępny: ${error}`);
    return false;
  }
}

async function createIssue(env, report, fetchImpl) {
  const labels = [LABELS[report.kind], LABELS.source];
  try {
    const response = await fetchImpl(`${GITHUB_API}/repos/${env.GITHUB_REPO}/issues`, {
      method: "POST",
      headers: {
        Accept: "application/vnd.github+json",
        Authorization: `Bearer ${env.GITHUB_TOKEN}`,
        "Content-Type": "application/json",
        "User-Agent": "transkryptor-zgloszenia",
        "X-GitHub-Api-Version": "2022-11-28",
      },
      body: JSON.stringify({
        title: noMentions(report.title),
        body: issueBody(report),
        labels,
      }),
    });
    if (response.status !== 201) {
      console.error(`GitHub: ${response.status} ${await response.text()}`);
      return null;
    }
    const issue = await response.json();
    return { number: issue.number, html_url: issue.html_url };
  } catch (error) {
    console.error(`GitHub niedostępny: ${error}`);
    return null;
  }
}
