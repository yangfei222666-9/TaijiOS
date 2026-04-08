from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import cv2
import numpy as np

from .base import BaseModule


@dataclass
class _MatchResult:
    x: float
    y: float
    score: float
    template_size: Tuple[int, int]


class MouseFlowModule(BaseModule):
    @property
    def name(self) -> str:
        return "mouse_flow_module"

    @property
    def module_type(self) -> str:
        return "mouse_flow"

    async def process(
        self,
        input_data: Any,
        config: Dict[str, Any] = None,
        context: Dict[str, Any] = None,
    ) -> Any:
        config = config or {}
        frames, fps = self._load_frames(input_data, config)

        templates = self._load_templates(config)
        match_threshold = float(config.get("match_threshold", 0.55))
        smooth_alpha = float(config.get("smooth_alpha", 0.35))
        template_scales = config.get("template_scales", [0.8, 1.0, 1.2, 1.5])

        trajectory: List[Dict[str, Any]] = []
        raw_positions: List[Optional[Tuple[float, float]]] = []
        raw_scores: List[float] = []

        last_pos: Optional[Tuple[float, float]] = None
        last_smooth: Optional[Tuple[float, float]] = None

        for idx, frame in enumerate(frames):
            t = idx / fps if fps > 0 else float(idx)
            match = self._match_best(frame, templates, template_scales)
            if match is None or match.score < match_threshold:
                trajectory.append({"t": t, "x": None, "y": None, "confidence": 0.0})
                raw_positions.append(None)
                raw_scores.append(0.0)
                continue

            pos = (match.x, match.y)
            last_pos = pos
            if last_smooth is None:
                smooth = pos
            else:
                smooth = (
                    smooth_alpha * pos[0] + (1.0 - smooth_alpha) * last_smooth[0],
                    smooth_alpha * pos[1] + (1.0 - smooth_alpha) * last_smooth[1],
                )
            last_smooth = smooth

            trajectory.append(
                {
                    "t": t,
                    "x": float(smooth[0]),
                    "y": float(smooth[1]),
                    "confidence": float(match.score),
                }
            )
            raw_positions.append(smooth)
            raw_scores.append(float(match.score))

        clicks = self._detect_clicks(frames, fps, raw_positions, raw_scores, config)
        conf = self._aggregate_confidence(raw_scores)

        return {
            "trajectory": trajectory,
            "clicks": clicks,
            "confidence": conf,
            "fps": fps,
            "frames": len(frames),
        }

    def _load_frames(self, input_data: Any, config: Dict[str, Any]) -> Tuple[List[np.ndarray], float]:
        fps = float(config.get("fps", 30.0))
        max_frames = int(config.get("max_frames", 600))
        sample_every = int(config.get("sample_every", 1))

        def take_samples(seq: Sequence[Any]) -> List[Any]:
            if sample_every <= 1:
                return list(seq)[:max_frames]
            out = []
            for i, it in enumerate(seq):
                if i % sample_every == 0:
                    out.append(it)
                if len(out) >= max_frames:
                    break
            return out

        if isinstance(input_data, dict):
            if "frames" in input_data:
                items = take_samples(input_data["frames"])
                frames = [self._to_frame(it) for it in items]
                frames = [f for f in frames if f is not None]
                fps = float(input_data.get("fps", fps))
                return frames[:max_frames], fps
            if "video_path" in input_data:
                return self._read_video(str(input_data["video_path"]), max_frames, sample_every, fps)
            if "frames_dir" in input_data:
                return self._read_frame_dir(str(input_data["frames_dir"]), max_frames, sample_every, fps)

        if isinstance(input_data, str) and os.path.exists(input_data):
            p = Path(input_data)
            if p.is_dir():
                return self._read_frame_dir(str(p), max_frames, sample_every, fps)
            if p.suffix.lower() in {".mp4", ".avi", ".mov", ".mkv", ".webm"}:
                return self._read_video(str(p), max_frames, sample_every, fps)
            frame = cv2.imread(str(p))
            return ([frame] if frame is not None else []), fps

        if isinstance(input_data, np.ndarray):
            return [input_data], fps

        return [], fps

    def _read_frame_dir(self, frames_dir: str, max_frames: int, sample_every: int, fps: float) -> Tuple[List[np.ndarray], float]:
        p = Path(frames_dir)
        exts = (".png", ".jpg", ".jpeg", ".bmp", ".webp")
        paths = sorted([x for x in p.iterdir() if x.is_file() and x.suffix.lower() in exts])
        paths = paths[:: max(1, sample_every)][:max_frames]
        frames = []
        for fp in paths:
            im = cv2.imread(str(fp))
            if im is not None:
                frames.append(im)
        return frames, fps

    def _read_video(self, video_path: str, max_frames: int, sample_every: int, fallback_fps: float) -> Tuple[List[np.ndarray], float]:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return [], fallback_fps
        fps = cap.get(cv2.CAP_PROP_FPS)
        fps = float(fps) if fps and fps > 0 else fallback_fps
        frames: List[np.ndarray] = []
        idx = 0
        while len(frames) < max_frames:
            ok, frame = cap.read()
            if not ok:
                break
            if idx % max(1, sample_every) == 0:
                frames.append(frame)
            idx += 1
        cap.release()
        return frames, fps

    def _to_frame(self, item: Any) -> Optional[np.ndarray]:
        if isinstance(item, np.ndarray):
            return item
        if isinstance(item, str) and os.path.exists(item):
            return cv2.imread(item)
        return None

    def _load_templates(self, config: Dict[str, Any]) -> List[np.ndarray]:
        templates: List[np.ndarray] = []
        for t in config.get("templates", []) or []:
            if isinstance(t, str) and os.path.exists(t):
                im = cv2.imread(t, cv2.IMREAD_GRAYSCALE)
                if im is not None:
                    templates.append(im)
            elif isinstance(t, dict) and "path" in t and os.path.exists(str(t["path"])):
                im = cv2.imread(str(t["path"]), cv2.IMREAD_GRAYSCALE)
                if im is not None:
                    templates.append(im)

        if templates:
            return templates

        return self._default_templates()

    def _default_templates(self) -> List[np.ndarray]:
        h, w = 32, 24
        img = np.ones((h, w), dtype=np.uint8) * 255
        pts = np.array([[3, 3], [3, 28], [10, 22], [14, 31], [17, 29], [13, 20], [22, 20]], dtype=np.int32)
        cv2.fillPoly(img, [pts], 0)
        cv2.rectangle(img, (0, 0), (w - 1, h - 1), 255, 1)
        return [img]

    def _match_best(
        self,
        frame_bgr: np.ndarray,
        templates_gray: List[np.ndarray],
        template_scales: Sequence[float],
    ) -> Optional[_MatchResult]:
        if frame_bgr is None or frame_bgr.size == 0:
            return None
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY) if frame_bgr.ndim == 3 else frame_bgr
        gray = gray.astype(np.uint8, copy=False)
        edge = cv2.Canny(gray, 50, 150)

        best: Optional[_MatchResult] = None
        for tpl in templates_gray:
            tpl_gray = tpl.astype(np.uint8, copy=False)
            for s in template_scales:
                try:
                    sf = float(s)
                except Exception:
                    continue
                if sf <= 0:
                    continue
                if sf == 1.0:
                    tpl_s = tpl_gray
                else:
                    nh = int(round(tpl_gray.shape[0] * sf))
                    nw = int(round(tpl_gray.shape[1] * sf))
                    if nh < 8 or nw < 8:
                        continue
                    tpl_s = cv2.resize(tpl_gray, (nw, nh), interpolation=cv2.INTER_AREA if sf < 1.0 else cv2.INTER_CUBIC)
                tpl_edge = cv2.Canny(tpl_s, 50, 150)
                if edge.shape[0] < tpl_edge.shape[0] or edge.shape[1] < tpl_edge.shape[1]:
                    continue
                res = cv2.matchTemplate(edge, tpl_edge, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, max_loc = cv2.minMaxLoc(res)
                th, tw = tpl_edge.shape[:2]
                cx = float(max_loc[0] + tw / 2.0)
                cy = float(max_loc[1] + th / 2.0)
                cur = _MatchResult(x=cx, y=cy, score=float(max_val), template_size=(tw, th))
                if best is None or cur.score > best.score:
                    best = cur
        return best

    def _aggregate_confidence(self, scores: List[float]) -> float:
        vals = [s for s in scores if s > 0]
        if not vals:
            return 0.0
        return float(sum(vals) / len(vals))

    def _detect_clicks(
        self,
        frames: List[np.ndarray],
        fps: float,
        positions: List[Optional[Tuple[float, float]]],
        scores: List[float],
        config: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        if not frames or not positions:
            return []
        click_stationary_frames = int(config.get("click_stationary_frames", 6))
        click_speed_threshold = float(config.get("click_speed_threshold", 2.0))
        min_conf = float(config.get("click_min_confidence", 0.65))
        min_gap_s = float(config.get("click_min_gap_s", 0.25))
        min_gap_frames = int(max(1, round(min_gap_s * (fps if fps > 0 else 30.0))))

        clicks: List[Dict[str, Any]] = []
        last_click_idx = -10**9

        def dist(a: Tuple[float, float], b: Tuple[float, float]) -> float:
            return float(((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5)

        for i in range(1, len(positions)):
            if i - last_click_idx < min_gap_frames:
                continue

            window_start = max(0, i - click_stationary_frames + 1)
            window = positions[window_start : i + 1]
            if any(p is None for p in window):
                continue
            if any(scores[j] < min_conf for j in range(window_start, i + 1)):
                continue

            speeds = []
            for j in range(window_start + 1, i + 1):
                a = positions[j - 1]
                b = positions[j]
                if a is None or b is None:
                    speeds = []
                    break
                speeds.append(dist(a, b))
            if not speeds:
                continue
            if max(speeds) > click_speed_threshold:
                continue

            p = positions[i]
            if p is None:
                continue
            t = i / fps if fps > 0 else float(i)
            clicks.append(
                {
                    "t": t,
                    "x": float(p[0]),
                    "y": float(p[1]),
                    "confidence": float(min(scores[window_start : i + 1])),
                    "type": "pause",
                }
            )
            last_click_idx = i

        return clicks
