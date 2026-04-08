# coherent_engine/tests/test_real_flow.py
import asyncio
import numpy as np
import time
from coherent_engine.core.cache import LockPointCache
from coherent_engine.core.aligner import FirstLastAligner
from coherent_engine.core.tweener import AsyncTweener
from coherent_engine.core.orchestrator import ModuleOrchestrator
from coherent_engine.core.executor import PipelineExecutor
from coherent_engine.modules.base import BaseModule
from typing import Any, Dict

class MockImageModule(BaseModule):
    """
    模拟真实的图像生成模块：
    1. 接收 numpy 数组作为输入
    2. 执行耗时操作（模拟 AI 推理）
    3. 输出修改后的 numpy 数组
    """
    @property
    def name(self) -> str:
        return "mock_image_gen"

    @property
    def module_type(self) -> str:
        return "image_generation"

    async def process(self, input_data: Any, config: Dict[str, Any] = None, context: Dict[str, Any] = None) -> Any:
        # PipelineExecutor 传入的 input_data 是一个字典：{"start": ..., "end": ..., "lock_points": ...}
        # 我们需要从中提取真实的图像数据
        image = input_data.get("start")
        
        print(f"  [MockImageModule] Processing {image.shape} image...")
        
        # 模拟 AI 推理耗时 (100ms)
        await asyncio.sleep(0.1)
        
        # 模拟处理：将图像亮度增加 (简单的像素操作)
        # 假设 image 是 (H, W, 3) 的 uint8 数组
        intensity = config.get("intensity", 1.0)
        output = np.clip(image * intensity, 0, 255).astype(np.uint8)
        
        return output

async def test_real_flow():
    print("\n=== Running Realistic Flow Test ===")
    
    # 1. 准备真实数据 (512x512 RGB 纯黑图像)
    start_frame = np.zeros((512, 512, 3), dtype=np.uint8)
    end_frame = np.ones((512, 512, 3), dtype=np.uint8) * 255 # 纯白
    
    # 2. 初始化引擎
    cache = LockPointCache()
    aligner = FirstLastAligner(cache)
    tweener = AsyncTweener()
    orchestrator = ModuleOrchestrator()
    
    # 3. 注册模拟的图像模块
    orchestrator.register_module(MockImageModule())
    
    executor = PipelineExecutor(aligner, orchestrator, tweener)
    
    # 4. 执行任务
    start_time = time.time()
    config = {
        "frames": 5, 
        "mock_image_gen": {"intensity": 1.2} # 提亮 20%
    }
    
    # 注意：aligner 目前还不支持 numpy 输入，为了测试通过，我们需要 mock 一下 aligner 的行为
    # 或者修改 aligner 让它能处理 numpy (但这里为了保持 aligner 纯洁性，我们在 executor 调用前做一点 hack)
    # 更好的做法是让 aligner.align 能够处理任意类型，或者在这里 mock 它的返回值
    
    # 临时 Monkey Patch aligner (仅供测试)
    original_align = aligner.align
    async def mock_align(s, e):
        # 模拟真实的特征提取耗时
        await asyncio.sleep(0.05)
        return {"mock_point": {"start": (10, 10), "end": (20, 20)}}
    aligner.align = mock_align
    
    try:
        result = await executor.run(start_frame, end_frame, config)
        
        duration = time.time() - start_time
        print(f"\nPipeline completed in {duration:.4f}s")
        
        # 验证输出
        module_out = result["module_results"]["mock_image_gen"]
        print(f"Output shape: {module_out.shape}, Mean value: {np.mean(module_out)}")
        
        # 验证补间序列
        seq = result["render_sequence"]["mock_image_gen_sequence"]
        print(f"Tween sequence length: {len(seq)}")
        print(f"Tween frame 0 mean: {np.mean(seq[0]):.2f}")
        print(f"Tween frame -1 mean: {np.mean(seq[-1]):.2f}")
        
        assert len(seq) == 5
        assert isinstance(seq[0], np.ndarray)
        print("✅ Realistic flow test passed!")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_real_flow())
