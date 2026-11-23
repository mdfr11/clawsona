"""Inspect built release archives without importing ClawSona or loading .env."""

import argparse
import configparser
import json
import tarfile
import zipfile
from email.parser import BytesParser
from pathlib import Path, PurePosixPath


def require(condition, message):
    if not condition:
        raise SystemExit(message)


def check_members(names):
    for name in names:
        path = PurePosixPath(name)
        public_sample = path.parts[-3:] in {
            ("website", "media", "hello-ru.mp3"),
            ("website", "media", "hello-en.mp3"),
        }
        require(
            not path.is_absolute() and ".." not in path.parts, f"Unsafe path: {name}"
        )
        require(
            not any(
                part in {".git", ".venv", "__pycache__", "logs", "models", "sessions"}
                or part.startswith(".openclaw")
                for part in path.parts
            ),
            f"Runtime state in archive: {name}",
        )
        require(
            path.name == ".env.example"
            or not (path.name == ".env" or path.name.startswith(".env.")),
            f"Private environment file in archive: {name}",
        )
        require(
            path.name != "yandex-auth.json"
            and (
                public_sample
                or not path.name.endswith(
                    (
                        ".onnx",
                        ".onnx.json",
                        ".bin",
                        ".safetensors",
                        ".wav",
                        ".mp3",
                        ".pcm",
                        ".log",
                        ".pyc",
                        ".part",
                    )
                )
            )
            and ".log." not in path.name,
            f"Local model, recording or log in archive: {name}",
        )


def check_distribution(directory):
    wheels = list(directory.glob("clawsona-*.whl"))
    sources = list(directory.glob("clawsona-*.tar.gz"))
    require(
        len(wheels) == len(sources) == 1,
        "Expected exactly one ClawSona wheel and source archive",
    )
    with zipfile.ZipFile(wheels[0]) as wheel:
        names = set(wheel.namelist())
        check_members(names)
        required = {
            "clawsona/main.py",
            "clawsona/__main__.py",
            "lyutik/__init__.py",
            "clawsona/openclaw_plugin/index.js",
            "clawsona/openclaw_plugin/openclaw.plugin.json",
            "clawsona/openclaw_plugin/package.json",
        }
        require(required <= names, f"Missing runtime files: {sorted(required - names)}")
        info = [n for n in names if n.endswith(".dist-info/METADATA")]
        require(len(info) == 1, "Missing or ambiguous wheel metadata")
        metadata = BytesParser().parsebytes(wheel.read(info[0]))
        require(metadata["Name"] == "clawsona", "Wrong distribution name")
        require(
            metadata["License-Expression"] == "GPL-3.0-or-later",
            "Missing license metadata",
        )
        prefix = info[0].removesuffix("METADATA")
        require(prefix + "licenses/LICENSE" in names, "License text missing from wheel")
        entrypoints = configparser.ConfigParser()
        entrypoints.read_string(wheel.read(prefix + "entry_points.txt").decode())
        for command in ("clawsona", "lyutik"):
            require(
                entrypoints.get("console_scripts", command) == "clawsona.main:main",
                f"Missing CLI entrypoint: {command}",
            )
        manifest = json.loads(
            wheel.read("clawsona/openclaw_plugin/openclaw.plugin.json")
        )
        require(manifest["id"] == "clawsona-tools", "Wrong bundled plugin ID")
        version = metadata["Version"]
    with tarfile.open(sources[0]) as source:
        names = set(source.getnames())
        check_members(names)
        root = f"clawsona-{version}/"
        for required in (
            "LICENSE",
            "README.md",
            "CONTRIBUTING.md",
            "SECURITY.md",
            "uv.lock",
            ".env.example",
            "src/clawsona/main.py",
            "src/lyutik/__init__.py",
            "openclaw/clawsona-tools/index.js",
            ".github/workflows/ci.yml",
            "docs/README.ru.md",
            "docs/RELEASING.md",
            "docs/THIRD_PARTY_NOTICES.md",
            "docs/assets/cover.svg",
            "website/index.html",
            "website/media/hello-ru.mp3",
            "website/media/hello-en.mp3",
            "website/media/README.md",
        ):
            require(
                root + required in names, f"Missing source release file: {required}"
            )
    print(
        f"Verified ClawSona {version}: wheel, source, CLI aliases, plugin, license and runtime exclusions."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", nargs="?", type=Path, default=Path("dist"))
    check_distribution(parser.parse_args().directory)
