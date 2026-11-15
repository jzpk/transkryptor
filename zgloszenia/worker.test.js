// Testy Workera zgłoszeń: node --test worker.test.js (w tym katalogu).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  COMMENT_FOOTER,
  DEDUP_TTL,
  MAX_BODY_BYTES,
  REPORT_FOOTER,
  commentBody,
  handle,
  issueBody,
  noMentions,
  parseComment,
  parseReport,
} from "./worker.js";

const ORIGIN = "https://transkryptorapp.pl";

function makeEnv(extra = {}) {
  return {
    GITHUB_TOKEN: "ghp_test",
    GITHUB_REPO: "owner/repo",
    TURNSTILE_SECRET: "secret",
    ALLOWED_ORIGINS: `${ORIGIN}, https://www.transkryptorapp.pl`,
    ...extra,
  };
}

// Odpowiedź Turnstile siteverify: wynik, host strony i akcja widżetu.
function turnstileResult(human, turnstile) {
  return Response.json({
    success: human,
    hostname: "transkryptorapp.pl",
    action: "report",
    ...turnstile,
  });
}

// Udaje Turnstile i GitHuba; zapisuje wywołania.
function makeFetch({ human = true, githubStatus = 201, turnstile = {} } = {}) {
  const calls = [];
  const fake = async (url, init) => {
    calls.push({ url, init });
    if (url.startsWith("https://challenges.cloudflare.com/")) {
      return turnstileResult(human, turnstile);
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
  version: "0.7.0",
  system: "Windows-11",
  area: "projekt",
  steps: "1. Otwieram projekt.\n2. Klikam Zapisz.",
  expected: "Projekt się zapisuje.",
  actual: "Nic się nie dzieje.",
  // Pole pomysłu - zgłoszenie błędu je pomija.
  problem: "Tracę zmiany.",
  website: "",
  token: "token",
};

function post(
  body,
  { origin = ORIGIN, type = "application/json", path = "/", ip = "1.2.3.4" } = {}
) {
  const headers = { Origin: origin, "Content-Type": type };
  if (ip) {
    headers["CF-Connecting-IP"] = ip;
  }
  return new Request(`https://worker.example${path}`, {
    method: "POST",
    headers,
    body: typeof body === "string" ? body : JSON.stringify(body),
  });
}

// Imitacja KV: get(klucz, "json") i put(klucz, wartość, opcje).
function makeKv() {
  const store = new Map();
  return {
    store,
    async get(key, type) {
      const value = store.get(key)?.value;
      return value === undefined ? null : type === "json" ? JSON.parse(value) : value;
    },
    async put(key, value, options) {
      store.set(key, { value, options });
    },
  };
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
  assert.deepEqual(sent.labels, ["bug", "reported by user"]);
  assert.match(sent.body, /Klikam Zapisz/);
  assert.match(sent.body, /Wersja programu: 0\.7\.0/);
});

test("idea gets the enhancement label", async () => {
  const fetchImpl = makeFetch();
  await handle(post({ ...VALID, kind: "idea" }), makeEnv(), fetchImpl);
  const github = fetchImpl.calls.find((call) => call.url.includes("api.github.com"));
  assert.deepEqual(JSON.parse(github.init.body).labels, ["enhancement", "reported by user"]);
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
  assert.equal(noMentions("cc @octocat i a@b.pl"), "cc @\u200boctocat i a@\u200bb.pl");
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
});

// Udaje Turnstile i GitHuba dla komentarzy: issue (albo jego status HTTP)
// i odpowiedź na dodanie komentarza.
function makeCommentFetch({ issue = { number: 7, locked: false }, issueStatus = 200, commentStatus = 201 } = {}) {
  const calls = [];
  const fake = async (url, init = {}) => {
    calls.push({ url, init });
    if (url.startsWith("https://challenges.cloudflare.com/")) {
      return turnstileResult(true, { action: "comment" });
    }
    if (url.endsWith("/comments")) {
      if (commentStatus !== 201) {
        return new Response("nope", { status: commentStatus });
      }
      return Response.json(
        { id: 99, html_url: "https://github.com/owner/repo/issues/7#issuecomment-99" },
        { status: 201 }
      );
    }
    if (issueStatus !== 200) {
      return new Response("nope", { status: issueStatus });
    }
    return Response.json(issue);
  };
  fake.calls = calls;
  return fake;
}

const COMMENT = {
  issue: 7,
  text: "Mnie też to się zdarza, @octocat.",
  website: "",
  token: "token",
};

function postComment(body) {
  return post(body, { path: "/comment" });
}

test("comment is added to an existing issue with the form footer", async () => {
  const fetchImpl = makeCommentFetch();
  const response = await handle(postComment(COMMENT), makeEnv(), fetchImpl);

  assert.equal(response.status, 201);
  assert.deepEqual(await response.json(), {
    id: 99,
    url: "https://github.com/owner/repo/issues/7#issuecomment-99",
  });
  assert.equal(response.headers.get("Access-Control-Allow-Origin"), ORIGIN);
  const github = fetchImpl.calls.filter((call) => call.url.includes("api.github.com"));
  assert.equal(github[0].url, "https://api.github.com/repos/owner/repo/issues/7");
  assert.equal(github[0].init.method, undefined);
  assert.equal(github[1].url, "https://api.github.com/repos/owner/repo/issues/7/comments");
  assert.equal(github[1].init.method, "POST");
  assert.equal(github[1].init.headers.Authorization, "Bearer ghp_test");
  const sent = JSON.parse(github[1].init.body);
  assert.equal(sent.body, `Mnie też to się zdarza, @\u200boctocat.\n\n---\n${COMMENT_FOOTER}\n`);
});

test("comment to a missing issue or a pull request is not found", async () => {
  for (const fetchImpl of [
    makeCommentFetch({ issueStatus: 404 }),
    makeCommentFetch({ issue: { number: 7, pull_request: {} } }),
  ]) {
    const response = await handle(postComment(COMMENT), makeEnv(), fetchImpl);
    assert.equal(response.status, 404);
    assert.deepEqual(await response.json(), { error: "not-found" });
    assert.ok(fetchImpl.calls.every((call) => !call.url.endsWith("/comments")));
  }
});

test("locked issue does not take comments", async () => {
  const fetchImpl = makeCommentFetch({ issue: { number: 7, locked: true } });
  const response = await handle(postComment(COMMENT), makeEnv(), fetchImpl);
  assert.equal(response.status, 409);
  assert.deepEqual(await response.json(), { error: "locked" });
  assert.ok(fetchImpl.calls.every((call) => !call.url.endsWith("/comments")));
});

test("GitHub failure while commenting is reported as 502", async () => {
  for (const fetchImpl of [
    makeCommentFetch({ issueStatus: 500 }),
    makeCommentFetch({ commentStatus: 403 }),
  ]) {
    const response = await handle(postComment(COMMENT), makeEnv(), fetchImpl);
    assert.equal(response.status, 502);
    assert.deepEqual(await response.json(), { error: "github" });
  }
});

test("invalid comments are rejected before Turnstile and GitHub", async () => {
  const cases = [
    { ...COMMENT, issue: "7" },
    { ...COMMENT, issue: 0 },
    { ...COMMENT, issue: 1.5 },
    { ...COMMENT, text: "za krótko" },
    { ...COMMENT, text: "x".repeat(5001) },
  ];
  for (const body of cases) {
    const fetchImpl = makeCommentFetch();
    const response = await handle(postComment(body), makeEnv(), fetchImpl);
    assert.equal(response.status, 400, JSON.stringify(body).slice(0, 80));
    assert.equal(fetchImpl.calls.length, 0);
  }
});

test("comments share the captcha, honeypot and rate limit of reports", async () => {
  const noToken = makeCommentFetch();
  const captcha = await handle(postComment({ ...COMMENT, token: "" }), makeEnv(), noToken);
  assert.equal(captcha.status, 403);
  assert.equal(noToken.calls.length, 0);

  const trapped = makeCommentFetch();
  const trap = await handle(postComment({ ...COMMENT, website: "spam" }), makeEnv(), trapped);
  assert.equal(trap.status, 201);
  assert.equal(trapped.calls.length, 0);

  const env = makeEnv({ REPORT_LIMITER: { limit: async () => ({ success: false }) } });
  const limited = await handle(postComment(COMMENT), env, makeCommentFetch());
  assert.equal(limited.status, 429);
});

test("comment fields are normalised", () => {
  assert.deepEqual(parseComment({ issue: 3, text: "  linia 1\r\nlinia 2\u0007 " }), {
    issue: 3,
    text: "linia 1\nlinia 2",
  });
  assert.match(commentBody({ text: "Treść komentarza" }), /^Treść komentarza\n\n---\n_Komentarz/);
});

test("form footers start with the text the issue page recognises", () => {
  const pattern = "(Zgłoszenie|Komentarz) z formularza na stronie programu\\.";
  const page = readFileSync(new URL("../pages/issue.js", import.meta.url), "utf-8");
  assert.ok(page.includes(`/^${pattern}/`), "FORM_FOOTER_TEXT w pages/issue.js");
  const recognised = new RegExp(`^_${pattern}`);
  assert.match(REPORT_FOOTER, recognised);
  assert.match(COMMENT_FOOTER, recognised);
  assert.ok(issueBody(parseReport(VALID)).endsWith(`\n---\n${REPORT_FOOTER}\n`));
});

test("each kind gets its labels", async () => {
  const expected = {
    bug: ["bug"],
    idea: ["enhancement"],
    question: ["question"],
    text: ["bug"],
    webpage: ["webpage"],
    unknown: ["bug"],
  };
  for (const [kind, labels] of Object.entries(expected)) {
    const fetchImpl = makeFetch();
    await handle(post({ ...VALID, kind }), makeEnv(), fetchImpl);
    const github = fetchImpl.calls.find((call) => call.url.includes("api.github.com"));
    assert.deepEqual(JSON.parse(github.init.body).labels, [...labels, "reported by user"], kind);
  }
});

test("bug fields become separate sections in order", () => {
  const body = issueBody(
    parseReport({
      ...VALID,
      area: "asr",
      steps: "1. Otwieram nagranie.\n2. Klikam Szkic.",
      expected: "Szkic się tworzy.",
      actual: "Program się zamyka.",
      frequency: "zawsze",
    })
  );
  const headings = [...body.matchAll(/^### (.+)$/gm)].map((match) => match[1]);
  assert.deepEqual(headings, [
    "Opis",
    "Czego dotyczy",
    "Kroki",
    "Oczekiwane zachowanie",
    "Faktyczne zachowanie",
    "Jak często występuje",
    "Informacje techniczne",
  ]);
  assert.match(body, /### Czego dotyczy\n\nSzkic z nagrania \(ASR\)\n/);
  assert.match(body, /### Jak często występuje\n\nZa każdym razem\n/);
  assert.match(body, /### Kroki\n\n1\. Otwieram nagranie\.\n2\. Klikam Szkic\.\n/);
});

test("empty sections are left out", () => {
  const body = issueBody(parseReport({ ...VALID, kind: "question" }));
  const headings = [...body.matchAll(/^### (.+)$/gm)].map((match) => match[1]);
  assert.deepEqual(headings, ["Opis", "Informacje techniczne"]);
});

test("fields of other kinds are ignored", () => {
  const idea = parseReport({ ...VALID, kind: "idea", steps: "krok", problem: "Brak eksportu." });
  assert.equal(idea.steps, "");
  assert.equal(idea.problem, "Brak eksportu.");
  assert.match(issueBody(idea), /### Jaki problem rozwiązuje\n\nBrak eksportu\.\n/);
  const bug = parseReport({ ...VALID, problem: "x" });
  assert.equal(bug.problem, "");
});

test("text errors are filed under texts and webpage reports skip the app version", () => {
  const text = issueBody(parseReport({ ...VALID, kind: "text", area: "asr" }));
  assert.match(text, /### Czego dotyczy\n\nTłumaczenie lub tekst w programie\n/);
  const webpage = issueBody(parseReport({ ...VALID, kind: "webpage" }));
  assert.doesNotMatch(webpage, /Wersja programu/);
  assert.match(webpage, /- System: Windows-11/);
});

test("unknown choices and too long sections are rejected", () => {
  assert.equal(parseReport({ ...VALID, area: "<script>" }), null);
  assert.equal(parseReport({ ...VALID, frequency: "często" }), null);
  assert.equal(parseReport({ ...VALID, frequency: "toString" }), null);
  assert.equal(parseReport({ ...VALID, steps: "x".repeat(3001) }), null);
  assert.equal(parseReport({ ...VALID, kind: "toString" }).kind, "bug");
});

test("mentions in sections are neutralised", () => {
  const body = issueBody(parseReport({ ...VALID, actual: "pisze do @octocat" }));
  assert.match(body, /pisze do @​octocat/);
});

test("required fields of the kind must be filled", () => {
  for (const field of ["area", "steps", "expected", "actual"]) {
    assert.equal(parseReport({ ...VALID, [field]: "" }), null, field);
    assert.equal(parseReport({ ...VALID, [field]: "  " }), null, field);
  }
  assert.equal(parseReport({ ...VALID, steps: "ab" }), null);
  assert.ok(parseReport({ ...VALID, frequency: "" }));
  assert.equal(parseReport({ ...VALID, kind: "idea", problem: "" }), null);
  for (const kind of ["question", "text", "webpage"]) {
    const bare = { kind, title: VALID.title, description: VALID.description, token: "t" };
    assert.ok(parseReport(bare), kind);
  }
});

test("report without required bug fields is rejected before GitHub", async () => {
  const fetchImpl = makeFetch();
  const response = await handle(post({ ...VALID, steps: "" }), makeEnv(), fetchImpl);
  assert.equal(response.status, 400);
  assert.equal(fetchImpl.calls.length, 0);
});

test("captcha from another site or another form is rejected", async () => {
  for (const turnstile of [
    { hostname: "evil.example" },
    { action: "comment" },
    { action: undefined },
  ]) {
    const fetchImpl = makeFetch({ turnstile });
    const response = await handle(post(VALID), makeEnv(), fetchImpl);
    assert.equal(response.status, 403, JSON.stringify(turnstile));
    assert.ok(fetchImpl.calls.every((call) => !call.url.includes("api.github.com")));
  }
  // Token z formularza zgłoszenia nie dodaje komentarza.
  const comment = await handle(postComment(COMMENT), makeEnv(), makeFetch());
  assert.equal(comment.status, 403);
});

test("request without the client address is rejected", async () => {
  const fetchImpl = makeFetch();
  const response = await handle(post(VALID, { ip: "" }), makeEnv(), fetchImpl);
  assert.equal(response.status, 400);
  assert.equal(fetchImpl.calls.length, 0);
});

test("too large body is rejected by its header and while reading", async () => {
  const big = { ...VALID, description: "x".repeat(MAX_BODY_BYTES) };
  const declared = await handle(post(big), makeEnv(), makeFetch());
  assert.equal(declared.status, 413);
  assert.deepEqual(await declared.json(), { error: "too-large" });

  // Strumień bez nagłówka Content-Length - limit liczony w trakcie odczytu.
  const chunk = new TextEncoder().encode("x".repeat(16 * 1024));
  let sent = 0;
  const body = new ReadableStream({
    pull(controller) {
      sent += chunk.byteLength;
      controller.enqueue(chunk);
    },
  });
  const request = new Request("https://worker.example/", {
    method: "POST",
    headers: { Origin: ORIGIN, "Content-Type": "application/json", "CF-Connecting-IP": "1.2.3.4" },
    body,
    duplex: "half",
  });
  const streamed = await handle(request, makeEnv(), makeFetch());
  assert.equal(streamed.status, 413);
  assert.ok(sent <= MAX_BODY_BYTES + 3 * chunk.byteLength, `wysłano ${sent} B`);
});

test("repeated submission returns the first result instead of a second issue", async () => {
  const kv = makeKv();
  const env = makeEnv({ REPORT_DEDUP: kv });
  const requestId = "0b6f6a4e-4c1d-4f63-9a51-0d0c8f7e2a11";
  const fetchImpl = makeFetch();
  const first = await handle(post({ ...VALID, requestId }), env, fetchImpl);
  const again = await handle(post({ ...VALID, requestId }), env, fetchImpl);

  assert.equal(first.status, 201);
  assert.equal(again.status, 201);
  assert.deepEqual(await again.json(), await first.json());
  const created = fetchImpl.calls.filter((call) => call.url.endsWith("/issues"));
  assert.equal(created.length, 1);
  assert.equal(kv.store.get(`report:${requestId}`).options.expirationTtl, DEDUP_TTL);

  // Inny identyfikator albo brak identyfikatora - nowe zgłoszenie.
  await handle(post({ ...VALID, requestId: requestId.replace("0b", "1b") }), env, fetchImpl);
  await handle(post(VALID), env, fetchImpl);
  assert.equal(fetchImpl.calls.filter((call) => call.url.endsWith("/issues")).length, 3);
});

test("failed submissions are not remembered", async () => {
  const kv = makeKv();
  const env = makeEnv({ REPORT_DEDUP: kv });
  const body = { ...VALID, requestId: "0b6f6a4e-4c1d-4f63-9a51-0d0c8f7e2a11" };
  await handle(post(body), env, makeFetch({ githubStatus: 500 }));
  assert.equal(kv.store.size, 0);
  const retry = await handle(post(body), env, makeFetch());
  assert.equal(retry.status, 201);
});
