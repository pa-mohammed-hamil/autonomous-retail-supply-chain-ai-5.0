"""Planned module: barcode detection. Implementation pending."""

"""
ai/computer_vision/barcode_reader.py

Barcode decoding and product lookup.

Features:
- EAN / UPC / Code128 / QR decoding
- Optional detector-assisted reading
- GTIN checksum validation
- Product catalog lookup
- Deduplication by code and type
- Manual-review flags

Dependencies:
    opencv-python
    pyzbar
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2
from pyzbar.pyzbar import decode


GTIN_LENGTHS = {8, 12, 13, 14}


def valid_gtin(value: str) -> bool:
    """
    Validate GTIN-8/12/13/14 check digit.

    A valid GTIN does not prove authenticity.
    """

    if (
        not isinstance(value, str)
        or not value.isascii()
        or not value.isdigit()
        or len(value) not in GTIN_LENGTHS
    ):
        return False

    digits = [int(c) for c in value]

    check_digit = digits[-1]

    body = digits[:-1][::-1]

    total = sum(
        digit * (3 if index % 2 == 0 else 1)
        for index, digit in enumerate(body)
    )

    expected = (-total) % 10

    return check_digit == expected


class BarcodeReader:

    def __init__(
        self,
        product_catalog: dict[str, dict] | None = None,
    ):
        if product_catalog is not None:
            if not isinstance(product_catalog, dict):
                raise ValueError(
                    "Catalog must be a dictionary"
                )

        self.product_catalog = (
            product_catalog or {}
        )

    @staticmethod
    def _read_image(
        image_path: str,
    ):
        path = Path(image_path)

        if not path.is_file():
            raise FileNotFoundError(path)

        image = cv2.imread(str(path))

        if image is None:
            raise ValueError(
                "Unable to read image"
            )

        return image

    @staticmethod
    def _decode_image(
        image,
        offset_x: int = 0,
        offset_y: int = 0,
    ) -> list[dict[str, Any]]:

        results = []

        for item in decode(image):
            try:
                value = item.data.decode(
                    "utf-8"
                )
            except UnicodeDecodeError:
                # Binary payloads are not silently
                # interpreted as product IDs.
                continue

            x = int(
                item.rect.left
            ) + offset_x

            y = int(
                item.rect.top
            ) + offset_y

            width = int(
                item.rect.width
            )

            height = int(
                item.rect.height
            )

            results.append({
                "value": value,
                "barcode_type": item.type,
                "bbox": [
                    x,
                    y,
                    x + width,
                    y + height,
                ],
            })

        return results

    def read(
        self,
        image_path: str,
        detected_regions: list[dict] | None = None,
    ) -> dict:

        image = self._read_image(
            image_path
        )

        height, width = image.shape[:2]

        # Always try full-image decoding first.
        decoded = self._decode_image(
            image
        )

        if detected_regions is not None:
            if not isinstance(
                detected_regions, list
            ):
                raise ValueError(
                    "detected_regions must be a list"
                )

            for region in detected_regions:
                if not isinstance(region, dict):
                    raise ValueError(
                        "Invalid region"
                    )

                bbox = region.get("bbox")

                if (
                    not isinstance(bbox, (list, tuple))
                    or len(bbox) != 4
                ):
                    raise ValueError(
                        "Invalid region bbox"
                    )

                x1, y1, x2, y2 = [
                    int(v) for v in bbox
                ]

                x1 = max(0, min(width, x1))
                x2 = max(0, min(width, x2))
                y1 = max(0, min(height, y1))
                y2 = max(0, min(height, y2))

                if x2 <= x1 or y2 <= y1:
                    continue

                crop = image[
                    y1:y2,
                    x1:x2,
                ]

                decoded.extend(
                    self._decode_image(
                        crop,
                        offset_x=x1,
                        offset_y=y1,
                    )
                )

        unique = {}

        for item in decoded:
            key = (
                item["barcode_type"],
                item["value"],
            )

            # This deduplicates identifiers, not
            # separate physical product instances.
            if key not in unique:
                unique[key] = item

        results = []

        for item in unique.values():
            value = item["value"]
            barcode_type = item[
                "barcode_type"
            ]

            is_gtin = barcode_type in {
                "EAN8",
                "EAN13",
                "UPCA",
                "UPCE",
                "ISBN13",
                "ISBN10",
            }

            # Normalize UPC-A and EAN-13 aliases
            # only if the catalog uses this scheme.
            catalog_product = (
                self.product_catalog.get(
                    value
                )
            )

            checksum_valid = (
                valid_gtin(value)
                if barcode_type in {
                    "EAN8",
                    "EAN13",
                    "UPCA",
                }
                else None
            )

            results.append({
                **item,
                "gtin_checksum_valid": (
                    checksum_valid
                ),
                "catalog_match": (
                    catalog_product is not None
                ),
                "product": catalog_product,
                "requires_review": (
                    catalog_product is None
                    or checksum_valid is False
                ),
            })

        return {
            "image_path": image_path,
            "barcode_count": len(results),
            "barcodes": results,
            "identifiers_deduplicated": True,
            "inventory_quantity_verified": False,
        }
