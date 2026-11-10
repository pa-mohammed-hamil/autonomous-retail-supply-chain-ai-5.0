"""Planned module: image preprocessing. Implementation pending."""

"""
ai/computer_vision/image_preprocessing.py

Image preprocessing for retail computer vision.

Supports:
- RGB/BGR conversion
- Aspect-ratio-preserving letterbox
- Denoising and contrast enhancement
- ImageNet normalization
- PyTorch tensor conversion
- Coordinate mapping to original image

OpenCV input images use BGR format.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


@dataclass
class PreprocessResult:
    image: np.ndarray
    original_size: tuple[int, int]
    processed_size: tuple[int, int]
    scale: float
    padding: tuple[int, int, int, int]


class ImagePreprocessor:

    IMAGENET_MEAN = np.array(
        [0.485, 0.456, 0.406],
        dtype=np.float32,
    )

    IMAGENET_STD = np.array(
        [0.229, 0.224, 0.225],
        dtype=np.float32,
    )

    @staticmethod
    def load(image_path: str) -> np.ndarray:
        path = Path(image_path)

        if not path.is_file():
            raise FileNotFoundError(path)

        image = cv2.imread(
            str(path),
            cv2.IMREAD_COLOR,
        )

        if image is None:
            raise ValueError(
                "Unable to decode image"
            )

        return image

    @staticmethod
    def validate(image: np.ndarray) -> None:
        if (
            not isinstance(image, np.ndarray)
            or image.dtype != np.uint8
            or image.ndim != 3
            or image.shape[2] != 3
            or image.shape[0] <= 0
            or image.shape[1] <= 0
        ):
            raise ValueError(
                "Expected uint8 HxWx3 BGR image"
            )

    @classmethod
    def enhance(
        cls,
        image: np.ndarray,
        denoise: bool = False,
        clahe: bool = False,
    ) -> np.ndarray:
        cls.validate(image)
        result = image.copy()

        if denoise:
            result = cv2.fastNlMeansDenoisingColored(
                result,
                None,
                5,
                5,
                7,
                21,
            )

        if clahe:
            lab = cv2.cvtColor(
                result,
                cv2.COLOR_BGR2LAB,
            )

            l, a, b = cv2.split(lab)

            equalizer = cv2.createCLAHE(
                clipLimit=2.0,
                tileGridSize=(8, 8),
            )

            l = equalizer.apply(l)

            result = cv2.cvtColor(
                cv2.merge((l, a, b)),
                cv2.COLOR_LAB2BGR,
            )

        return result

    @classmethod
    def letterbox(
        cls,
        image: np.ndarray,
        target_size: tuple[int, int] = (640, 640),
        pad_value: int = 114,
    ) -> PreprocessResult:
        """
        target_size = (width, height)

        Returns an image with exact target dimensions.
        """
        cls.validate(image)

        target_w, target_h = target_size

        if (
            target_w <= 0
            or target_h <= 0
            or not 0 <= pad_value <= 255
        ):
            raise ValueError(
                "Invalid letterbox configuration"
            )

        original_h, original_w = image.shape[:2]

        scale = min(
            target_w / original_w,
            target_h / original_h,
        )

        new_w = max(
            1,
            min(
                target_w,
                round(original_w * scale),
            ),
        )

        new_h = max(
            1,
            min(
                target_h,
                round(original_h * scale),
            ),
        )

        resized = cv2.resize(
            image,
            (new_w, new_h),
            interpolation=(
                cv2.INTER_AREA
                if scale < 1
                else cv2.INTER_LINEAR
            ),
        )

        pad_w = target_w - new_w
        pad_h = target_h - new_h

        left = pad_w // 2
        right = pad_w - left
        top = pad_h // 2
        bottom = pad_h - top

        padded = cv2.copyMakeBorder(
            resized,
            top,
            bottom,
            left,
            right,
            cv2.BORDER_CONSTANT,
            value=(pad_value,) * 3,
        )

        return PreprocessResult(
            image=padded,
            original_size=(
                original_w,
                original_h,
            ),
            processed_size=(
                target_w,
                target_h,
            ),
            scale=scale,
            padding=(
                left,
                top,
                right,
                bottom,
            ),
        )

    @classmethod
    def classification_tensor(
        cls,
        image: np.ndarray,
        size: int = 224,
    ):
        """
        Returns a float32 PyTorch tensor:
            [1, 3, size, size]

        Uses direct square resizing, matching the
        configured model preprocessing contract.
        """
        import torch

        cls.validate(image)

        if size <= 0:
            raise ValueError(
                "size must be positive"
            )

        rgb = cv2.cvtColor(
            image,
            cv2.COLOR_BGR2RGB,
        )

        resized = cv2.resize(
            rgb,
            (size, size),
            interpolation=cv2.INTER_LINEAR,
        )

        normalized = (
            resized.astype(np.float32)
            / 255.0
        )

        normalized = (
            normalized - cls.IMAGENET_MEAN
        ) / cls.IMAGENET_STD

        chw = np.transpose(
            normalized,
            (2, 0, 1),
        )

        return torch.from_numpy(
            np.ascontiguousarray(chw)
        ).unsqueeze(0)

    @staticmethod
    def restore_boxes(
        boxes: list[list[float]],
        result: PreprocessResult,
    ) -> list[list[float]]:
        """
        Convert xyxy boxes from letterboxed
        coordinates to original image coordinates.
        """
        left, top, _, _ = result.padding
        original_w, original_h = result.original_size

        # Use the actual resized dimensions to
        # account for integer rounding.
        processed_w, processed_h = (
            result.processed_size
        )
        _, _, right, bottom = result.padding

        scale_x = (
            processed_w - left - right
        ) / original_w

        scale_y = (
            processed_h - top - bottom
        ) / original_h

        restored = []

        for box in boxes:
            if len(box) != 4:
                raise ValueError(
                    "Expected xyxy box"
                )

            x1, y1, x2, y2 = box

            restored.append([
                round(
                    float(np.clip(
                        (x1 - left) / scale_x,
                        0,
                        original_w,
                    )),
                    2,
                ),
                round(
                    float(np.clip(
                        (y1 - top) / scale_y,
                        0,
                        original_h,
                    )),
                    2,
                ),
                round(
                    float(np.clip(
                        (x2 - left) / scale_x,
                        0,
                        original_w,
                    )),
                    2,
                ),
                round(
                    float(np.clip(
                        (y2 - top) / scale_y,
                        0,
                        original_h,
                    )),
                    2,
                ),
            ])

        return restored
    