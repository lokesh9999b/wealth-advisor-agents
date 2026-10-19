"""Tools: the only way agents touch the outside world / raw computation.

Agents resolve tools by name from a :class:`ToolRegistry` and interact with
them through the uniform :class:`Tool` interface, so no agent ever imports a
concrete tool implementation directly.
"""

from .base import Tool, ToolRegistry, ToolResult

__all__ = ["Tool", "ToolRegistry", "ToolResult"]
