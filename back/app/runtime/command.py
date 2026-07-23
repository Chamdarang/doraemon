from __future__ import annotations


VALUE_FLAGS = {"--port", "-p"}
VALUE_PREFIXES = ("--port=", "-p=", "--server.port=", "-Dserver.port=")


def replace_command_port(
    command: list[str],
    port: int,
    previous_port: int | None = None,
) -> list[str]:
    """Return a command with common framework port arguments updated."""
    updated = list(command)
    previous = str(previous_port) if previous_port is not None else None
    for index, argument in enumerate(updated):
        if index > 0 and updated[index - 1] in VALUE_FLAGS:
            updated[index] = str(port)
            continue
        prefix = next((item for item in VALUE_PREFIXES if argument.startswith(item)), None)
        if prefix:
            updated[index] = f"{prefix}{port}"
            continue
        if previous is None or previous == str(port):
            continue
        if argument == previous:
            updated[index] = str(port)
        elif argument.endswith(f":{previous}"):
            updated[index] = f"{argument[:-len(previous)]}{port}"
    return updated
