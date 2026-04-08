import asyncio
import json
import numpy as np
import cv2
from coherent_engine.core.cache import LockPointCache
from coherent_engine.core.aligner import FirstLastAligner
from coherent_engine.core.tweener import AsyncTweener
from coherent_engine.core.orchestrator import ModuleOrchestrator
from coherent_engine.core.executor import PipelineExecutor

from coherent_engine.modules.expression import ExpressionModule
from coherent_engine.modules.pose import PoseModule
from coherent_engine.modules.background import BackgroundModule
from coherent_engine.modules.voice import VoiceModule
from coherent_engine.modules.camera import CameraModule

async def main():
    print("=== Coherent Engine: Real CV Integration Test ===\n")

    # 1. Create Real Input (Synthetic Image)
    # 512x512 black image
    start_frame = np.zeros((512, 512, 3), dtype=np.uint8)
    # Draw a white circle at (350, 200) - this is our "Actor"
    cv2.circle(start_frame, (350, 200), 30, (255, 255, 255), -1)
    
    initial_input = {
        "start_frame": start_frame,
        "end_frame": start_frame.copy(),
        "audio_script": "Hello, world! I see you."
    }

    # 2. Initialize Modules
    orchestrator = ModuleOrchestrator()
    orchestrator.register_module(PoseModule())
    orchestrator.register_module(ExpressionModule(), depends_on=["pose_module"])
    orchestrator.register_module(CameraModule(), depends_on=["pose_module"]) # Camera depends on Pose
    orchestrator.register_module(BackgroundModule())
    orchestrator.register_module(VoiceModule())

    # 3. Setup Executor
    cache = LockPointCache()
    # Mock Redis connection or use fallback
    aligner = FirstLastAligner(cache)
    tweener = AsyncTweener()
    # Correct order: aligner, orchestrator, tweener
    executor = PipelineExecutor(aligner, orchestrator, tweener)

    # 4. Run
    print(">>> Starting Execution Pipeline...")
    try:
        # Correct arguments: start_frame, end_frame, config
        # Note: We pass audio_script in config, and PoseModule reads 'start' from input_data
        results = await executor.run(
            start_frame=initial_input["start_frame"],
            end_frame=initial_input["end_frame"],
            workflow_config={"audio_script": "Hello"}
        )
        
        # NOTE: PipelineExecutor.run returns {"module_results": ...}
        module_results = results.get("module_results", {})
        
        print("\n>>> Execution Completed Successfully!")
        print("-" * 40)
        
        # Verify CV Result
        pose_res = module_results.get("pose_module")
        if pose_res:
            root = pose_res.get("root_position")
            print(f"Pose Detection: {root}")
            # Expected: around x=350, y=200
            if abs(root['x'] - 350) < 5 and abs(root['y'] - 200) < 5:
                print(" CV Detection ACCURATE")
            else:
                print(" CV Detection FAILED")
        else:
             print(" Pose Module Result NOT FOUND")
        
        # Verify Camera Context Awareness
        cam_res = module_results.get("camera_module")
        if cam_res:
            focus = cam_res.get("focus_point")
            print(f"Camera Focus: {focus}")
            if focus == root:
                 print(" Camera Context Injection SUCCESS")
            else:
                 print(" Camera Context Injection FAILED")
        else:
             print(" Camera Module Result NOT FOUND")
                 
    except Exception as e:
        print(f"\n Execution Failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
