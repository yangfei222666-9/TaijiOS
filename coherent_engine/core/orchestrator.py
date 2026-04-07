# core/orchestrator.py
import asyncio
from typing import Dict, Any, List, Set
from coherent_engine.modules.base import BaseModule

class ModuleOrchestrator:
    """
    模块调度器：负责解析依赖关系并调度模块执行
    """
    def __init__(self):
        self._modules: Dict[str, BaseModule] = {}
        self._dependencies: Dict[str, Set[str]] = {}

    def register_module(self, module: BaseModule, depends_on: List[str] = None):
        """注册模块及其依赖"""
        self._modules[module.name] = module
        self._dependencies[module.name] = set(depends_on or [])

    async def execute_workflow(self, 
                             initial_input: Any, 
                             workflow_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行完整工作流
        TODO: 目前是简单的拓扑排序执行，未来支持更复杂的并行流
        """
        results = {"initial_input": initial_input}
        context = {"workflow_id": "temp_id"}  # TODO: 接入真实上下文

        # 1. 计算执行顺序 (简化版拓扑排序)
        execution_order = self._resolve_dependencies()
        
        # 2. 按序执行
        for module_name in execution_order:
            if module_name not in self._modules:
                print(f"Warning: Module {module_name} not found, skipping.")
                continue
                
            module = self._modules[module_name]
            config = workflow_config.get(module_name, {})
            
            # 准备输入数据：默认使用上一个模块的输出，或者初始输入
            # TODO: 实现更灵活的数据流路由
            input_data = initial_input
            
            print(f"Running module: {module_name}...")
            try:
                output = await module.process(input_data, config, context)
                results[module_name] = output
                # 更新 context 供后续模块使用
                context[f"{module_name}_output"] = output
            except Exception as e:
                print(f"Error executing {module_name}: {e}")
                # TODO: 错误处理策略 (重试/跳过/中断)
                raise e

        return results

    def _resolve_dependencies(self) -> List[str]:
        """
        解析依赖，返回执行顺序列表
        TODO: 处理循环依赖检测
        """
        order = []
        visited = set()
        temp_visited = set() # 用于检测循环

        def visit(node):
            if node in visited:
                return
            if node in temp_visited:
                raise ValueError(f"Circular dependency detected: {node}")
            
            temp_visited.add(node)
            
            # 先访问依赖项
            for dep in self._dependencies.get(node, []):
                visit(dep)
            
            temp_visited.remove(node)
            visited.add(node)
            order.append(node)

        for module_name in self._modules:
            visit(module_name)
            
        return order
