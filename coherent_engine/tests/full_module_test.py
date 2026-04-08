# coherent_engine/tests/full_module_test.py
import asyncio
import json
from coherent_engine.core.cache import LockPointCache
from coherent_engine.core.aligner import FirstLastAligner
from coherent_engine.core.tweener import AsyncTweener
from coherent_engine.core.orchestrator import ModuleOrchestrator
from coherent_engine.core.executor import PipelineExecutor

# 导入所有功能模块
from coherent_engine.modules.expression import ExpressionModule
from coherent_engine.modules.pose import PoseModule
from coherent_engine.modules.background import BackgroundModule
from coherent_engine.modules.voice import VoiceModule
from coherent_engine.modules.camera import CameraModule

async def main():
    print("=== Coherent Engine: Full Module Integration Test ===\n")

    # 1. 初始化核心组件
    # 自动降级：如果没有 Redis，LockPointCache 会自动使用本地内存
    cache = LockPointCache()
    aligner = FirstLastAligner(cache)
    tweener = AsyncTweener()
    orchestrator = ModuleOrchestrator()

    # 2. 注册所有模块
    # 模拟依赖关系：
    # - PoseModule 是基础，先执行
    # - ExpressionModule 依赖 Pose (假设需要头部姿态)
    # - CameraModule 依赖 Pose (需要跟随人物)
    # - BackgroundModule 独立
    # - VoiceModule 独立
    
    pose_mod = PoseModule()
    orchestrator.register_module(pose_mod)
    
    expr_mod = ExpressionModule()
    orchestrator.register_module(expr_mod, depends_on=[pose_mod.name])
    
    cam_mod = CameraModule()
    orchestrator.register_module(cam_mod, depends_on=[pose_mod.name])
    
    bg_mod = BackgroundModule()
    orchestrator.register_module(bg_mod)
    
    voice_mod = VoiceModule()
    orchestrator.register_module(voice_mod)

    print(f"Registered Modules: {list(orchestrator._modules.keys())}")
    print(f"Dependencies: {orchestrator._dependencies}\n")

    # 3. 组装执行器
    executor = PipelineExecutor(aligner, orchestrator, tweener)

    # 4. 准备测试数据
    start_frame = "mock_start_frame.jpg"
    end_frame = "mock_end_frame.jpg"
    
    workflow_config = {
        "frames": 15,
        "pose_module": {"style": "dance"},
        "expression_module": {"intensity": 0.8},
        "camera_module": {"movement": "zoom_in"},
        "background_module": {"type": "cyberpunk_city"},
        "voice_module": {"text": "Hello, welcome to TaijiOS Coherent Engine."}
    }

    # 5. 运行全流程
    try:
        print(">>> Starting Execution Pipeline...")
        result = await executor.run(start_frame, end_frame, workflow_config)
        
        print("\n>>> Execution Completed Successfully!")
        print("-" * 40)
        
        # 验证锁点
        print(f"Lock Points: {len(result['lock_points'])} extracted")
        
        # 验证模块输出
        print("Module Outputs:")
        for mod, out in result['module_results'].items():
            if mod == "initial_input": continue
            # 简化输出显示
            out_str = str(out)
            if len(out_str) > 50: out_str = out_str[:47] + "..."
            print(f"  - {mod}: {out_str}")
            
        # 验证补间序列
        print("Tween Sequences:")
        for seq_name, seq_data in result['render_sequence'].items():
            print(f"  - {seq_name}: {len(seq_data)} frames generated")
            
        print("-" * 40)
        print("✅ Full module integration test PASSED.")

    except Exception as e:
        print(f"\n❌ Execution FAILED: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await cache.close()

if __name__ == "__main__":
    asyncio.run(main())
