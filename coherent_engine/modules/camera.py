from typing import Any, Dict
from .base import BaseModule
import asyncio

class CameraModule(BaseModule):
    @property
    def name(self) -> str:
        return "camera_module"

    @property
    def module_type(self) -> str:
        return "camera"

    async def process(self, input_data: Any, config: Dict[str, Any] = None, context: Dict[str, Any] = None) -> Any:
        print(f"  [{self.name}] Calculating camera movement...")
        
        # Context Awareness: Adjust focus based on Pose module output
        look_at = {"x": 0, "y": 0, "z": 0}
        
        if context:
            # The orchestrator stores results by module name_output
            pose_output = context.get("pose_module_output")
            if pose_output and isinstance(pose_output, dict):
                root_pos = pose_output.get("root_position")
                if root_pos:
                    print(f"    [Context Aware] Detected person at: {root_pos}, auto-adjusting focus.")
                    look_at = root_pos
        
        await asyncio.sleep(0.1)
        return {
            "camera_matrix": "mock_matrix_data",
            "focus_point": look_at
        }
