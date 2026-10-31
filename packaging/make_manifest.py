"""Generate an uninstaller that removes only the files shipped in this build."""
from pathlib import Path

root = Path(__file__).resolve().parents[1]
distribution = root / "dist" / "ProductDesk"
entries = []
for path in sorted(distribution.rglob("*")):
    if path.is_file():
        relative = str(path.relative_to(distribution)).replace("$", "$$")
        entries.append(f'  Delete "$INSTDIR\\{relative}"')
directories = sorted((path for path in distribution.rglob("*") if path.is_dir()),
                     key=lambda path: len(path.parts), reverse=True)
for path in directories:
    relative = str(path.relative_to(distribution)).replace("$", "$$")
    entries.append(f'  RMDir "$INSTDIR\\{relative}"')
(root / "build" / "uninstall-files.nsh").write_text("\n".join(entries) + "\n", encoding="utf-8-sig")
print(f"Uninstall manifest: {len(entries)} file and directory entries")
