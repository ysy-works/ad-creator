from .nodes.model_c import AdCreatorModelCGenerate
from .nodes.openai_image import AdCreatorOpenAIImageGenerate


NODE_CLASS_MAPPINGS = {
    "AdCreatorModelCGenerate": AdCreatorModelCGenerate,
    "AdCreatorOpenAIImageGenerate": AdCreatorOpenAIImageGenerate,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "AdCreatorModelCGenerate": "Ad Creator · model-c v1",
    "AdCreatorOpenAIImageGenerate": "Ad Creator · OpenAI GPT Image 2",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
