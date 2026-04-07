from typing import Dict, Any, List, Tuple
import numpy as np
import hashlib
from .cache import LockPointCache

class FirstLastAligner:
    """首尾帧对齐 & 锁点提取"""
    def __init__(self, cache: LockPointCache):
        self.cache = cache

    def _hash_frame(self, frame: Any) -> str:
        if isinstance(frame, np.ndarray):
            # Use MD5 of bytes for stability
            return hashlib.md5(frame.tobytes()).hexdigest()
        return str(hash(str(frame)))

    async def align(self, start_frame: Any, end_frame: Any) -> Dict[str, Any]:
        """
        提取首尾帧关键特征点
        实际应调用CV模型，这里用模拟数据
        """
        # 尝试从缓存读取（假设有帧ID）
        cache_key = f"{self._hash_frame(start_frame)}-{self._hash_frame(end_frame)}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        # 模拟人脸特征点检测（眼、鼻、嘴角）
        # Keep mock points for now
        start_features = {
            "left_eye": (100, 200),
            "right_eye": (300, 200),
            "nose": (200, 300),
            "mouth_left": (150, 350),
            "mouth_right": (250, 350),
        }
        end_features = {
            "left_eye": (105, 198),
            "right_eye": (305, 202),
            "nose": (202, 298),
            "mouth_left": (152, 348),
            "mouth_right": (252, 352),
        }

        # 提取锁点（这里简单取全部特征点）
        lock_points = {
            name: {"start": start_features[name], "end": end_features[name]}
            for name in start_features.keys()
        }

        # 存入缓存
        await self.cache.set(cache_key, lock_points)
        return lock_points

    def post_align(self, results: List[Any], lock_points: Dict[str, Any]) -> List[Any]:
        """根据锁点对齐所有模块生成的结果"""
        # 实际应根据锁点做仿射变换，这里简化返回
        return results
