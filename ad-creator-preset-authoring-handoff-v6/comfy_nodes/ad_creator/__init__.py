from .nodes import AdCreatorExtension


WEB_DIRECTORY = "./js"


async def comfy_entrypoint() -> AdCreatorExtension:
    return AdCreatorExtension()


__all__ = ["WEB_DIRECTORY", "comfy_entrypoint"]
