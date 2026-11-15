"""Content-Security-Policy strony projektu.

Strona pokazuje treść zgłoszeń z GitHuba (HTML z API przechodzi przez
sanitizer w ``pages/issue.js``). CSP to druga linia obrony: gdyby sanitizer
przepuścił skrypt, przeglądarka i tak go nie uruchomi, a obrazki spoza
GitHuba nie zostaną pobrane (piksel śledzący odwiedzających).

Polityka trafia do ``<meta http-equiv>`` zaraz po ``<meta charset>`` każdej
strony - GitHub Pages nie pozwala ustawić nagłówków. Dozwolone są tylko:

- skrypty i style z tej strony, skrypt i ramka Cloudflare Turnstile;
  style wbudowane (``<style>`` z literami tła) są dozwolone, bo nie
  uruchamiają kodu;
- połączenia z API GitHuba i z Workerem zgłoszeń;
- obrazki z tej strony i z hostów GitHuba, na które GitHub przepisuje
  obrazki ze zgłoszeń (``camo``, ``user-images``, ``private-user-images``,
  ``github.com/user-attachments``).

Blok JSON-LD (``<script type="application/ld+json">``) nie jest
uruchamiany, więc nie wymaga ``unsafe-inline``.
"""

from __future__ import annotations

import html
from urllib.parse import urlsplit

GITHUB_API_ORIGIN = "https://api.github.com"
TURNSTILE_ORIGIN = "https://challenges.cloudflare.com"
# Hosty obrazków w treści zgłoszeń - te same co IMAGE_HOSTS w pages/issue.js.
IMAGE_SOURCES = ("https://github.com", "https://*.githubusercontent.com")
_CHARSET = '<meta charset="utf-8" />'


def origin(url: str) -> str:
    """``https://host[:port]`` adresu (bez ścieżki); pusty adres → ``""``."""
    if not url:
        return ""
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def content_security_policy(report_endpoint: str = "") -> str:
    """Polityka dla wszystkich stron; ``report_endpoint`` - adres Workera."""
    connect = ["'self'", GITHUB_API_ORIGIN]
    if worker := origin(report_endpoint):
        connect.append(worker)
    directives = {
        "default-src": ["'self'"],
        "script-src": ["'self'", TURNSTILE_ORIGIN],
        "style-src": ["'self'", "'unsafe-inline'"],
        "img-src": ["'self'", *IMAGE_SOURCES],
        "connect-src": connect,
        "frame-src": [TURNSTILE_ORIGIN],
        "object-src": ["'none'"],
        "base-uri": ["'none'"],
        "form-action": ["'self'"],
    }
    return "; ".join(
        f"{name} {' '.join(values)}" for name, values in directives.items()
    )


def add_csp(page: str, policy: str) -> str:
    """Wstawia politykę zaraz po ``<meta charset>`` - przed skryptami."""
    if _CHARSET not in page:
        raise ValueError("strona nie ma <meta charset>, po którym stoi CSP")
    meta = (
        '<meta http-equiv="Content-Security-Policy" '
        f'content="{html.escape(policy)}" />'
    )
    return page.replace(_CHARSET, f"{_CHARSET}\n    {meta}", 1)
