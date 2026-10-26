// Testy Workera zgłoszeń: node --test worker.test.js (w tym katalogu).
import assert from "node:assert/strict";
import { test } from "node:test";

import { handle, issueBody, noMentions, parseReport } from "./worker.js";

const ORIGIN = "https://transkryptorapp.pl";

function makeEnv(extra = {}) {
  const stored = new Map();
  return {
    GITHUB_TOKEN: "ghp_test",
    GITHUB_REPO: "owner/repo",
    TURNSTILE_SECRET: "secret",
    ALLOWED_ORIGINS: `${ORIGIN}, https://www.transkryptorapp.pl`,
    CONTACTS: {
      stored,
      async put(key, value, options) {
        stored.set(key, { value: JSON.parse(value), options });
      },
    },
    ...extra,
  };
}

// Udaje Turnstile i GitHuba; zapisuje wywołania.
function makeFetch({ human = true, githubStatus = 201 } = {}) {
  const calls = [];
  const fake = async (url, init) => {
    calls.push({ url, init });
    if (url.startsWith("https://challenges.cloudflare.com/")) {
      return Response.json({ success: human });
    }
    if (githubStatus !== 201) {
      return new Response("nope", { status: githubStatus });
    }
    return Response.json(
      { number: 42, html_url: "https://github.com/owner/repo/issues/42" },
      { status: 201 }
    );
  };
  fake.calls = calls;
  return fake;
}

const VALID = {
  kind: "bug",
  title: "Nie zapisuje projektu",
  description: "Klikam Zapisz i nic się nie dzieje.",
  email: "",
  version: "0.7.0",
  system: "Windows-11",
  website: "",
  token: "token",
};

function post(body, { origin = ORIGIN, type = "application/json" } = {}) {
  return new Request("https://worker.example/", {
    method: "POST",
    headers: { Origin: origin, "Content-Type": type, "CF-Connecting-IP": "1.2.3.4" },
    body: typeof body === "string" ? body : JSON.stringify(body),
  });
}

test("valid report creates a labelled issue", async () => {
  const fetchImpl = makeFetch();
  const response = await handle(post(VALID), makeEnv(), fetchImpl);

  assert.equal(response.status, 201);
  assert.deepEqual(await response.json(), {
    number: 42,
    url: "https://github.com/owner/repo/issues/42",
  });
  assert.equal(response.headers.get("Access-Control-Allow-Origin"), ORIGIN);
  const github = fetchImpl.calls.find((call) => call.url.includes("api.github.com"));
  assert.equal(github.url, "https://api.github.com/repos/owner/repo/issues");
  assert.equal(github.init.headers.Authorization, "Bearer ghp_test");
  const sent = JSON.parse(github.init.body);
  assert.equal(sent.title, "Nie zapisuje projektu");
  assert.deepEqual(sent.labels, ["bug", "od-uzytkownika"]);
  assert.match(sent.body, /Klikam Zapisz/);
  assert.match(sent.body, /Wersja programu: 0\.7\.0/);
});

test("idea gets the enhancement label", async () => {
  const fetchImpl = makeFetch();
  await handle(post({ ...VALID, kind: "idea" }), makeEnv(), fetchImpl);
  const github = fetchImpl.calls.find((call) => call.url.includes("api.github.com"));
  assert.deepEqual(JSON.parse(github.init.body).labels, ["enhancement", "od-uzytkownika"]);
});

test("email is stored privately and never sent to GitHub", async () => {
  const env = makeEnv();
  const fetchImpl = makeFetch();
  const response = await handle(post({ ...VALID, email: "ala@example.com" }), env, fetchImpl);

  assert.equal(response.status, 201);
  const github = fetchImpl.calls.find((call) => call.url.includes("api.github.com"));
  assert.doesNotMatch(github.init.body, /ala@/);
  const contact = env.CONTACTS.stored.get("issue-42");
  assert.equal(contact.value.email, "ala@example.com");
  assert.ok(contact.options.expirationTtl > 0);
});

test("preflight is answered only for the project site", async () => {
  const preflight = (origin) =>
    new Request("https://worker.example/", { method: "OPTIONS", headers: { Origin: origin } });

  const ok = await handle(preflight(ORIGIN), makeEnv(), makeFetch());
  assert.equal(ok.status, 204);
  assert.equal(ok.headers.get("Access-Control-Allow-Origin"), ORIGIN);

  const other = await handle(preflight("https://evil.example"), makeEnv(), makeFetch());
  assert.equal(other.status, 403);
  assert.equal(other.headers.get("Access-Control-Allow-Origin"), null);
});

test("other origins cannot create issues", async () => {
  const fetchImpl = makeFetch();
  const response = await handle(post(VALID, { origin: "https://evil.example" }), makeEnv(), fetchImpl);
  assert.equal(response.status, 403);
  assert.equal(fetchImpl.calls.length, 0);
});

test("failed captcha is rejected before GitHub is called", async () => {
  const fetchImpl = makeFetch({ human: false });
  const response = await handle(post(VALID), makeEnv(), fetchImpl);
  assert.equal(response.status, 403);
  assert.deepEqual(await response.json(), { error: "captcha" });
  assert.ok(fetchImpl.calls.every((call) => !call.url.includes("api.github.com")));
});

test("missing captcha token is rejected without asking Turnstile", async () => {
  const fetchImpl = makeFetch();
  const response = await handle(post({ ...VALID, token: "" }), makeEnv(), fetchImpl);
  assert.equal(response.status, 403);
  assert.equal(fetchImpl.calls.length, 0);
});

test("honeypot pretends success and creates nothing", async () => {
  const fetchImpl = makeFetch();
  const response = await handle(post({ ...VALID, website: "spam" }), makeEnv(), fetchImpl);
  assert.equal(response.status, 201);
  assert.equal(fetchImpl.calls.length, 0);
});

test("rate limit returns 429", async () => {
  const env = makeEnv({ REPORT_LIMITER: { limit: async () => ({ success: false }) } });
  const fetchImpl = makeFetch();
  const response = await handle(post(VALID), env, fetchImpl);
  assert.equal(response.status, 429);
  assert.deepEqual(await response.json(), { error: "too-many" });
  assert.equal(fetchImpl.calls.length, 0);
});

test("invalid input is rejected", async () => {
  const cases = [
    { ...VALID, title: "abc" },
    { ...VALID, description: "x".repeat(5001) },
    { ...VALID, email: "nie-adres" },
    { ...VALID, title: 123 },
  ];
  for (const body of cases) {
    const response = await handle(post(body), makeEnv(), makeFetch());
    assert.equal(response.status, 400, JSON.stringify(body).slice(0, 80));
  }
  const notJson = await handle(post("{", {}), makeEnv(), makeFetch());
  assert.equal(notJson.status, 400);
  const wrongType = await handle(post(VALID, { type: "text/plain" }), makeEnv(), makeFetch());
  assert.equal(wrongType.status, 400);
});

test("GitHub failure is reported as 502", async () => {
  const response = await handle(post(VALID), makeEnv(), makeFetch({ githubStatus: 401 }));
  assert.equal(response.status, 502);
  assert.deepEqual(await response.json(), { error: "github" });
});

test("missing configuration is a server error, not a silent drop", async () => {
  const response = await handle(post(VALID), makeEnv({ GITHUB_TOKEN: "" }), makeFetch());
  assert.equal(response.status, 500);
});

test("other methods are not allowed", async () => {
  const request = new Request("https://worker.example/", { headers: { Origin: ORIGIN } });
  const response = await handle(request, makeEnv(), makeFetch());
  assert.equal(response.status, 405);
});

test("mentions are neutralised and fields are normalised", () => {
  assert.equal(noMentions("cc @octocat i a@b.pl"), "cc @​octocat i a@​b.pl");
  const report = parseReport({
    ...VALID,
    title: "  Tytuł\nw dwóch\twierszach  ",
    description: "linia 1\r\nlinia 2\u0007",
  });
  assert.equal(report.title, "Tytuł w dwóch wierszach");
  assert.equal(report.description, "linia 1\nlinia 2");
  assert.equal(report.kind, "bug");
});

test("issue body marks missing technical details", () => {
  const body = issueBody(parseReport({ ...VALID, version: "", system: "" }));
  assert.match(body, /Wersja programu: nie podano/);
  assert.match(body, /System: nie podano/);
  assert.doesNotMatch(body, /adres e-mail/);
});
