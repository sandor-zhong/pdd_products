"""Ship installed runtime packages' own notices alongside the application."""
import importlib.metadata
import shutil
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
destination = root / "dist" / "ProductDesk"
packages = ["PyQt5", "PyQt5-Qt5", "PyQt5-sip", "openpyxl", "et_xmlfile", "Pillow"]
lines = ["商品资料台 1.0.2 - 运行组件说明", "", f"Python {sys.version.split()[0]}"]
for name in packages:
    package = importlib.metadata.distribution(name)
    lines.append(f"{name} {package.version}: {package.metadata.get('License-Expression') or package.metadata.get('License', 'See bundled notices')}")
    for item in package.files or []:
        if any(word in item.name.lower() for word in ("license", "copying", "notice")):
            source = Path(package.locate_file(item))
            if source.is_file():
                target = destination / "licenses" / name / item.name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
python_license = Path(sys.base_prefix) / "LICENSE.txt"
if python_license.is_file():
    target = destination / "licenses" / "Python" / "LICENSE.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(python_license, target)
(destination / "运行组件说明.txt").write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
shutil.copyfile(root / "packaging" / "使用说明.txt", destination / "使用说明.txt")
