"""Confirmation strategy contracts for core operations."""

from abc import ABC, abstractmethod


class ConfirmationStrategy(ABC):
    """Strategy for confirming user actions."""

    @abstractmethod
    def confirm_update(self, node_name: str, current_version: str, new_version: str) -> bool:
        """Ask user to confirm a node update.

        Args:
            node_name: Name of the node
            current_version: Current version
            new_version: New version

        Returns:
            True if user confirms, False otherwise
        """
        pass

    def confirm_replace_dev_node(self, node_name: str, current_version: str, new_version: str) -> bool:
        """Ask user to confirm replacing a development node.

        Args:
            node_name: Name of the development node
            current_version: Current version ('dev')
            new_version: New version to install

        Returns:
            True if user confirms, False otherwise
        """
        # Default: use confirm_update for backward compatibility
        return self.confirm_update(node_name, current_version, new_version)


class AutoConfirmStrategy(ConfirmationStrategy):
    """Always confirm without asking."""

    def confirm_update(self, node_name: str, current_version: str, new_version: str) -> bool:
        return True
