"""Build an installable Anki add-on archive from this source tree."""

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "dist" / "anki-tutor.ankiaddon"
SOURCES = (
    "manifest.json",
    "LICENSE",
    "config.json",
    "__init__.py",
    "panel.py",
    "authoring.py",
    "authoring_client.py",
    "authoring_dialog.py",
    "authoring_style.py",
    "bulk_fill.py",
    "browser_tools.py",
    "safe_write.py",
    "tts.py",
    "usage.py",
    "usage_page.py",
    "usage_i18n.py",
    "home.py",
    "home_i18n.py",
    "insights.py",
    "insights_dialog.py",
    "history.py",
    "attachments.py",
    "harness.py",
    "protocols.py",
    "context.py",
    "i18n.py",
    "authoring_i18n.py",
    "storage.py",
    "web/chat.js",
    "web/chat.css",
    "web/mathjax-config.js",
    "web/vendor/markdown-it.min.js",
    "web/vendor/LICENSE.markdown-it",
)


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(OUTPUT, "w", compression=ZIP_DEFLATED) as archive:
        for name in SOURCES:
            archive.write(ROOT / name, arcname=name)
    print(OUTPUT)


if __name__ == "__main__":
    main()
