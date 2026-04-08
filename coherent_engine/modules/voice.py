import asyncio
import edge_tts
import os
from typing import Any, Dict
from .base import BaseModule

class VoiceModule(BaseModule):
    @property
    def name(self) -> str:
        return "voice_module"

    @property
    def module_type(self) -> str:
        return "voice"

    async def process(self, input_data: Any, config: Dict[str, Any] = None, context: Dict[str, Any] = None) -> Any:
        # 获取要合成的文本
        text = config.get("text", "你好，我是太极OS连贯引擎，很高兴见到你。")
        voice = config.get("voice", "zh-CN-XiaoxiaoNeural") # 默认使用晓晓女声
        output_path = config.get("output_path", "output_audio.mp3")

        print(f"  [{self.name}] 正在为文本执行真实 TTS 合成: '{text[:15]}...'")

        try:
            # 使用 edge-tts 进行异步合成
            communicate = edge_tts.Communicate(text, voice)
            await communicate.save(output_path)
            
            file_size = os.path.getsize(output_path)
            print(f"    [TTS Engine] 合成成功！输出文件: {output_path} ({file_size} 字节)")

            return {
                "audio_path": output_path,
                "duration": file_size / 16000, # 粗略估算时长
                "status": "success",
                "text_content": text
            }
        except Exception as e:
            print(f"    [TTS Engine] 合成失败: {e}")
            return {"status": "error", "error": str(e)}
