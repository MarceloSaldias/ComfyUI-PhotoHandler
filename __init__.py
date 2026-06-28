"""ComfyUI custom node package for PhotoHandler."""

from .photohandler_node import PhotoHandlerDescription

NODE_CLASS_MAPPINGS = {
    "PhotoHandlerDescription": PhotoHandlerDescription,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "PhotoHandlerDescription": "PhotoHandler Description",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
