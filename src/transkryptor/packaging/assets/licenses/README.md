# Teksty licencji dołączane przez wydawcę

Część kół PyPI nie zawiera pliku z tekstem swojej licencji — ma tylko
identyfikator w metadanych. Artefakt wydania musi jednak zawierać pełne
teksty, dlatego te brakujące pochodzą z tego katalogu.

| Plik                           | Pochodzenie                                                  | Dla kogo                                               |
| ------------------------------ | ------------------------------------------------------------ | ------------------------------------------------------ |
| `spdx/LGPL-3.0.txt`            | <https://www.gnu.org/licenses/lgpl-3.0.txt>                  | PySide6, PySide6_Essentials, PySide6_Addons, shiboken6 |
| `spdx/Apache-2.0.txt`          | <https://www.apache.org/licenses/LICENSE-2.0.txt>            | tokenizers, flatbuffers                                |
| `packages/ctranslate2/LICENSE` | <https://github.com/OpenNMT/CTranslate2/blob/master/LICENSE> | ctranslate2                                            |

`LGPL-3.0` włącza przez odniesienie tekst `GPL-3.0`, który leży w artefakcie
jako plik `LICENSE` (licencja aplikacji).
