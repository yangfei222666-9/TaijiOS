# core/executor.py
from typing import Any, Dict, List
from .aligner import FirstLastAligner
from .orchestrator import ModuleOrchestrator
from .tweener import AsyncTweener
# from .cache import LockPointCache # TODO: 稍后集成

class PipelineExecutor:
    """
    工作流执行器：串联对齐、调度、补间全流程
    """
    def __init__(self, 
                 aligner: FirstLastAligner, 
                 orchestrator: ModuleOrchestrator, 
                 tweener: AsyncTweener):
        self.aligner = aligner
        self.orchestrator = orchestrator
        self.tweener = tweener

    async def run(self, 
                  start_frame: Any, 
                  end_frame: Any, 
                  workflow_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        运行一次完整的生成任务
        """
        print("=== Pipeline Started ===")
        
        # 1. 首尾帧对齐 & 锁点提取
        print("Step 1: Aligning frames...")
        lock_points = await self.aligner.align(start_frame, end_frame)
        print(f"  Lock points extracted: {len(lock_points)} points")

        # 2. 模块调度执行 (生成关键帧内容)
        # 将锁点注入上下文
        # TODO: 将 lock_points 传递给 orchestrator
        print("Step 2: Orchestrating modules...")
        # 这里假设模块生成的内容是基于 start_frame 的某种变换
        module_results = await self.orchestrator.execute_workflow(
            initial_input={"start": start_frame, "end": end_frame, "lock_points": lock_points},
            workflow_config=workflow_config
        )
        
        # 3. 异步补间生成 (生成中间帧)
        print("Step 3: Generating tweens...")
        # 模拟：假设某个模块输出了一组参数，我们需要对这组参数进行补间
        # 真实场景中，这里会根据 module_results 生成最终视频帧
        
        # 示例：对 'expression_module' 的输出进行补间 (假设存在)
        final_output = {}
        frames_count = workflow_config.get("frames", 30)
        
        # 简单的演示逻辑：如果模块输出了数值，我们做插值
        for mod_name, res in module_results.items():
            if mod_name == "initial_input": continue # 跳过输入数据

            # 支持数值、列表、字典以及 numpy 数组的补间
            # 这里简单判断：只要 tweener 能处理就行
            try:
                 # 假设 res 是终态，start_frame 是初态 (这里简化处理)
                 # TODO: 获取真实的初态值
                 start_val = res # 占位
                 end_val = res   # 占位
                 
                 tween_seq = await self.tweener.tween(start_val, end_val, frames_count)
                 final_output[f"{mod_name}_sequence"] = tween_seq
            except Exception as e:
                print(f"Warning: Could not tween result from {mod_name}: {e}")

        print("=== Pipeline Finished ===")
        return {
            "lock_points": lock_points,
            "module_results": module_results,
            "render_sequence": final_output # 最终渲染序列
        }
