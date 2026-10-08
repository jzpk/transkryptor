/*
 * Zastępcza icuuc.dll — TYLKO dla obrazu budowania pod Wine.
 *
 * Qt6Core.dll z PySide6 6.7+ linkuje się z systemowym ICU Windows
 * (C:\Windows\System32\icuuc.dll, obecne od Windows 10 1903). Wine tej
 * biblioteki nie dostarcza, więc import QtCore — którego PyInstaller
 * potrzebuje, by odczytać ścieżki wtyczek Qt — kończył się błędem i
 * instalator powstawał bez wtyczek Qt.
 *
 * Qt importuje z icuuc.dll wyłącznie konwertery ucnv_* (obsługa starszych
 * kodowań w QStringConverter). Ta atrapa udaje ICU bez żadnego konwertera:
 * ucnv_open zawsze zgłasza błąd, a lista kodowań jest pusta. Qt traktuje to
 * jak brak danego kodowania.
 *
 * Plik leży w System32 prefiksu Wine, więc PyInstaller uznaje go za
 * bibliotekę systemową i NIE dołącza do artefaktu. U użytkownika Qt używa
 * prawdziwego ICU z Windows.
 */
#include <stddef.h>
#include <stdint.h>

#define EXPORT __declspec(dllexport)

typedef int32_t UErrorCode;
#define U_FILE_ACCESS_ERROR 4

EXPORT void *ucnv_open(const char *name, UErrorCode *err)
{
    (void)name;
    if (err != NULL && *err <= 0)
        *err = U_FILE_ACCESS_ERROR;
    return NULL;
}

EXPORT int32_t ucnv_countAvailable(void) { return 0; }
EXPORT const char *ucnv_getAvailableName(int32_t n) { (void)n; return NULL; }
EXPORT const char *ucnv_getStandardName(const char *name, const char *standard, UErrorCode *err)
{
    (void)name; (void)standard; (void)err;
    return NULL;
}

/* Poniższe działają wyłącznie na konwerterze, którego ucnv_open nigdy nie
 * zwraca — nie mogą zostać wywołane z poprawnym argumentem. */
EXPORT void ucnv_close(void *cnv) { (void)cnv; }
EXPORT void ucnv_reset(void *cnv) { (void)cnv; }
EXPORT int8_t ucnv_getMaxCharSize(const void *cnv) { (void)cnv; return 1; }
EXPORT const char *ucnv_getName(const void *cnv, UErrorCode *err) { (void)cnv; (void)err; return NULL; }
EXPORT int32_t ucnv_fromUCountPending(const void *cnv, UErrorCode *err) { (void)cnv; (void)err; return 0; }
EXPORT int32_t ucnv_toUCountPending(const void *cnv, UErrorCode *err) { (void)cnv; (void)err; return 0; }
EXPORT void ucnv_fromUnicode(void) {}
EXPORT void ucnv_toUnicode(void) {}
EXPORT void ucnv_getFromUCallBack(void) {}
EXPORT void ucnv_getToUCallBack(void) {}
EXPORT void ucnv_setFromUCallBack(void) {}
EXPORT void ucnv_setToUCallBack(void) {}
EXPORT void ucnv_cbFromUWriteUChars(void) {}
EXPORT void ucnv_cbToUWriteUChars(void) {}
EXPORT void UCNV_FROM_U_CALLBACK_SUBSTITUTE(void) {}
EXPORT void UCNV_TO_U_CALLBACK_SUBSTITUTE(void) {}
