from .nodes.model_c import AdCreatorModelCGenerate


NODE_CLASS_MAPPINGS = {
    "AdCreatorModelCGenerate": AdCreatorModelCGenerate,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "AdCreatorModelCGenerate": "Ad Creator · model-c v1",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
