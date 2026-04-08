import asyncio
from typing import List, Tuple

import numpy as np

from coherent_engine.modules.mouse_flow import MouseFlowModule


def _paste_template(frame: np.ndarray, tpl: np.ndarray, center: Tuple[int, int]) -> None:
    h, w = frame.shape[:2]
    th, tw = tpl.shape[:2]
    cx, cy = center
    x0 = int(round(cx - tw / 2))
    y0 = int(round(cy - th / 2))
    x1 = x0 + tw
    y1 = y0 + th
    if x0 < 0 or y0 < 0 or x1 > w or y1 > h:
        return
    mask = tpl < 128
    patch = frame[y0:y1, x0:x1]
    patch[mask] = (0, 0, 0)


def _gen_frames() -> Tuple[List[np.ndarray], Tuple[int, int]]:
    module = MouseFlowModule()
    tpl = module._default_templates()[0]
    frames: List[np.ndarray] = []

    path: List[Tuple[int, int]] = []
    for i in range(20):
        path.append((50 + int(i * 10), 60 + int(i * 6)))
    pause_point = path[-1]
    for _ in range(10):
        path.append(pause_point)
    for i in range(10):
        path.append((pause_point[0] + int(i * 6), pause_point[1] + int(i * 2)))

    for p in path:
        frame = np.ones((480, 640, 3), dtype=np.uint8) * 255
        _paste_template(frame, tpl, p)
        frames.append(frame)
    return frames, pause_point


async def _run() -> None:
    frames, pause_point = _gen_frames()
    module = MouseFlowModule()
    out = await module.process(
        input_data={"frames": frames, "fps": 30.0},
        config={
            "match_threshold": 0.35,
            "smooth_alpha": 0.45,
            "click_stationary_frames": 6,
            "click_min_confidence": 0.3,
            "click_speed_threshold": 1.5,
        },
        context={},
    )

    assert "trajectory" in out
    assert "clicks" in out
    assert "confidence" in out
    assert len(out["trajectory"]) == len(frames)
    assert out["confidence"] > 0
    assert len(out["clicks"]) >= 1

    c = out["clicks"][0]
    dx = abs(float(c["x"]) - float(pause_point[0]))
    dy = abs(float(c["y"]) - float(pause_point[1]))
    assert dx < 25 and dy < 25


def main() -> None:
    asyncio.run(_run())
    print("mouse_flow_test_ok")


if __name__ == "__main__":
    main()

