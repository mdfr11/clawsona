"""Build the static project page using only public, explicitly selected files."""

import argparse
import json
import re
import shutil
import tarfile
from pathlib import Path

from check_distribution import check_distribution


def build_site(root: Path, repository_url: str | None = None) -> Path:
    website = root / "website"
    release = root / "dist" / "clawsona-0.3.0.tar.gz"
    if not release.is_file():
        raise SystemExit("Run uv build before building the project page.")
    check_distribution(root / "dist")
    with tarfile.open(release) as archive:
        if not any(member.name.endswith("/website/index.html") for member in archive):
            raise SystemExit("Source archive predates the website. Run uv build again.")
    output = website / "dist"
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(exist_ok=True)
    for name in ("index.html", "styles.css", "app.js", "site-config.json"):
        shutil.copy2(website / name, output / name)
    if repository_url is not None:
        if not re.fullmatch(r"https://github\.com/[\w.-]+/[\w.-]+/?", repository_url):
            raise SystemExit("Use a real https://github.com/owner/repository URL.")
        (output / "site-config.json").write_text(
            json.dumps({"repository_url": repository_url}, indent=2) + "\n"
        )
    assets = output / "assets"
    assets.mkdir(exist_ok=True)
    for name in ("mark.svg", "cover.svg", "pipeline.svg", "social-card.png"):
        shutil.copy2(root / "docs/assets" / name, assets / name)
    media = output / "media"
    media.mkdir(exist_ok=True)
    for name in ("hello-ru.mp3", "hello-en.mp3", "README.md"):
        shutil.copy2(website / "media" / name, media / name)
    downloads = output / "downloads"
    downloads.mkdir(exist_ok=True)
    shutil.copy2(release, downloads / release.name)
    print(f"Static project page ready: {output}")
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--repository-url", help="Public GitHub repository URL")
    args = parser.parse_args()
    build_site(args.root.resolve(), args.repository_url)
