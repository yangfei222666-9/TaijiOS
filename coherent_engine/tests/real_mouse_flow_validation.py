import argparse
import asyncio
import json
import subprocess
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from coherent_engine.modules.mouse_flow import MouseFlowModule


def _move_mouse(duration_s: float) -> None:
    import ctypes

    user32 = ctypes.windll.user32
    w = int(user32.GetSystemMetrics(0))
    h = int(user32.GetSystemMetrics(1))
    t0 = time.time()
    while True:
        dt = time.time() - t0
        if dt >= duration_s:
            break
        phase = dt / duration_s if duration_s > 0 else 1.0
        if 0.45 <= phase <= 0.60:
            time.sleep(0.02)
            continue
        x = int(w * (0.15 + 0.7 * phase))
        y = int(h * (0.35 + 0.15 * np.sin(phase * 2 * np.pi * 2)))
        user32.SetCursorPos(x, y)
        time.sleep(0.02)


def _record_desktop(video_path: Path, duration_s: float, fps: int) -> int:
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "gdigrab",
        "-draw_mouse",
        "1",
        "-framerate",
        str(int(fps)),
        "-i",
        "desktop",
        "-t",
        str(float(duration_s)),
        "-pix_fmt",
        "yuv420p",
        str(video_path),
    ]
    p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return int(p.wait())


def _save_evidence_frames(video_path: Path, result: dict, out_dir: Path, samples: int = 8) -> list:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return []
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    traj = result.get("trajectory") or []
    if total <= 0:
        cap.release()
        return []
    idxs = []
    if total <= samples:
        idxs = list(range(total))
    else:
        for i in range(samples):
            idxs.append(int(round(i * (total - 1) / (samples - 1))))
    written = []
    for idx in idxs:
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = cap.read()
        if not ok:
            continue
        point = traj[idx] if idx < len(traj) else None
        if point and point.get("x") is not None and point.get("y") is not None:
            x = int(round(float(point["x"])))
            y = int(round(float(point["y"])))
            cv2.circle(frame, (x, y), 16, (0, 0, 255), 3)
            cv2.putText(
                frame,
                f"idx={idx} t={point.get('t', 0):.2f} conf={point.get('confidence', 0):.2f} x={x} y={y}",
                (20, 40),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.9,
                (0, 0, 255),
                2,
                cv2.LINE_AA,
            )
        out_path = out_dir / f"evidence_{idx:05d}.jpg"
        cv2.imwrite(str(out_path), frame)
        written.append(
            {
                "frame_idx": idx,
                "image": str(out_path),
                "point": point,
            }
        )
    cap.release()
    return written


async def _run(args: argparse.Namespace) -> int:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.out_dir) / f"mouseflow_real_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)
    video_path = out_dir / "desktop_capture.mp4"

    print(f"recording={video_path}")
    start = time.time()

    ffmpeg_proc = subprocess.Popen(
        [
            "ffmpeg",
            "-y",
            "-f",
            "gdigrab",
            "-draw_mouse",
            "1",
            "-framerate",
            str(int(args.fps)),
            "-i",
            "desktop",
            "-t",
            str(float(args.duration)),
            "-pix_fmt",
            "yuv420p",
            str(video_path),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    time.sleep(0.25)
    if args.auto_move:
        _move_mouse(float(args.duration))
    rc = ffmpeg_proc.wait()
    if rc != 0 or not video_path.exists() or video_path.stat().st_size == 0:
        print("ffmpeg_failed")
        return 2

    module = MouseFlowModule()
    result = await module.process(
        input_data={"video_path": str(video_path)},
        config={
            "match_threshold": float(args.match_threshold),
            "smooth_alpha": float(args.smooth_alpha),
            "click_stationary_frames": int(args.click_stationary_frames),
            "click_speed_threshold": float(args.click_speed_threshold),
            "click_min_confidence": float(args.click_min_confidence),
            "template_scales": [0.7, 0.85, 1.0, 1.15, 1.3, 1.5],
        },
        context={},
    )

    result_path = out_dir / "mouseflow_result.json"
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    evidence = _save_evidence_frames(video_path, result, out_dir, samples=int(args.evidence_samples))
    evidence_path = out_dir / "evidence.json"
    evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")

    end = time.time()
    print(f"analyze_seconds={end - start:.3f}")
    print(f"video_bytes={video_path.stat().st_size}")
    print(f"result={result_path}")
    print(f"evidence={evidence_path}")
    print(f"confidence={result.get('confidence', 0):.4f} frames={result.get('frames')} fps={result.get('fps')}")

    clicks = result.get("clicks") or []
    print(f"clicks={len(clicks)}")
    for c in clicks[:3]:
        print(f"click t={c.get('t'):.2f} x={c.get('x')} y={c.get('y')} conf={c.get('confidence'):.3f} type={c.get('type')}")

    if evidence:
        head = evidence[0]
        p = head.get("point") or {}
        print(f"sample_frame={head.get('image')}")
        print(f"sample_point t={p.get('t')} x={p.get('x')} y={p.get('y')} conf={p.get('confidence')}")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--duration", type=float, default=5.0)
    ap.add_argument("--fps", type=int, default=15)
    ap.add_argument("--auto-move", action="store_true")
    ap.add_argument("--out-dir", type=str, default="g:/TaijiOS_Backup/reports")
    ap.add_argument("--match-threshold", type=float, default=0.45)
    ap.add_argument("--smooth-alpha", type=float, default=0.35)
    ap.add_argument("--click-stationary-frames", type=int, default=6)
    ap.add_argument("--click-speed-threshold", type=float, default=2.0)
    ap.add_argument("--click-min-confidence", type=float, default=0.45)
    ap.add_argument("--evidence-samples", type=int, default=8)
    args = ap.parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()

