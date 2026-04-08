import asyncio
import os
from typing import Any, Dict

import cv2
import numpy as np

from .base import BaseModule


class PoseModule(BaseModule):
    _cascade_specs = [
        ("frontalface", "haarcascade_frontalface_default.xml"),
        ("profileface", "haarcascade_profileface.xml"),
        ("upperbody", "haarcascade_upperbody.xml"),
        ("fullbody", "haarcascade_fullbody.xml"),
    ]

    def __init__(self):
        self._cascades: Dict[str, cv2.CascadeClassifier] = {}
        self._hog = cv2.HOGDescriptor()
        self._hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())

    @property
    def name(self) -> str:
        return "pose_module"

    @property
    def module_type(self) -> str:
        return "pose"

    def _load_cascades(self) -> None:
        if self._cascades:
            return
        for key, xml in self._cascade_specs:
            path = cv2.data.haarcascades + xml
            self._cascades[key] = cv2.CascadeClassifier(path)

    def _read_frame(self, input_data: Any) -> np.ndarray | None:
        if isinstance(input_data, str) and os.path.exists(input_data):
            return cv2.imread(input_data)
        if isinstance(input_data, np.ndarray):
            return input_data
        if isinstance(input_data, dict):
            candidate = input_data.get("start_frame") or input_data.get("start")
            if isinstance(candidate, str) and os.path.exists(candidate):
                return cv2.imread(candidate)
            if isinstance(candidate, np.ndarray):
                return candidate
        return None

    def _detect_best_haar(self, gray: np.ndarray) -> tuple[bool, str, tuple[int, int, int, int] | None, float]:
        self._load_cascades()

        best_bbox = None
        best_area = 0
        best_type = "none"

        for key, _ in self._cascade_specs:
            cas = self._cascades.get(key)
            if cas is None or cas.empty():
                continue

            rects = cas.detectMultiScale(
                gray,
                scaleFactor=1.1,
                minNeighbors=5,
                minSize=(30, 30),
                flags=cv2.CASCADE_SCALE_IMAGE,
            )

            if len(rects) == 0:
                continue

            for (x, y, w, h) in rects:
                area = int(w) * int(h)
                if area > best_area:
                    best_area = area
                    best_bbox = (int(x), int(y), int(w), int(h))
                    best_type = key

        if best_bbox is None:
            return False, "none", None, 0.0

        if best_type in {"frontalface", "profileface"}:
            confidence = 0.9
        elif best_type == "upperbody":
            confidence = 0.75
        else:
            confidence = 0.65

        return True, best_type, best_bbox, confidence

    def _detect_best_hog(self, frame_bgr: np.ndarray) -> tuple[bool, tuple[int, int, int, int] | None, float]:
        img = frame_bgr
        height, width = img.shape[:2]
        if width > 640:
            scale = 640.0 / width
            img = cv2.resize(img, (640, int(height * scale)))
        else:
            scale = 1.0

        (rects, weights) = self._hog.detectMultiScale(img, winStride=(4, 4), padding=(8, 8), scale=1.05)
        if len(rects) == 0:
            return False, None, 0.0

        max_idx = int(np.argmax(weights))
        (x, y, w, h) = rects[max_idx]
        confidence = float(weights[max_idx])
        bbox = (int(x / scale), int(y / scale), int(w / scale), int(h / scale))
        return True, bbox, confidence

    def _fallback_centroid(self, gray: np.ndarray) -> tuple[dict, float] | None:
        try:
            _, thresh = cv2.threshold(gray, 50, 255, cv2.THRESH_BINARY_INV)
            contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if not contours:
                return None
            c = max(contours, key=cv2.contourArea)
            m = cv2.moments(c)
            if m.get("m00", 0) == 0:
                return None
            cx = int(m["m10"] / m["m00"])
            cy = int(m["m01"] / m["m00"])
            return ({"x": float(cx), "y": float(cy), "z": 1.0}, 0.35)
        except Exception:
            return None

    async def process(self, input_data: Any, config: Dict[str, Any] = None, context: Dict[str, Any] = None) -> Any:
        print(f"  [{self.name}] Pose inference (Haar Cascade -> HOG -> centroid)...")

        frame = self._read_frame(input_data)
        if frame is None:
            await asyncio.sleep(0.01)
            return {
                "skeleton": "none",
                "confidence": 0.0,
                "root_position": {"x": 0.0, "y": 0.0, "z": 0.0},
                "detected": False,
                "detector": "none",
                "bbox": None,
            }

        if len(frame.shape) == 3:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        else:
            gray = frame

        gray = cv2.equalizeHist(gray)

        detected, det_type, bbox, confidence = self._detect_best_haar(gray)
        if detected and bbox is not None:
            x, y, w, h = bbox
            cx = x + w / 2.0
            cy = y + h / 2.0
            root_pos = {"x": float(cx), "y": float(cy), "z": 1.0}
            print(f"    [Pose] detected=True detector={det_type} bbox={bbox} center=({cx:.1f}, {cy:.1f})")
            await asyncio.sleep(0.01)
            return {
                "skeleton": "haar_detected",
                "confidence": confidence,
                "root_position": root_pos,
                "detected": True,
                "detector": det_type,
                "bbox": [x, y, w, h],
            }

        hog_ok, hog_bbox, hog_conf = self._detect_best_hog(frame)
        if hog_ok and hog_bbox is not None:
            x, y, w, h = hog_bbox
            cx = x + w / 2.0
            cy = y + h / 2.0
            root_pos = {"x": float(cx), "y": float(cy), "z": 1.0}
            print(f"    [Pose] detected=True detector=hog bbox={hog_bbox} center=({cx:.1f}, {cy:.1f}) conf={hog_conf:.2f}")
            await asyncio.sleep(0.01)
            return {
                "skeleton": "hog_detected_person",
                "confidence": hog_conf,
                "root_position": root_pos,
                "detected": True,
                "detector": "hog",
                "bbox": [x, y, w, h],
            }

        fb = self._fallback_centroid(gray)
        if fb is not None:
            root_pos, fb_conf = fb
            print(f"    [Pose] detected=False detector=fallback_centroid center=({root_pos['x']:.1f}, {root_pos['y']:.1f})")
            await asyncio.sleep(0.01)
            return {
                "skeleton": "fallback_centroid",
                "confidence": fb_conf,
                "root_position": root_pos,
                "detected": False,
                "detector": "fallback_centroid",
                "bbox": None,
            }

        print("    [Pose] detected=False detector=none")
        await asyncio.sleep(0.01)
        return {
            "skeleton": "none",
            "confidence": 0.1,
            "root_position": {"x": 0.0, "y": 0.0, "z": 1.0},
            "detected": False,
            "detector": "none",
            "bbox": None,
        }

