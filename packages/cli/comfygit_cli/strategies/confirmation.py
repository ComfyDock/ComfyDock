"""CLI-owned confirmation strategies for interactive commands."""

from comfygit_core.confirmation import AutoConfirmStrategy, ConfirmationStrategy

__all__ = [
    "AutoConfirmStrategy",
    "ConfirmationStrategy",
    "InteractiveConfirmStrategy",
]


class InteractiveConfirmStrategy(ConfirmationStrategy):
    """Ask the terminal user to confirm node operations."""

    def confirm_update(self, node_name: str, current_version: str, new_version: str) -> bool:
        response = input(
            f"Update '{node_name}' from {current_version} -> {new_version}? (Y/n): "
        )
        return response.lower() != "n"

    def confirm_replace_dev_node(self, node_name: str, current_version: str, new_version: str) -> bool:
        print(f"'{node_name}' is a development node (local changes may exist)")
        response = input(
            f"Replace with registry version {new_version}? This will delete local changes. (y/N): "
        )
        return response.lower() == "y"
