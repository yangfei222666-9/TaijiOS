# modules/validator.py
"""
VisualValidator - 视觉校验模块 v0

第一版策略：规则打分，不依赖外部模型，优先保证稳定输出可解释的失败原因。

评分维度：
1. character_consistency - 角色一致性（颜色直方图 + 面积占比）
2. style_consistency     - 风格一致性（色调/亮度/饱和度统计）
3. shot_continuity       - 镜头连贯性（主体位置漂移）
4. subtitle_safety       - 文案可读性（安全区遮挡检测）

输出格式：
{
    "score": 0.0-1.0,
    "passed": bool,
    "checks": {
        "character_consistency": {"score": float, "passed": bool, "reason": str},
        "style_consistency":     {"score": float, "passed": bool, "reason": str},
        "shot_continuity":       {"score": float, "passed": bool, "reason": str},
        "subtitle_safety":       {"score": float, "passed": bool, "reason": str},
    },
    "failed_checks": [str],
    "fix_suggestions": [str]
}
"""

from typing import Any, Dict, List, Optional, Tuple
import numpy as np
from .base import BaseModule


# --------------------------------------------------------------------------- #
# 权重配置（四项合计 = 1.0）
# --------------------------------------------------------------------------- #
WEIGHTS = {
    "character_consistency": 0.35,
    "style_consistency":     0.30,
    "shot_continuity":       0.25,
    "subtitle_safety":       0.10,
}

PASS_THRESHOLD = 0.85  # 整体分阈值
CHECK_THRESHOLD = 0.80  # 单项分阈值


# --------------------------------------------------------------------------- #
# 工具函数
# --------------------------------------------------------------------------- #

def _to_numpy(frame: Any) -> Optional[np.ndarray]:
    """将输入统一转为 HxWxC uint8 numpy 数组，失败返回 None"""
    if frame is None:
        return None
    if isinstance(frame, np.ndarray):
        return frame.astype(np.uint8) if frame.dtype != np.uint8 else frame
    try:
        import cv2  # type: ignore
        if isinstance(frame, (str, bytes)):
            buf = np.frombuffer(frame, dtype=np.uint8) if isinstance(frame, bytes) else None
            if buf is not None:
                return cv2.imdecode(buf, cv2.IMREAD_COLOR)
        return None
    except Exception:
        return None


def _color_histogram(img: np.ndarray, bins: int = 32) -> np.ndarray:
    """计算 HSV 颜色直方图（归一化）"""
    try:
        import cv2  # type: ignore
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        h = cv2.calcHist([hsv], [0], None, [bins], [0, 180]).flatten()
        s = cv2.calcHist([hsv], [1], None, [bins], [0, 256]).flatten()
        hist = np.concatenate([h, s])
        total = hist.sum()
        return hist / total if total > 0 else hist
    except Exception:
        return np.zeros(bins * 2)


def _histogram_similarity(h1: np.ndarray, h2: np.ndarray) -> float:
    """巴氏系数相似度 [0, 1]"""
    bc = np.sum(np.sqrt(h1 * h2))
    return float(np.clip(bc, 0.0, 1.0))


def _brightness_saturation_stats(img: np.ndarray) -> Tuple[float, float]:
    """返回 (mean_brightness, mean_saturation)，范围 [0, 1]"""
    try:
        import cv2  # type: ignore
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV).astype(float)
        brightness = hsv[:, :, 2].mean() / 255.0
        saturation = hsv[:, :, 1].mean() / 255.0
        return brightness, saturation
    except Exception:
        return 0.5, 0.5


def _dominant_region_center(img: np.ndarray) -> Tuple[float, float]:
    """用亮度重心估算主体位置，返回归一化 (cx, cy)"""
    try:
        gray = img.mean(axis=2)
        h, w = gray.shape
        ys, xs = np.mgrid[0:h, 0:w]
        total = gray.sum()
        if total == 0:
            return 0.5, 0.5
        cx = float((xs * gray).sum() / total) / w
        cy = float((ys * gray).sum() / total) / h
        return cx, cy
    except Exception:
        return 0.5, 0.5


# --------------------------------------------------------------------------- #
# 四个检查项
# --------------------------------------------------------------------------- #

def check_character_consistency(
    frames: List[np.ndarray],
    reference: Optional[np.ndarray] = None,
) -> Dict[str, Any]:
    """
    角色一致性：比较所有帧与参考帧（或第一帧）的颜色直方图相似度。
    score = 所有帧与参考帧相似度的均值。
    """
    if not frames:
        return {"score": 1.0, "passed": True, "reason": "no frames to check"}

    ref = reference if reference is not None else frames[0]
    ref_hist = _color_histogram(ref)

    scores = []
    for i, f in enumerate(frames):
        sim = _histogram_similarity(ref_hist, _color_histogram(f))
        scores.append(sim)

    score = float(np.mean(scores))
    passed = score >= CHECK_THRESHOLD
    worst_idx = int(np.argmin(scores))
    reason = (
        f"OK (mean={score:.3f})"
        if passed
        else f"frame[{worst_idx}] similarity={scores[worst_idx]:.3f} < {CHECK_THRESHOLD}"
    )
    return {"score": score, "passed": passed, "reason": reason}


def check_style_consistency(frames: List[np.ndarray]) -> Dict[str, Any]:
    """
    风格一致性：检查各帧亮度/饱和度的标准差。
    标准差越小 → 风格越一致。
    """
    if not frames:
        return {"score": 1.0, "passed": True, "reason": "no frames to check"}

    brightness_list, saturation_list = [], []
    for f in frames:
        b, s = _brightness_saturation_stats(f)
        brightness_list.append(b)
        saturation_list.append(s)

    b_std = float(np.std(brightness_list))
    s_std = float(np.std(saturation_list))

    # 标准差 0 → score 1.0；标准差 ≥ 0.2 → score 0.0
    b_score = float(np.clip(1.0 - b_std / 0.2, 0.0, 1.0))
    s_score = float(np.clip(1.0 - s_std / 0.2, 0.0, 1.0))
    score = (b_score + s_score) / 2.0

    passed = score >= CHECK_THRESHOLD
    reason = (
        f"OK (brightness_std={b_std:.3f}, saturation_std={s_std:.3f})"
        if passed
        else f"style drift detected: brightness_std={b_std:.3f}, saturation_std={s_std:.3f}"
    )
    return {"score": score, "passed": passed, "reason": reason}


def check_shot_continuity(frames: List[np.ndarray]) -> Dict[str, Any]:
    """
    镜头连贯性：检查相邻帧主体位置漂移。
    漂移距离 > 0.3（归一化）视为跳变。
    """
    if len(frames) < 2:
        return {"score": 1.0, "passed": True, "reason": "not enough frames to check"}

    centers = [_dominant_region_center(f) for f in frames]
    dists = []
    for i in range(1, len(centers)):
        dx = centers[i][0] - centers[i - 1][0]
        dy = centers[i][1] - centers[i - 1][1]
        dists.append(float(np.sqrt(dx ** 2 + dy ** 2)))

    max_drift = float(np.max(dists))
    mean_drift = float(np.mean(dists))
    # 漂移 0 → score 1.0；漂移 ≥ 0.3 → score 0.0
    score = float(np.clip(1.0 - max_drift / 0.3, 0.0, 1.0))
    passed = score >= CHECK_THRESHOLD
    worst_idx = int(np.argmax(dists))
    reason = (
        f"OK (max_drift={max_drift:.3f}, mean={mean_drift:.3f})"
        if passed
        else f"jump cut at frame[{worst_idx}→{worst_idx+1}]: drift={dists[worst_idx]:.3f}"
    )
    return {"score": score, "passed": passed, "reason": reason}


def check_subtitle_safety(
    frames: List[np.ndarray],
    safe_area: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """
    文案安全区检测：检查字幕区域（底部 15%）是否被非黑色像素占据过多。
    safe_area 格式：{top_pct, bottom_pct, left_pct, right_pct}（百分比，0-50）
    """
    if not frames:
        return {"score": 1.0, "passed": True, "reason": "no frames to check"}

    bottom_pct = (safe_area or {}).get("bottom_pct", 15) / 100.0
    violation_rates = []

    for f in frames:
        h, w = f.shape[:2]
        subtitle_row = int(h * (1.0 - bottom_pct))
        region = f[subtitle_row:, :]
        # 判断亮度 > 30 的像素比例（非纯黑 = 可能遮挡字幕）
        bright_ratio = float((region.mean(axis=2) > 30).mean())
        violation_rates.append(bright_ratio)

    mean_violation = float(np.mean(violation_rates))
    # violation > 0.6 → 字幕区域被占满，扣分
    score = float(np.clip(1.0 - mean_violation * 0.5, 0.0, 1.0))
    passed = score >= CHECK_THRESHOLD
    reason = (
        f"OK (safe_area_occupation={mean_violation:.2%})"
        if passed
        else f"subtitle zone congested: mean occupation={mean_violation:.2%}"
    )
    return {"score": score, "passed": passed, "reason": reason}


# --------------------------------------------------------------------------- #
# 修复建议生成
# --------------------------------------------------------------------------- #

FIX_SUGGESTIONS: Dict[str, str] = {
    "character_consistency": "强化角色不变量约束（hair/outfit/main_colors），提高锁定权重，重做该镜头",
    "style_consistency":     "固化 style token 或参考图，减少生成随机性（降低 temperature/cfg_scale），重做该镜头",
    "shot_continuity":       "调整镜头模板过渡参数，增加衔接镜头或调整相邻镜头景别，重做相邻镜头",
    "subtitle_safety":       "检查字幕位置配置（safe_area.bottom_pct），确保字幕不被前景遮挡",
}


# --------------------------------------------------------------------------- #
# ValidatorModule（BaseModule 实现）
# --------------------------------------------------------------------------- #

class VisualValidatorModule(BaseModule):
    """
    视觉校验模块，可注册到 ModuleOrchestrator。

    input_data 期望格式：
    {
        "frames": List[np.ndarray],          # 必填：待校验帧序列
        "reference_frame": np.ndarray | None, # 可选：角色参考帧
        "safe_area": Dict | None,             # 可选：字幕安全区配置
    }
    """

    @property
    def name(self) -> str:
        return "visual_validator"

    @property
    def module_type(self) -> str:
        return "validator"

    async def process(
        self,
        input_data: Any,
        config: Dict[str, Any] = None,
        context: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        frames_raw = input_data.get("frames", []) if isinstance(input_data, dict) else []
        reference_raw = input_data.get("reference_frame") if isinstance(input_data, dict) else None
        safe_area = input_data.get("safe_area") if isinstance(input_data, dict) else None

        frames = [f for f in (_to_numpy(f) for f in frames_raw) if f is not None]
        reference = _to_numpy(reference_raw)

        return validate(frames=frames, reference=reference, safe_area=safe_area)


# --------------------------------------------------------------------------- #
# 顶层便捷函数
# --------------------------------------------------------------------------- #

def validate(
    frames: List[np.ndarray],
    reference: Optional[np.ndarray] = None,
    safe_area: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """
    对一组帧执行全量校验，返回标准化结果字典。

    Args:
        frames:     待校验的帧序列（numpy 数组列表）
        reference:  角色参考帧（可选，默认用 frames[0]）
        safe_area:  字幕安全区配置（可选）

    Returns:
        标准化校验结果（见模块文档字符串）
    """
    checks = {
        "character_consistency": check_character_consistency(frames, reference),
        "style_consistency":     check_style_consistency(frames),
        "shot_continuity":       check_shot_continuity(frames),
        "subtitle_safety":       check_subtitle_safety(frames, safe_area),
    }

    # 加权总分
    score = sum(
        checks[k]["score"] * WEIGHTS[k]
        for k in WEIGHTS
    )
    score = float(np.clip(score, 0.0, 1.0))
    passed = score >= PASS_THRESHOLD

    failed_checks = [k for k, v in checks.items() if not v["passed"]]
    fix_suggestions = [FIX_SUGGESTIONS[k] for k in failed_checks]

    return {
        "score": round(score, 4),
        "passed": passed,
        "checks": checks,
        "failed_checks": failed_checks,
        "fix_suggestions": fix_suggestions,
    }
