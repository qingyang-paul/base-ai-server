import re
import yaml
from enum import Enum
from pathlib import Path
from typing import Dict, List, Tuple
from pydantic import BaseModel

class SystemPromptScene(str, Enum):
    PAL = "pal"
    SESSION_TITLE = "session_title"
    SESSION_COVER = "session_cover"

class PromptMeta(BaseModel):
    scene: SystemPromptScene     
    version: str        # 版本号，例如: "1.0.0"
    description: str    # 内部备注：这个版本的 Prompt 改了什么
    content: str        # 【核心改进】：把读取到的文本内容直接驻留在内存

class PromptRegistry:
    _registry: Dict[str, PromptMeta] = {}
    _is_initialized: bool = False

    @classmethod
    def initialize(cls, prompts_dir: str = "app/session_service/core/system_prompts"):
        """启动时调用：自动扫描并注册所有 Prompt"""
        if cls._is_initialized:
            return

        base_path = Path(prompts_dir)
        if not base_path.exists():
            print(f"⚠️ Prompts directory {prompts_dir} does not exist.")
            return
            
        # 遍历目录下所有 .md 文件
        for file_path in base_path.rglob("*.md"):
            cls._parse_and_register(file_path)
            
        cls._is_initialized = True
        print(f"✅ 优雅加载了 {len(cls._registry)} 个 System Prompts.")

    @classmethod
    def _parse_and_register(cls, file_path: Path):
        """解析带有 YAML Frontmatter 的 Markdown 文件"""
        content = file_path.read_text(encoding="utf-8")
        
        # 简单的 Frontmatter 解析逻辑
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                yaml_meta = yaml.safe_load(parts[1])
                body = parts[2].strip()
                
                meta = PromptMeta(
                    scene=SystemPromptScene(yaml_meta["scene"]),
                    version=str(yaml_meta["version"]),
                    description=yaml_meta.get("description", ""),
                    content=body
                )
                
                key = f"{meta.scene.value}:{meta.version}"
                cls._registry[key] = meta

    @classmethod
    def get_prompt_content(cls, scene: SystemPromptScene, version: str) -> str:
        """获取具体的 Prompt 文本内容，O(1) 内存读取，无磁盘 I/O"""
        key = f"{scene.value}:{version}"
        if key not in cls._registry:
            raise ValueError(f"Prompt {key} not found!")
        return cls._registry[key].content

    @classmethod
    def get_prompt(cls, scene: SystemPromptScene, version: str) -> str:
        """获取具体的 Prompt 文本内容的快捷方式"""
        return cls.get_prompt_content(scene, version)

    @classmethod
    def get_latest_prompt(cls, scene: SystemPromptScene) -> PromptMeta:
        """获取指定场景下的最新版本 Prompt"""
        scene_prompts = [
            meta for meta in cls._registry.values() 
            if meta.scene == scene
        ]
        
        if not scene_prompts:
            raise ValueError(f"No prompts registered for scene: {scene}")

        def parse_version(version_str: str) -> Tuple[int, ...]:
            clean_v = re.sub(r'^[vV]', '', version_str)
            try:
                return tuple(map(int, clean_v.split('.')))
            except ValueError:
                return (0,) 

        latest_meta = max(scene_prompts, key=lambda x: parse_version(x.version))
        return latest_meta

    @classmethod
    def register(cls, meta: PromptMeta):
        key = f"{meta.scene.value}:{meta.version}"
        cls._registry[key] = meta


# 初始化注册表，加入自带的测试/默认系统 prompt
PromptRegistry.register(PromptMeta(
    scene=SystemPromptScene.PAL,
    version="v1.0", 
    description="初始版本的聊天人设",
    content="You are a helpful PAL..."
))
