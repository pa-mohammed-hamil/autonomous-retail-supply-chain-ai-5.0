
"""
ai/computer_vision/batch_inference.py

Batch inference for retail computer vision.

Features:
- Multi-image processing
- Shared model instance
- Bounded batch size
- Configurable retries
- Partial failure handling
- JSONL result export
- Batch execution statistics

This is application-level batching:
each image is inferred individually.
It does not perform tensor-level GPU batching.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable


@dataclass(frozen=True)
class BatchConfig:
    batch_size: int = 8
    max_retries: int = 1
    retry_delay_seconds: float = 0.5
    max_images: int = 1000


class BatchInference:

    def __init__(
        self,
        inference_pipeline: Any,
        output_directory: str = (
            "storage/batch_results"
        ),
        config: BatchConfig | None = None,
        retryable_exceptions: tuple[type[Exception], ...] = (
            TimeoutError,
            ConnectionError,
        ),
    ):
        self.pipeline = inference_pipeline
        self.output_directory = Path(
            output_directory
        )
        self.config = config or BatchConfig()
        self.retryable_exceptions = (
            retryable_exceptions
        )

        if self.config.batch_size <= 0:
            raise ValueError("Invalid batch size")

        if self.config.max_retries < 0:
            raise ValueError("Invalid retry count")

        if self.config.max_images <= 0:
            raise ValueError("Invalid image limit")

        if self.config.retry_delay_seconds < 0:
            raise ValueError("Invalid retry delay")

        self.output_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

    @staticmethod
    def _sha256_file(path: Path) -> str:
        digest = hashlib.sha256()

        with path.open("rb") as file:
            for chunk in iter(
                lambda: file.read(1024 * 1024),
                b"",
            ):
                digest.update(chunk)

        return digest.hexdigest()

    @staticmethod
    def _chunks(
        items: list,
        size: int,
    ) -> Iterable[list]:
        for start in range(
            0,
            len(items),
            size,
        ):
            yield items[start:start + size]

    def _infer_one(
        self,
        image_path: str,
        shelf_regions: list[dict] | None,
    ) -> dict[str, Any]:

        path = Path(image_path)

        if not path.is_file():
            raise FileNotFoundError(path)

        image_hash = self._sha256_file(path)
        start = time.perf_counter()

        for attempt in range(
            1,
            self.config.max_retries + 2,
        ):
            try:
                prediction = self.pipeline.run(
                    image_path=str(path),
                    shelf_regions=shelf_regions,
                )

                status = prediction.get(
                    "status",
                    "unknown",
                )

                return {
                    "image_path": str(path),
                    "image_sha256": image_hash,
                    "status": status,
                    "attempts": attempt,
                    "latency_ms": round(
                        (
                            time.perf_counter()
                            - start
                        ) * 1000,
                        2,
                    ),
                    "prediction": prediction,
                }

            except self.retryable_exceptions as exc:
                if (
                    attempt
                    > self.config.max_retries
                ):
                    return {
                        "image_path": str(path),
                        "image_sha256": image_hash,
                        "status": "failed",
                        "attempts": attempt,
                        "error_type": type(exc).__name__,
                    }

                time.sleep(
                    self.config.retry_delay_seconds
                    * attempt
                )

            except Exception as exc:
                return {
                    "image_path": str(path),
                    "image_sha256": image_hash,
                    "status": "failed",
                    "attempts": attempt,
                    "error_type": type(exc).__name__,
                }

        raise RuntimeError(
            "Unexpected retry state"
        )

    def run(
        self,
        image_paths: list[str],
        shelf_regions: list[dict] | None = None,
        result_callback: Callable[[dict], None] | None = None,
    ) -> dict[str, Any]:

        if not image_paths:
            raise ValueError(
                "No images provided"
            )

        if (
            len(image_paths)
            > self.config.max_images
        ):
            raise ValueError(
                "Batch exceeds image limit"
            )

        batch_id = uuid.uuid4().hex
        started_at = datetime.now(
            timezone.utc
        ).isoformat()

        output_path = (
            self.output_directory
            / f"{batch_id}.jsonl"
        )

        start = time.perf_counter()
        results = []

        with output_path.open(
            "w",
            encoding="utf-8",
        ) as output_file:

            for chunk in self._chunks(
                image_paths,
                self.config.batch_size,
            ):
                for image_path in chunk:
                    try:
                        result = self._infer_one(
                            image_path,
                            shelf_regions,
                        )
                    except Exception as exc:
                        # Includes unreadable files or
                        # hashing failures.
                        result = {
                            "image_path": image_path,
                            "status": "failed",
                            "error_type": (
                                type(exc).__name__
                            ),
                        }

                    results.append(result)

                    output_file.write(
                        json.dumps(
                            result,
                            allow_nan=False,
                        ) + "\n"
                    )

                    if result_callback:
                        try:
                            result_callback(result)
                        except Exception:
                            # Callback failures should
                            # be logged in production.
                            pass

        completed = sum(
            item["status"] == "completed"
            for item in results
        )

        partial = sum(
            item["status"] == "partial_failure"
            for item in results
        )

        failed = len(results) - completed - partial

        return {
            "batch_id": batch_id,
            "started_at": started_at,
            "finished_at": datetime.now(
                timezone.utc
            ).isoformat(),
            "total_images": len(results),
            "completed": completed,
            "partial_failure": partial,
            "failed": failed,
            "elapsed_seconds": round(
                time.perf_counter() - start,
                3,
            ),
            "results_path": str(output_path),
            "status": (
                "completed"
                if failed == 0 and partial == 0
                else "completed_with_errors"
            ),
        }
