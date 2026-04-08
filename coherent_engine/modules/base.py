# modules/base.py
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

class BaseModule(ABC):
    """
    所有功能模块的基类
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """模块名称，如 'expression_module'"""
        pass

    @property
    @abstractmethod
    def module_type(self) -> str:
        """模块类型，如 'expression', 'pose', 'background'"""
        pass

    @abstractmethod
    async def process(self, 
                      input_data: Any, 
                      config: Dict[str, Any] = None,
                      context: Dict[str, Any] = None) -> Any:
        """
        核心处理逻辑
        
        Args:
            input_data: 输入数据（如图像帧、特征点等）
            config: 模块配置参数
            context: 全局上下文（包含锁点信息、其他模块输出等）
            
        Returns:
            处理结果
        """
        pass

    async def initialize(self):
        """初始化资源（如加载模型），可选"""
        pass

    async def cleanup(self):
        """释放资源，可选"""
        pass
