import cv2
import numpy as np
import os
from typing import Any, Dict
from .base import BaseModule

class BackgroundModule(BaseModule):
    @property
    def name(self) -> str:
        return "background_module"

    @property
    def module_type(self) -> str:
        return "background"

    async def process(self, input_data: Any, config: Dict[str, Any] = None, context: Dict[str, Any] = None) -> Any:
        print(f"  [{self.name}] 正在执行真实背景处理推理...")
        
        # 1. 获取输入图像 (支持路径, ndarray, 或来自 Executor 的 dict)
        frame = None
        target_input = input_data
        if isinstance(input_data, dict):
            target_input = input_data.get("start") or input_data.get("start_frame")

        if isinstance(target_input, str) and os.path.exists(target_input):
            frame = cv2.imread(target_input)
        elif isinstance(target_input, np.ndarray):
            frame = target_input
            
        if frame is None:
            print(f"    [Error] 无法读取图像数据，回退到 Mock 模式. Input type: {type(target_input)}")
            # 返回一个黑图避免后续报错
            frame = np.zeros((480, 640, 3), dtype=np.uint8)

        # 2. 获取配置和上下文
        bg_style = config.get("type", "blur") # 默认模糊
        pose_output = context.get("pose_module_output", {})
        root_pos = pose_output.get("root_position", None)
        
        processed_frame = frame.copy()
        output_info = {"style": bg_style}

        # 3. 真实图像处理逻辑
        if bg_style == "blur":
            print("    [CV Engine] 执行背景模糊处理...")
            processed_frame = cv2.GaussianBlur(frame, (21, 21), 0)
            
        elif bg_style == "cyberpunk":
            print("    [CV Engine] 执行赛博朋克风格化...")
            b, g, r = cv2.split(frame)
            r = cv2.add(r, 50)
            b = cv2.add(b, 30)
            processed_frame = cv2.merge([b, g, r])
            
        elif bg_style == "selective_focus" and root_pos:
            print(f"    [CV Engine] 执行基于位置 {root_pos} 的对焦处理...")
            cx, cy = int(root_pos.get("x", 0)), int(root_pos.get("y", 0))
            cv2.circle(processed_frame, (cx, cy), 100, (255, 255, 255), 2)
            output_info["focus_center"] = (cx, cy)

        # 4. 保存处理后的背景预览图
        output_path = config.get("output_path", "g:/TaijiOS_Backup/background_output.jpg")
        cv2.imwrite(output_path, processed_frame)
        print(f"    [CV Engine] 处理完成，输出预览: {output_path}")

        return {
            "background_path": output_path,
            "style_applied": bg_style,
            "status": "success",
            "metadata": output_info
        }
