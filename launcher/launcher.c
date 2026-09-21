/* Pdf Rename.exe
 *
 * A batch file cannot carry its own icon, so this tiny program does. It
 * runs pdf_renamer_launcher.bat from its own folder and passes along any
 * folder dropped onto it. Nothing else. All setup logic stays in the batch
 * file so it can be read and edited without a compiler.
 */
#include <windows.h>
#include <shellapi.h>
#include <wchar.h>
#include <string.h>

int WINAPI wWinMain(HINSTANCE hInst, HINSTANCE hPrev, PWSTR args, int show)
{
    wchar_t dir[MAX_PATH], bat[MAX_PATH];
    if (!GetModuleFileNameW(NULL, dir, MAX_PATH))
        return 1;
    wchar_t *slash = wcsrchr(dir, L'\\');
    if (slash) *slash = 0;
    /* Built by plain concatenation. swprintf's %s is ambiguous between the
       MSVC and mingw C libraries, and one of them truncates a wide string
       after its first character. */
    wcscpy(bat, dir);
    wcscat(bat, L"\\pdf_renamer_launcher.bat");

    if (GetFileAttributesW(bat) == INVALID_FILE_ATTRIBUTES) {
        wchar_t msg[MAX_PATH + 160];
        wcscpy(msg, L"Could not find:\n");
        wcscat(msg, bat);
        wcscat(msg, L"\n\nKeep PDF Renamer.exe in the same folder as the other app files.");
        MessageBoxW(NULL, msg, L"Pdf Rename", MB_ICONERROR | MB_OK);
        return 1;
    }

    HINSTANCE r = ShellExecuteW(NULL, L"open", bat,
                                (args && *args) ? args : NULL, dir, SW_SHOWNORMAL);
    return ((INT_PTR)r > 32) ? 0 : 1;
}
