"""Fetch the pinned Markdown parser used by the chat webview."""

import io
import tarfile
from pathlib import Path
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
VERSION = "14.1.0"
URL = f"https://registry.npmjs.org/markdown-it/-/markdown-it-{VERSION}.tgz"


def main() -> None:
    with urlopen(URL, timeout=30) as response:
        payload = response.read()
    output = ROOT / "web" / "vendor"
    output.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as package:
        for source, destination in (
            ("package/dist/markdown-it.min.js", "markdown-it.min.js"),
            ("package/LICENSE", "LICENSE.markdown-it"),
        ):
            member = package.extractfile(source)
            if member is None:
                raise RuntimeError(f"Missing vendor file: {source}")
            (output / destination).write_bytes(member.read())
    print(f"Markdown-it {VERSION} vendored in {output}")


if __name__ == "__main__":
    main()
