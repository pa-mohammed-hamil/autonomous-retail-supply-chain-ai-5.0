"""Planned module: image ingestion. Implementation pending."""

"""
ai/computer_vision/image_ingestion.py

Secure image ingestion for retail computer vision.

Features:
- Upload size limit
- Allowed image formats
- Decode verification
- Image dimension and pixel limits
- EXIF orientation correction
- Metadata removal by re-encoding
- SHA-256 integrity hash
- UUID-based storage filenames
- Tenant-scoped storage

Supported formats:
JPEG, PNG, WEBP

Requires:
    pillow
"""

from __future__ import annotations

import hashlib
import io
import re
import uuid

from pathlib import Path
from typing import Any

from PIL import (
    Image,
    ImageOps,
    UnidentifiedImageError,
)


class ImageIngestion:

    ALLOWED_FORMATS = {
        "JPEG",
        "PNG",
        "WEBP",
    }

    TENANT_PATTERN = re.compile(
        r"^[A-Za-z0-9_-]{1,64}$"
    )

    def __init__(
        self,
        storage_root: str = "storage/images",
        max_file_mb: int = 10,
        max_pixels: int = 25_000_000,
        max_dimension: int = 8000,
    ):
        if max_file_mb <= 0:
            raise ValueError(
                "max_file_mb must be positive"
            )

        if max_pixels <= 0 or max_dimension <= 0:
            raise ValueError(
                "Invalid image limits"
            )

        self.storage_root = Path(
            storage_root
        ).resolve()

        self.storage_root.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.max_file_bytes = (
            max_file_mb * 1024 * 1024
        )

        self.max_pixels = max_pixels
        self.max_dimension = max_dimension

    @staticmethod
    def _sha256(data: bytes) -> str:
        return hashlib.sha256(
            data
        ).hexdigest()

    def ingest_bytes(
        self,
        image_bytes: bytes,
        tenant_id: str,
        source_name: str = "upload",
    ) -> dict[str, Any]:

        if not isinstance(
            image_bytes, bytes
        ):
            raise ValueError(
                "image_bytes must be bytes"
            )

        if (
            not image_bytes
            or len(image_bytes)
            > self.max_file_bytes
        ):
            raise ValueError(
                "Empty or oversized upload"
            )

        if (
            not isinstance(tenant_id, str)
            or not self.TENANT_PATTERN.fullmatch(
                tenant_id
            )
        ):
            raise ValueError(
                "Invalid tenant identifier"
            )

        source_hash = self._sha256(
            image_bytes
        )

        try:
            with Image.open(
                io.BytesIO(image_bytes)
            ) as image:

                original_format = image.format

                if (
                    original_format
                    not in self.ALLOWED_FORMATS
                ):
                    raise ValueError(
                        "Unsupported image format"
                    )

                width, height = image.size

                if (
                    width <= 0
                    or height <= 0
                    or width > self.max_dimension
                    or height > self.max_dimension
                    or width * height > self.max_pixels
                ):
                    raise ValueError(
                        "Image dimensions exceed limits"
                    )

                # Fully decode before accepting.
                image.load()

                normalized = ImageOps.exif_transpose(
                    image
                )

                # Re-encode pixel data rather than
                # copying metadata or original bytes.
                normalized = normalized.convert(
                    "RGB"
                )

                normalized = normalized.copy()

        except (
            UnidentifiedImageError,
            OSError,
            Image.DecompressionBombError,
        ) as exc:
            raise ValueError(
                "Invalid or unsafe image"
            ) from exc

        tenant_directory = (
            self.storage_root / tenant_id
        )

        tenant_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        image_id = uuid.uuid4().hex

        destination = (
            tenant_directory
            / f"{image_id}.png"
        )

        # Save without original EXIF/ICC metadata.
        normalized.save(
            destination,
            format="PNG",
            optimize=True,
        )

        saved_bytes = destination.read_bytes()

        return {
            "image_id": image_id,
            "tenant_id": tenant_id,
            "source_name": source_name,
            "original_format": original_format,
            "normalized_format": "PNG",
            "width": normalized.width,
            "height": normalized.height,
            "source_size_bytes": len(
                image_bytes
            ),
            "normalized_size_bytes": len(
                saved_bytes
            ),
            "source_sha256": source_hash,
            "normalized_sha256": self._sha256(
                saved_bytes
            ),
            "storage_path": str(
                destination
            ),
            "metadata_stripped": True,
            "ready_for_cv": True,
        }

    def ingest_file(
        self,
        file_path: str,
        tenant_id: str,
    ) -> dict[str, Any]:

        path = Path(file_path)

        if not path.is_file():
            raise FileNotFoundError(path)

        if (
            path.stat().st_size
            > self.max_file_bytes
        ):
            raise ValueError(
                "File exceeds upload limit"
            )

        return self.ingest_bytes(
            image_bytes=path.read_bytes(),
            tenant_id=tenant_id,
            source_name=path.name,
        )
