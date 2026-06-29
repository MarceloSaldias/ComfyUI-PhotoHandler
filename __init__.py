"""ComfyUI custom node package for PhotoHandler."""

from .photohandler_node import (
    PhotoHandlerDescription,
    PhotoHandlerDescriptionByImage,
)

NODE_CLASS_MAPPINGS = {
    "PhotoHandlerDescription": PhotoHandlerDescription,
    "PhotoHandlerDescriptionByImage": PhotoHandlerDescriptionByImage,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "PhotoHandlerDescription": "PhotoHandler Description",
    "PhotoHandlerDescriptionByImage": "PhotoHandler Description (Image)",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
