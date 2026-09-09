"""模型适配层：统一各家模型接口，并支持注入脚本化实现用于测试。"""

from .base import ModelProvider, ProviderError
from .openai_compat import OpenAICompatProvider
from .scripted import ScriptedProvider

__all__ = ["ModelProvider", "ProviderError", "OpenAICompatProvider", "ScriptedProvider"]
