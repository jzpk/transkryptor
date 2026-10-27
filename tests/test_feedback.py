"""Adres formularza zgłoszeń otwieranego z programu."""

import platform
from urllib.parse import parse_qs, urlsplit

from transkryptor import __version__
from transkryptor.feedback import REPORT_FORM_URL, report_form_url
from transkryptor.packaging import site


def test_form_url_carries_version_and_system() -> None:
    url = urlsplit(report_form_url())

    assert f"{url.scheme}://{url.netloc}{url.path}" == REPORT_FORM_URL
    assert parse_qs(url.query) == {
        "wersja": [__version__],
        "system": [platform.platform()],
    }


def test_form_is_a_page_of_the_project_site() -> None:
    assert f"{site.SITE_URL}/zglos.html" == REPORT_FORM_URL
    assert "zglos.html" in site.TEMPLATE_FILES
