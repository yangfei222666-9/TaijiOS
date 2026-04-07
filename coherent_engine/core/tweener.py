# core/tweener.py 
import asyncio 
from typing import Any, Callable, List 

class AsyncTweener: 
    """异步补间插值引擎""" 
    def __init__(self): 
        self._tasks = [] 

    async def tween(self, 
                    start_val: Any, 
                    end_val: Any, 
                    frames: int, 
                    interpolator: Callable = None) -> List[Any]: 
        """ 
        生成补间序列（异步非阻塞） 
        interpolator: 自定义插值函数，默认线性 
        """ 
        if interpolator is None: 
            interpolator = self._linear_interpolate 

        loop = asyncio.get_event_loop() 
        # 在线程池中执行插值计算，避免阻塞事件循环 
        result = await loop.run_in_executor( 
            None, 
            self._generate_tween_sync, 
            start_val, end_val, frames, interpolator 
        ) 
        return result 

    def _generate_tween_sync(self, start, end, frames, interp): 
        """同步插值生成（在另一个线程执行）""" 
        if frames <= 1: 
            return [start] 
        step = 1.0 / (frames - 1) 
        return [interp(start, end, i * step) for i in range(frames)] 

    @staticmethod 
    def _linear_interpolate(a, b, t): 
        """简单线性插值，支持数值和向量""" 
        if isinstance(a, (int, float)) and isinstance(b, (int, float)): 
            return a + (b - a) * t 
        elif isinstance(a, (tuple, list)) and isinstance(b, (tuple, list)): 
            return [a[i] + (b[i] - a[i]) * t for i in range(len(a))] 
        elif isinstance(a, dict) and isinstance(b, dict): 
            return {k: AsyncTweener._linear_interpolate(a[k], b[k], t) for k in a} 
        return a  # 不支持的类型返回起始值 
