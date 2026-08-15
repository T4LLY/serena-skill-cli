class SerenaSkillError(RuntimeError):
    """Base error presented by the CLI."""


class ProjectNotFoundError(SerenaSkillError):
    pass


class ServerStartError(SerenaSkillError):
    pass


class ToolUnavailableError(SerenaSkillError):
    pass
