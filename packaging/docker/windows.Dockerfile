# Środowisko budowania instalatora Windows na Linuxie.
#
# PyInstaller nie buduje krzyżowo, więc uruchamiamy Windowsowego Pythona
# pod Wine: PyInstaller widzi sys.platform == "win32", zbiera biblioteki
# z kół win_amd64, a Inno Setup (ISCC.exe) kompiluje instalator. Wynik jest
# tym samym plikiem, który powstałby na Windows.
#
# Wymagane jest Wine 10+: numpy 2.x woła ucrtbase.crealf, którego Wine 9
# nie implementuje (proces PyInstallera kończył się wtedy awarią).
# Bazowy obraz dostarcza Wine 11; jego własny Python (3.14) jest nieużywany —
# aplikacja wymaga 3.12, więc instalujemy go obok z oficjalnej paczki NuGet
# python.org (zwykłe archiwum, bez instalatora).
#
# Kontekst budowania: requirements-windows.txt wyeksportowany z uv.lock
# i katalog icu-stub/ (przygotowuje je scripts/build-installers.sh). Kod jest
# montowany przy uruchomieniu.

# Zastępcza icuuc.dll dla importu QtCore pod Wine — opis w icuuc_stub.c.
FROM debian:bookworm-slim AS icu-stub
RUN apt-get update \
    && apt-get install --no-install-recommends -y gcc-mingw-w64-x86-64 \
    && rm -rf /var/lib/apt/lists/*
COPY icu-stub/icuuc_stub.c /tmp/icuuc_stub.c
RUN x86_64-w64-mingw32-gcc -O2 -shared -s -static-libgcc \
        -o /tmp/icuuc.dll /tmp/icuuc_stub.c

FROM tobix/pywine@sha256:b053219cba558a12a8a3df2401a653b2ab2fced6833accd1e5d72399d7da1ad3

# Ostatnie wydanie binarne linii 3.12.
ARG PYTHON_VERSION=3.12.10
ARG PYTHON_NUPKG_SHA256=0eb85c2dfccccf1b17352de4c397f69194035b7d37149eacc16f1147d93de3b8
ENV PYTHON312='C:\Python312\python.exe'
RUN set -eux; \
    curl -fsSL -o /tmp/python.nupkg \
        "https://api.nuget.org/v3-flatcontainer/python/${PYTHON_VERSION}/python.${PYTHON_VERSION}.nupkg"; \
    echo "${PYTHON_NUPKG_SHA256}  /tmp/python.nupkg" | sha256sum --check --strict; \
    unzip -q /tmp/python.nupkg 'tools/*' -d /tmp/python; \
    mv /tmp/python/tools "${WINEPREFIX}/drive_c/Python312"; \
    rm -rf /tmp/python /tmp/python.nupkg; \
    wine "${PYTHON312}" -m ensurepip --default-pip; \
    wine "${PYTHON312}" --version; \
    wineserver -w

# Wersja i suma takie same jak w .github/workflows/release.yml.
ARG INNO_SETUP_VERSION=6.7.3
ARG INNO_SETUP_SHA256=9c73c3bae7ed48d44112a0f48e66742c00090bdb5bef71d9d3c056c66e97b732
RUN set -eux; \
    tag="is-$(echo "${INNO_SETUP_VERSION}" | tr . _)"; \
    curl -fsSL -o /tmp/innosetup.exe \
        "https://github.com/jrsoftware/issrc/releases/download/${tag}/innosetup-${INNO_SETUP_VERSION}.exe"; \
    echo "${INNO_SETUP_SHA256}  /tmp/innosetup.exe" | sha256sum --check --strict; \
    xvfb-run -a wine /tmp/innosetup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- /ALLUSERS; \
    wineserver -w; \
    rm /tmp/innosetup.exe; \
    test -f "${WINEPREFIX}/drive_c/Program Files (x86)/Inno Setup 6/ISCC.exe"; \
    test -f "${WINEPREFIX}/drive_c/Program Files (x86)/Inno Setup 6/Languages/Polish.isl"

# Zależności z uv.lock (z hashami) w osobnej warstwie.
COPY requirements-windows.txt /tmp/requirements-windows.txt
RUN wine "${PYTHON312}" -m pip install --no-cache-dir --no-warn-script-location \
        -r 'Z:\tmp\requirements-windows.txt' \
    && wineserver -w

# System32: PyInstaller nie dołączy jej do artefaktu (biblioteka systemowa).
COPY --from=icu-stub /tmp/icuuc.dll /opt/wineprefix/drive_c/windows/system32/icuuc.dll
# Bez działającego importu QtCore instalator powstałby bez wtyczek Qt.
RUN wine "${PYTHON312}" -c "import PySide6.QtCore as q; print('QtCore', q.qVersion())" \
    && wineserver -w

WORKDIR /src
