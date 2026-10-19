"""Domain-specific exceptions for the Wealth Advisor system.

These exist so that different failure modes can be caught and handled
distinctly. By convention, *tools* catch these internally and translate them
into a non-raising ``ToolResult(ok=False, ...)`` so that agents never have to
wrap every tool call in try/except — they inspect ``ToolResult.ok`` instead.
Agents raise ``AgentError`` only for truly unexpected, unrecoverable states.
"""

from __future__ import annotations


class WealthAdvisorError(Exception):
    """Base class for all errors raised by this system."""


class DataValidationError(WealthAdvisorError):
    """Input client data is missing required fields or is malformed."""


class ToolError(WealthAdvisorError):
    """A tool failed to execute (e.g. a simulated external API error)."""


class ToolNotFoundError(WealthAdvisorError):
    """An agent requested a tool that is not present in the registry."""


class AgentError(WealthAdvisorError):
    """An agent hit an unrecoverable condition it could not degrade around."""


class PipelineError(WealthAdvisorError):
    """The orchestrated run could not complete (e.g. fatal input error)."""
