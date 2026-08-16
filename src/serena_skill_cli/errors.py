class SerenaSkillError(RuntimeError):
    """Base error presented by the CLI."""


class ProjectNotFoundError(SerenaSkillError):
    pass


class ServerStartError(SerenaSkillError):
    pass


class MCPConnectionError(SerenaSkillError):
    pass


class MCPCallError(SerenaSkillError):
    """A request had started, so retrying a mutating tool may be unsafe."""


class SerenaToolError(SerenaSkillError):
    pass


class ToolUnavailableError(SerenaSkillError):
    pass
