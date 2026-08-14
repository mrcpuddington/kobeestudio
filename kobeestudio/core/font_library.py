"""Versioned, update-safe storage for user-installed Google Font faces."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import urllib.request
import uuid
import sys
import io
import re
import urllib.parse
import ssl
import certifi
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Tuple

_VENDOR = str(Path(__file__).resolve().parents[1] / "vendor")
if _VENDOR not in sys.path:
    sys.path.insert(0, _VENDOR)

from fontTools.ttLib import TTFont

from .data_paths import user_data_root


FONT_SCHEMA_VERSION = 1
MAX_FONT_BYTES = 32 * 1024 * 1024
MAX_CATALOG_BYTES = 16 * 1024 * 1024
MAX_PREVIEW_CACHE_FACES = 24
GOOGLE_FONTS_METADATA_URL = "https://fonts.google.com/metadata/fonts"
GOOGLE_FONTS_CSS_URL = "https://fonts.googleapis.com/css2"


def _urlopen(request, timeout=30):
    return urllib.request.urlopen(request, timeout=timeout,
                                  context=ssl.create_default_context(cafile=certifi.where()))


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".font-", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, str(path))
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _font_names(path: Path) -> Tuple[str, str]:
    try:
        font = TTFont(str(path), lazy=True)
        names = font["name"]
        family = names.getDebugName(1) or names.getDebugName(16) or path.stem
        face = names.getDebugName(2) or names.getDebugName(17) or "Regular"
        font.close()
    except Exception as error:
        raise ValueError("Downloaded file is not a valid OpenType font: {}".format(error)) from error
    return str(family).strip(), str(face).strip()


def _normalise_font_bytes(data: bytes) -> bytes:
    """Validate an OpenType payload and return renderer-friendly TTF bytes."""
    if not isinstance(data, bytes) or not data or len(data) > MAX_FONT_BYTES:
        raise ValueError("Font file must be between 1 byte and 32 MiB")
    try:
        font = TTFont(io.BytesIO(data), lazy=False)
        font.flavor = None
        output = io.BytesIO()
        font.save(output)
        font.close()
        normalised = output.getvalue()
    except Exception as error:
        raise ValueError("Downloaded file is not a valid OpenType font: {}".format(error)) from error
    if not normalised or len(normalised) > MAX_FONT_BYTES:
        raise ValueError("Decoded font exceeds the 32 MiB safety limit")
    return normalised


def _atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".font-preview-", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, str(path))
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


@dataclass(frozen=True)
class FontFace:
    face_id: str
    family: str
    style: str
    weight: int
    renderer_name: str
    path: Path
    source_url: str
    licence_url: str = ""
    content_sha256: str = ""
    missing: bool = False

    @property
    def display_name(self) -> str:
        return "{} — {} {}".format(self.family, self.weight, self.style.title())


class FontLibraryStore:
    """Owns global installed font files and a best-effort Google catalog cache."""

    def __init__(self, data_root: Optional[Path] = None) -> None:
        self.data_root = Path(data_root) if data_root is not None else user_data_root()
        self.root = self.data_root / "fonts" / "v1"
        self.catalog_path = self.root / "catalog.json"
        # Preview files are an expendable performance cache, not portable
        # library data.  Keeping them outside fonts/v1 prevents backups from
        # growing merely because somebody browsed the catalog.
        self.preview_root = self.data_root / "cache" / "font-previews" / "v1"

    def list(self) -> Tuple[FontFace, ...]:
        return tuple(item for item in self.records() if not item.missing)

    def records(self) -> Tuple[FontFace, ...]:
        """Return valid metadata records, including repairable missing files."""
        result = []
        if not self.root.exists():
            return ()
        for directory in sorted(self.root.iterdir()):
            if directory.is_symlink() or not directory.is_dir():
                continue
            metadata_path = directory / "metadata.json"
            if metadata_path.is_symlink() or not metadata_path.is_file():
                continue
            try:
                payload = json.loads(metadata_path.read_text(encoding="utf-8"))
                if payload.get("schema_version") != FONT_SCHEMA_VERSION:
                    continue
                filename = str(payload["filename"])
                if Path(filename).name != filename:
                    continue
                font_path = directory / filename
                missing = font_path.is_symlink() or not font_path.is_file()
                digest = ""
                if not missing:
                    digest = hashlib.sha256(font_path.read_bytes()).hexdigest()
                    if digest != payload.get("content_sha256"):
                        missing = True
                    else:
                        try:
                            _font_names(font_path)
                        except ValueError:
                            missing = True
                result.append(FontFace(
                    face_id=str(payload["face_id"]), family=str(payload["family"]),
                    style=str(payload.get("style", "normal")), weight=int(payload.get("weight", 400)),
                    renderer_name=str(payload["renderer_name"]), path=font_path,
                    source_url=str(payload.get("source_url", "")),
                    licence_url=str(payload.get("licence_url", "")),
                    content_sha256=str(payload.get("content_sha256", digest)), missing=missing,
                ))
            except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
                continue
        return tuple(sorted(result, key=lambda item: (item.family.casefold(), item.weight, item.style)))

    def install_bytes(
        self, data: bytes, *, family: str, style: str = "normal", weight: int = 400,
        source_url: str = "", licence_url: str = "", licence_text: str = "",
    ) -> FontFace:
        if not isinstance(data, bytes) or not data or len(data) > MAX_FONT_BYTES:
            raise ValueError("Font file must be between 1 byte and 32 MiB")
        family = str(family).strip()
        style = str(style).strip().lower() or "normal"
        weight = int(weight)
        if not family or len(family) > 120 or style not in ("normal", "italic") or not 1 <= weight <= 1000:
            raise ValueError("Invalid font family, style, or weight")
        face_id = str(uuid.uuid4())
        destination = self.root / face_id
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".install-", dir=str(destination.parent)))
        try:
            font_path = staging / "font.ttf"
            normalized_data = _normalise_font_bytes(data)
            font_path.write_bytes(normalized_data)
            actual_family, actual_face = _font_names(font_path)
            renderer_name = "{}-{}-{}-{}".format(
                actual_family.replace(" ", ""), weight, style, face_id[:8]
            )
            digest = hashlib.sha256(normalized_data).hexdigest()
            if licence_text:
                (staging / "LICENSE.txt").write_text(licence_text, encoding="utf-8")
            _atomic_json(staging / "metadata.json", {
                "schema_version": FONT_SCHEMA_VERSION, "face_id": face_id,
                "family": family or actual_family, "face_name": actual_face,
                "style": style, "weight": weight, "renderer_name": renderer_name,
                "filename": "font.ttf", "source_url": str(source_url),
                "licence_url": str(licence_url), "content_sha256": digest,
            })
            os.replace(str(staging), str(destination))
        except Exception:
            shutil.rmtree(str(staging), ignore_errors=True)
            raise
        return next(item for item in self.list() if item.face_id == face_id)

    def download(self, **face) -> FontFace:
        source_url = str(face.get("source_url", ""))
        if not source_url.startswith("https://"):
            raise ValueError("Google Font downloads require an HTTPS source URL")
        request = urllib.request.Request(source_url, headers={"User-Agent": "Kobee-Studio"})
        with _urlopen(request, timeout=30) as response:
            data = response.read(MAX_FONT_BYTES + 1)
        return self.install_bytes(data, **face)

    def download_google_face(self, family: str, weight: int = 400, style: str = "normal") -> FontFace:
        preview_path, source_url, _cached = self.preview_face(family, weight, style)
        data = preview_path.read_bytes()
        licence_text, licence_url = self._google_licence(family)
        return self.install_bytes(
            data, family=family, weight=weight, style=style, source_url=source_url,
            licence_url=licence_url, licence_text=licence_text,
        )

    @staticmethod
    def _preview_key(family: str, weight: int, style: str) -> str:
        identity = "{}\0{}\0{}".format(str(family).strip().casefold(), int(weight), str(style).lower())
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()

    def preview_face(self, family: str, weight: int = 400, style: str = "normal") -> Tuple[Path, str, bool]:
        """Return one validated cached TTF for an on-demand catalog preview.

        Only the explicitly selected face is downloaded.  The cache is small,
        bounded, excluded from backups, and reused by installation so browsing
        a font never causes a second font-file download.
        """
        family, weight, style = str(family).strip(), int(weight), str(style).lower()
        if not family or not 1 <= weight <= 1000 or style not in ("normal", "italic"):
            raise ValueError("Invalid Google Font face")
        key = self._preview_key(family, weight, style)
        font_path = self.preview_root / "{}.ttf".format(key)
        metadata_path = self.preview_root / "{}.json".format(key)
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            if metadata.get("family") != family or int(metadata.get("weight")) != weight or metadata.get("style") != style:
                raise ValueError("Preview cache identity mismatch")
            if hashlib.sha256(font_path.read_bytes()).hexdigest() != metadata.get("content_sha256"):
                raise ValueError("Preview cache checksum mismatch")
            _font_names(font_path)
            os.utime(font_path, None)
            os.utime(metadata_path, None)
            return font_path, str(metadata.get("source_url", "")), True
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            for path in (font_path, metadata_path):
                try:
                    path.unlink()
                except OSError:
                    pass

        data, source_url = self._google_face_bytes(family, weight, style)
        normalised = _normalise_font_bytes(data)
        _atomic_bytes(font_path, normalised)
        _atomic_json(metadata_path, {
            "schema_version": 1,
            "family": family,
            "weight": weight,
            "style": style,
            "source_url": source_url,
            "content_sha256": hashlib.sha256(normalised).hexdigest(),
        })
        self._prune_preview_cache(keep_key=key)
        return font_path, source_url, False

    def _prune_preview_cache(self, keep_key: str = "") -> None:
        try:
            entries = sorted(
                self.preview_root.glob("*.ttf"),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
        except OSError:
            return
        for font_path in entries[MAX_PREVIEW_CACHE_FACES:]:
            if font_path.stem == keep_key:
                continue
            for path in (font_path, font_path.with_suffix(".json")):
                try:
                    path.unlink()
                except OSError:
                    pass

    def _google_face_bytes(self, family: str, weight: int = 400, style: str = "normal"):
        family, weight, style = str(family).strip(), int(weight), str(style).lower()
        if not family or not 1 <= weight <= 1000 or style not in ("normal", "italic"):
            raise ValueError("Invalid Google Font face")
        axis = "ital,wght@1,{}".format(weight) if style == "italic" else "wght@{}".format(weight)
        query = urllib.parse.urlencode({"family": "{}:{}".format(family, axis)})
        request = urllib.request.Request(
            "{}?{}".format(GOOGLE_FONTS_CSS_URL, query),
            headers={"User-Agent": "Mozilla/5.0 Kobee-Studio"},
        )
        with _urlopen(request, timeout=30) as response:
            css = response.read(1024 * 1024).decode("utf-8", "replace")
        urls = re.findall(r"url\((https://[^)]+)\)", css)
        if not urls:
            raise ValueError("Google Fonts did not provide that face")
        source_url = urls[-1]
        request = urllib.request.Request(source_url, headers={"User-Agent": "Kobee-Studio"})
        with _urlopen(request, timeout=30) as response:
            data = response.read(MAX_FONT_BYTES + 1)
        if len(data) > MAX_FONT_BYTES:
            raise ValueError("Google Font exceeds the 32 MiB safety limit")
        return data, source_url

    @staticmethod
    def _google_licence(family: str) -> Tuple[str, str]:
        slug = re.sub(r"[^a-z0-9]", "", str(family).lower())
        candidates = (
            ("ofl", "OFL.txt"), ("apache", "LICENSE.txt"), ("ufl", "UFL.txt"),
        )
        for directory, filename in candidates:
            url = "https://raw.githubusercontent.com/google/fonts/main/{}/{}/{}".format(directory, slug, filename)
            try:
                request = urllib.request.Request(url, headers={"User-Agent": "Kobee-Studio"})
                with _urlopen(request, timeout=15) as response:
                    raw = response.read(256 * 1024 + 1)
                if raw and len(raw) <= 256 * 1024:
                    return raw.decode("utf-8", "replace"), url
            except Exception:
                continue
        raise ValueError("Could not retrieve the upstream Google Fonts licence; the face was not installed")

    def repair(self, face_id: str) -> FontFace:
        """Redownload a missing face without changing its renderer identity."""
        record = next((item for item in self.records() if item.face_id == face_id), None)
        if record is None:
            raise LookupError("Font face was not found")
        if not record.missing:
            return record
        data, source_url = self._google_face_bytes(record.family, record.weight, record.style)
        licence_text, licence_url = self._google_licence(record.family)
        temporary = self.install_bytes(
            data, family=record.family, weight=record.weight, style=record.style,
            source_url=source_url, licence_url=licence_url, licence_text=licence_text,
        )
        destination = record.path.parent
        staging = Path(tempfile.mkdtemp(prefix=".repair-", dir=str(self.root)))
        tombstone = destination.with_name(".repair-old-{}".format(uuid.uuid4()))
        try:
            font_bytes = temporary.path.read_bytes()
            (staging / "font.ttf").write_bytes(font_bytes)
            metadata = json.loads((destination / "metadata.json").read_text(encoding="utf-8"))
            metadata.update({"source_url": source_url, "licence_url": licence_url,
                             "content_sha256": hashlib.sha256(font_bytes).hexdigest()})
            metadata_path = staging / "metadata.json"
            _atomic_json(metadata_path, metadata)
            if licence_text:
                (staging / "LICENSE.txt").write_text(licence_text, encoding="utf-8")
            os.replace(str(destination), str(tombstone))
            try:
                os.replace(str(staging), str(destination))
            except Exception:
                os.replace(str(tombstone), str(destination))
                raise
            shutil.rmtree(str(tombstone), ignore_errors=True)
        finally:
            shutil.rmtree(str(staging), ignore_errors=True)
            shutil.rmtree(str(temporary.path.parent), ignore_errors=True)
        return next(item for item in self.list() if item.face_id == face_id)

    def delete(self, face_id: str) -> None:
        match = next((item for item in self.records() if item.face_id == face_id), None)
        if match is None:
            raise LookupError("Font face was not found")
        directory = match.path.parent
        tombstone = directory.with_name(".delete-{}".format(uuid.uuid4()))
        os.replace(str(directory), str(tombstone))
        shutil.rmtree(str(tombstone))

    def load_catalog(self) -> Tuple[Mapping[str, Any], ...]:
        candidates = (self.catalog_path, Path(__file__).resolve().parents[1] / "resources" / "google_fonts_catalog.json")
        for path in candidates:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                families = payload.get("families", payload) if isinstance(payload, Mapping) else payload
                if isinstance(families, list):
                    return tuple(item for item in families if isinstance(item, Mapping))
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                continue
        return ()

    def refresh_catalog(self) -> Tuple[Mapping[str, Any], ...]:
        request = urllib.request.Request(GOOGLE_FONTS_METADATA_URL, headers={"User-Agent": "Kobee-Studio"})
        with _urlopen(request, timeout=30) as response:
            raw = response.read(MAX_CATALOG_BYTES + 1)
        if len(raw) > MAX_CATALOG_BYTES:
            raise ValueError("Google Fonts catalog response is too large")
        if raw.startswith(b")]}\'"):
            raw = raw.split(b"\n", 1)[-1]
        payload = json.loads(raw.decode("utf-8"))
        families = payload.get("familyMetadataList", payload.get("families", ()))
        if not isinstance(families, list):
            raise ValueError("Google Fonts returned an unsupported catalog")
        self.root.mkdir(parents=True, exist_ok=True)
        _atomic_json(self.catalog_path, {"schema_version": 1, "families": families})
        return tuple(item for item in families if isinstance(item, Mapping))


def installed_renderer_paths(stores: Iterable[FontLibraryStore]) -> Tuple[Tuple[str, Path], ...]:
    return tuple((face.renderer_name, face.path) for store in stores for face in store.list())
