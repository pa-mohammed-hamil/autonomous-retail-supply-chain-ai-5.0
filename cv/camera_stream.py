"""Planned module: camera stream. Implementation pending."""

"""
ai/computer_vision/camera_stream.py

Live computer vision stream processing.

Sources:
- Local webcam: 0
- Video file: "sample.mp4"
- RTSP stream: "rtsp://..."

Features:
- YOLO inference
- Frame sampling
- Bounding-box annotation
- Event callbacks
- Stream reconnect attempts
- Performance metrics
- Optional preview window

Only connect to authorized camera sources.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable, Any

import cv2

from ultralytics import YOLO

from ai.computer_vision.cv_metrics import (
    CVMetrics,
)


class CameraStream:

    def __init__(
        self,
        source: int | str = 0,
        model_path: str = "models/retail_product_best.pt",
        confidence: float = 0.40,
        image_size: int = 640,
        process_every_n_frames: int = 1,
        max_reconnect_attempts: int = 3,
        reconnect_delay_seconds: float = 2.0,
        preview: bool = False,
        event_callback: Callable[
            [dict[str, Any]], None
        ] | None = None,
    ):
        if (
            isinstance(source, bool)
            or not isinstance(source, (int, str))
        ):
            raise ValueError("Invalid camera source")

        if (
            not isinstance(confidence, (int, float))
            or isinstance(confidence, bool)
            or not 0 <= confidence <= 1
        ):
            raise ValueError("Invalid confidence")

        if (
            not isinstance(process_every_n_frames, int)
            or isinstance(process_every_n_frames, bool)
            or process_every_n_frames <= 0
        ):
            raise ValueError(
                "process_every_n_frames must be positive"
            )

        if (
            not isinstance(image_size, int)
            or image_size <= 0
        ):
            raise ValueError("Invalid image size")

        if (
            not isinstance(max_reconnect_attempts, int)
            or max_reconnect_attempts < 0
        ):
            raise ValueError(
                "Invalid reconnect attempts"
            )

        if reconnect_delay_seconds < 0:
            raise ValueError(
                "Invalid reconnect delay"
            )

        if not Path(model_path).is_file():
            raise FileNotFoundError(model_path)

        self.source = source
        self.model = YOLO(model_path)
        self.confidence = confidence
        self.image_size = image_size
        self.process_every_n_frames = (
            process_every_n_frames
        )

        self.max_reconnect_attempts = (
            max_reconnect_attempts
        )
        self.reconnect_delay_seconds = (
            reconnect_delay_seconds
        )

        self.preview = preview
        self.event_callback = event_callback

        self.metrics = CVMetrics()
        self.running = False

    def _open_capture(self):
        capture = cv2.VideoCapture(
            self.source
        )

        if not capture.isOpened():
            capture.release()
            raise RuntimeError(
                "Unable to open camera or video source"
            )

        return capture

    def _predict(
        self,
        frame,
    ) -> tuple[list[dict], Any]:

        results = self.model.predict(
            source=frame,
            conf=self.confidence,
            imgsz=self.image_size,
            verbose=False,
        )

        detections = []

        result = results[0]

        if result.boxes is not None:
            for box in result.boxes:
                class_id = int(
                    box.cls[0].item()
                )

                detections.append({
                    "class_id": class_id,
                    "class_name": result.names[
                        class_id
                    ],
                    "confidence": round(
                        float(box.conf[0].item()),
                        4,
                    ),
                    "bbox": [
                        round(float(value), 2)
                        for value in (
                            box.xyxy[0]
                            .cpu()
                            .tolist()
                        )
                    ],
                })

        annotated = result.plot()

        return detections, annotated

    def run(
        self,
        max_frames: int | None = None,
    ) -> dict:

        if max_frames is not None and (
            isinstance(max_frames, bool)
            or not isinstance(max_frames, int)
            or max_frames <= 0
        ):
            raise ValueError("Invalid max_frames")

        self.running = True

        capture = None
        reconnect_attempts = 0
        frame_number = 0
        processed_frames = 0

        try:
            capture = self._open_capture()

            while self.running:

                success, frame = capture.read()

                if not success:
                    # A finite video file normally ends here.
                    if (
                        isinstance(self.source, str)
                        and not self.source.startswith(
                            ("rtsp://", "rtsps://")
                        )
                    ):
                        break

                    capture.release()
                    capture = None

                    if (
                        reconnect_attempts
                        >= self.max_reconnect_attempts
                    ):
                        break

                    reconnect_attempts += 1
                    time.sleep(
                        self.reconnect_delay_seconds
                    )

                    try:
                        capture = self._open_capture()
                        reconnect_attempts = 0
                    except RuntimeError:
                        continue

                    continue

                frame_number += 1

                if (
                    frame_number
                    % self.process_every_n_frames
                    != 0
                ):
                    continue

                start = time.perf_counter()

                try:
                    detections, annotated = (
                        self._predict(frame)
                    )

                    latency_ms = (
                        time.perf_counter() - start
                    ) * 1000

                    self.metrics.record_frame(
                        latency_ms=latency_ms,
                        detections=detections,
                    )

                    processed_frames += 1

                    event = {
                        "frame_number": frame_number,
                        "detections": detections,
                        "latency_ms": round(
                            latency_ms, 2
                        ),
                        "timestamp_unix": (
                            time.time()
                        ),
                    }

                    if self.event_callback:
                        self.event_callback(
                            event
                        )

                    if self.preview:
                        cv2.imshow(
                            "Retail AI Camera",
                            annotated,
                        )

                        if (
                            cv2.waitKey(1) & 0xFF
                        ) == ord("q"):
                            break

                except Exception:
                    self.metrics.record_error()
                    # Continue processing subsequent frames.
                    continue

                if (
                    max_frames is not None
                    and processed_frames >= max_frames
                ):
                    break

        finally:
            self.running = False

            if capture is not None:
                capture.release()

            if self.preview:
                cv2.destroyAllWindows()

        return {
            "source_type": (
                "webcam"
                if isinstance(self.source, int)
                else "video_or_network"
            ),
            "frames_read": frame_number,
            "frames_processed": processed_frames,
            "metrics": self.metrics.summary(),
        }

    def stop(self) -> None:
        self.running = False
