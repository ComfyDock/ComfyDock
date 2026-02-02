"""Environment-specific logging for ComfyGit."""

import logging
import os
from collections.abc import Callable
from contextlib import contextmanager
from datetime import datetime
from functools import wraps
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .compressed_handler import CompressedDualHandler


class EnvironmentLogger:
    """Manages environment-specific logging with rotation.

    This integrates with the existing logging system by adding/removing
    handlers to the root logger, so all get_logger(__name__) calls
    in managers will automatically log to the environment file.
    """

    # Shared configuration
    MAX_BYTES = 10 * 1024 * 1024  # 10 MB per log file
    BACKUP_COUNT = 5  # Keep 5 old log files
    DETAILED_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s"

    _workspace_path: Path | None = None
    _active_handler: RotatingFileHandler | None = None
    _current_env: str | None = None
    _original_root_level: int | None = None

    @classmethod
    def set_workspace_path(cls, workspace_path: Path) -> None:
        """Set the workspace path for all environment loggers.

        Args:
            workspace_path: Path to ComfyGit workspace
        """
        cls._workspace_path = workspace_path

        # Create logs directory if workspace exists
        if workspace_path and workspace_path.exists():
            logs_dir = workspace_path / "logs"
            logs_dir.mkdir(exist_ok=True)

    @classmethod
    def _add_env_handler(cls, env_name: str) -> logging.Handler | None:
        """Add a file handler for the environment to the root logger.

        Args:
            env_name: Environment name

        Returns:
            The handler that was added, or None if workspace not set
        """
        if not cls._workspace_path or not cls._workspace_path.exists():
            return None

        # Remove any existing environment handler
        cls._remove_env_handler()

        # ALWAYS use directory structure for consistency
        log_dir = cls._workspace_path / "logs" / env_name
        log_dir.mkdir(parents=True, exist_ok=True)

        # Check if compressed logging is enabled via env var
        enable_compressed = os.environ.get('COMFYGIT_DEV_COMPRESS_LOGS', '').lower() in ('true', '1', 'yes')

        if enable_compressed:
            # Dual-output handler (full.log + compressed.log)
            handler = CompressedDualHandler(
                log_dir=log_dir,
                env_name=env_name,
                compression_level='medium',  # Configurable in future
                maxBytes=cls.MAX_BYTES,
                backupCount=cls.BACKUP_COUNT,
                encoding='utf-8'
            )
        else:
            # Single file in directory
            log_file = log_dir / "full.log"
            handler = RotatingFileHandler(
                log_file,
                maxBytes=cls.MAX_BYTES,
                backupCount=cls.BACKUP_COUNT,
                encoding='utf-8'
            )

        handler.setLevel(logging.DEBUG)

        # Set formatter
        formatter = logging.Formatter(cls.DETAILED_FORMAT)
        handler.setFormatter(formatter)

        # Add a name to identify this handler
        handler.set_name(f"env_handler_{env_name}")

        # Add handler to root logger and ensure it's configured
        root_logger = logging.getLogger()

        # Ensure root logger level allows DEBUG messages through
        if root_logger.level > logging.DEBUG:
            # Store original level to restore later
            cls._original_root_level = root_logger.level
            root_logger.setLevel(logging.DEBUG)
        else:
            cls._original_root_level = None

        root_logger.addHandler(handler)

        # Store reference
        cls._active_handler = handler
        cls._current_env = env_name

        return handler

    @classmethod
    def _remove_env_handler(cls) -> None:
        """Remove the current environment handler from the root logger."""
        if cls._active_handler:
            root_logger = logging.getLogger()
            root_logger.removeHandler(cls._active_handler)
            cls._active_handler.close()
            cls._active_handler = None
            cls._current_env = None

            # Restore original root logger level if we changed it
            if cls._original_root_level is not None:
                root_logger.setLevel(cls._original_root_level)
                cls._original_root_level = None

    @classmethod
    @contextmanager
    def log_command(cls, env_name: str, command: str, **context):
        """Context manager for logging a command execution.

        This adds a file handler to the root logger for the duration
        of the command, so all logging from any module will go to
        the environment's log file.

        Args:
            env_name: Environment name
            command: Command being executed
            **context: Additional context to log

        Example:
            with EnvironmentLogger.log_command("my-env", "node add"):
                # All logging from any module will go to my-env.log
                env_mgr.create_environment(...)  # Its logs go to my-env.log
        """
        handler = cls._add_env_handler(env_name)

        if not handler:
            # No workspace, yield None
            yield None
            return

        # Get root logger for command logging
        logger = logging.getLogger("comfygit.command")

        # Log command start
        separator = "=" * 60
        logger.info(separator)
        logger.info(f"Command: {command}")
        logger.info(f"Started: {datetime.now().isoformat()}")

        # Log any context
        for key, value in context.items():
            if value is not None:  # Only log non-None values
                logger.info(f"{key}: {value}")

        logger.info("-" * 40)

        try:
            # Yield - during this time all logging goes to the env file
            yield logger

            # Log successful completion
            logger.info(f"Command '{command}' completed successfully")

        except (SystemExit, KeyboardInterrupt) as e:
            # Log system exit/interrupt
            if isinstance(e, SystemExit):
                logger.info(f"Command '{command}' exited with code {e.code}")
            else:
                logger.info(f"Command '{command}' interrupted")
            raise

        except Exception as e:
            # Log the error
            logger.error(f"Command '{command}' failed: {e}", exc_info=True)
            raise

        finally:
            # Log command end
            logger.info(f"Ended: {datetime.now().isoformat()}")
            logger.info(separator + "\n")

            # Remove the handler
            cls._remove_env_handler()

    @classmethod
    def set_environment(cls, env_name: str) -> None:
        """Set the active environment for logging.

        This is useful for long-running operations where you want
        all logs to go to a specific environment file without
        using the context manager.

        Args:
            env_name: Environment name
        """
        cls._add_env_handler(env_name)

    @classmethod
    def clear_environment(cls) -> None:
        """Clear the active environment logging."""
        cls._remove_env_handler()

    @classmethod
    def get_current_environment(cls) -> str | None:
        """Get the currently active environment for logging."""
        return cls._current_env


class WorkspaceLogger:
    """Manages workspace-level logging separate from environment-specific logging.

    This creates logs under logs/workspace/workspace.log for global workspace commands.
    """

    # Shared configuration
    MAX_BYTES = 10 * 1024 * 1024  # 10 MB per log file
    BACKUP_COUNT = 5  # Keep 5 old log files
    DETAILED_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s"

    _workspace_path: Path | None = None
    _active_handler: RotatingFileHandler | None = None
    _original_root_level: int | None = None

    @classmethod
    def set_workspace_path(cls, workspace_path: Path) -> None:
        """Set the workspace path for workspace logging.

        Args:
            workspace_path: Path to ComfyGit workspace
        """
        cls._workspace_path = workspace_path

        # Create workspace logs directory if workspace exists
        if workspace_path and workspace_path.exists():
            logs_dir = workspace_path / "logs" / "workspace"
            logs_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def _add_workspace_handler(cls) -> logging.Handler | None:
        """Add a file handler for workspace commands to the root logger.

        Returns:
            The handler that was added, or None if workspace not set
        """
        if not cls._workspace_path or not cls._workspace_path.exists():
            return None

        # Remove any existing workspace handler
        cls._remove_workspace_handler()

        # Use consistent directory structure
        log_dir = cls._workspace_path / "logs" / "workspace"
        log_dir.mkdir(parents=True, exist_ok=True)

        # Check if compressed logging is enabled via env var
        enable_compressed = os.environ.get('COMFYGIT_DEV_COMPRESS_LOGS', '').lower() in ('true', '1', 'yes')

        if enable_compressed:
            # Dual-output handler (full.log + compressed.log)
            handler = CompressedDualHandler(
                log_dir=log_dir,
                env_name='workspace',  # For header
                compression_level='medium',
                maxBytes=cls.MAX_BYTES,
                backupCount=cls.BACKUP_COUNT,
                encoding='utf-8'
            )
        else:
            # Single file in directory (renamed to full.log for consistency)
            log_file = log_dir / "full.log"
            handler = RotatingFileHandler(
                log_file,
                maxBytes=cls.MAX_BYTES,
                backupCount=cls.BACKUP_COUNT,
                encoding='utf-8'
            )

        handler.setLevel(logging.DEBUG)

        # Set formatter
        formatter = logging.Formatter(cls.DETAILED_FORMAT)
        handler.setFormatter(formatter)

        # Add a name to identify this handler
        handler.set_name("workspace_handler")

        # Add handler to root logger and ensure it's configured
        root_logger = logging.getLogger()

        # Ensure root logger level allows DEBUG messages through
        if root_logger.level > logging.DEBUG:
            # Store original level to restore later
            cls._original_root_level = root_logger.level
            root_logger.setLevel(logging.DEBUG)
        else:
            cls._original_root_level = None

        root_logger.addHandler(handler)

        # Store reference
        cls._active_handler = handler

        return handler

    @classmethod
    def _remove_workspace_handler(cls) -> None:
        """Remove the current workspace handler from the root logger."""
        if cls._active_handler:
            root_logger = logging.getLogger()
            root_logger.removeHandler(cls._active_handler)
            cls._active_handler.close()
            cls._active_handler = None

            # Restore original root logger level if we changed it
            if cls._original_root_level is not None:
                root_logger.setLevel(cls._original_root_level)
                cls._original_root_level = None

    @classmethod
    @contextmanager
    def log_command(cls, command: str, **context):
        """Context manager for logging a workspace command execution.

        This adds a file handler to the root logger for the duration
        of the command, so all logging from any module will go to
        the workspace log file.

        Args:
            command: Command being executed
            **context: Additional context to log

        Example:
            with WorkspaceLogger.log_command("init"):
                # All logging from any module will go to workspace.log
                workspace_mgr.create_workspace(...)
        """
        handler = cls._add_workspace_handler()

        if not handler:
            # No workspace, yield None
            yield None
            return

        # Get root logger for command logging
        logger = logging.getLogger("comfygit.workspace")

        # Log command start
        separator = "=" * 60
        logger.info(separator)
        logger.info(f"Command: {command}")
        logger.info(f"Started: {datetime.now().isoformat()}")

        # Log any context
        for key, value in context.items():
            if value is not None:  # Only log non-None values
                logger.info(f"{key}: {value}")

        logger.info("-" * 40)

        try:
            # Yield - during this time all logging goes to the workspace file
            yield logger

            # Log successful completion
            logger.info(f"Command '{command}' completed successfully")

        except (SystemExit, KeyboardInterrupt) as e:
            # Log system exit/interrupt
            if isinstance(e, SystemExit):
                logger.info(f"Command '{command}' exited with code {e.code}")
            else:
                logger.info(f"Command '{command}' interrupted")
            raise

        except Exception as e:
            # Log the error
            logger.error(f"Command '{command}' failed: {e}", exc_info=True)
            raise

        finally:
            # Log command end
            logger.info(f"Ended: {datetime.now().isoformat()}")
            logger.info(separator + "\n")

            # Remove the handler
            cls._remove_workspace_handler()


def with_env_logging(command_name: str, get_env_name: Callable | None = None, log_args: bool = True, **log_context):
    """Decorator for environment commands that automatically sets up logging.

    Args:
        command_name: Name of the command for logging (e.g., "create", "node add")
        get_env_name: Optional function to extract env name from args.
                     If None, tries args.name, then args.env_name,
                     then calls self._get_env_name(args) if available.
        log_args: If True, automatically logs all args attributes (default: True)
        **log_context: Additional static context to log

    Example:
        @with_env_logging("create")  # Automatically logs all args
        def create(self, args):
            # All logging automatically goes to environment log
            result = self.env_mgr.create_environment(...)

        @with_env_logging("repair", log_args=False, custom_field="value")
        def repair(self, args):
            # Only logs custom_field, not args
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(self, args, *extra_args, **kwargs):
            # Determine environment name
            env_name = None
            if get_env_name:
                # Try calling with self first, fall back to just args
                import inspect
                sig = inspect.signature(get_env_name)
                if len(sig.parameters) >= 2:
                    env_name = get_env_name(self, args)
                else:
                    env_name = get_env_name(args)
            elif hasattr(args, 'name'):
                # For commands like 'create', args.name is the target environment
                env_name = args.name
            elif hasattr(args, 'env_name'):
                env_name = args.env_name
            elif hasattr(self, '_get_env'):
                # For commands operating IN an environment, fall back to active env
                env_name = self._get_env(args).name

            # If no environment name available, run without logging
            if not env_name:
                return func(self, args, *extra_args, **kwargs)

            # Ensure EnvironmentLogger has workspace path set
            # Import here to avoid circular imports
            from ..cli_utils import get_workspace_optional

            workspace = get_workspace_optional()
            if workspace:
                EnvironmentLogger.set_workspace_path(workspace.path)

            # Build context
            context = {}

            # Auto-capture all args attributes if enabled
            if log_args and hasattr(args, '__dict__'):
                # Get all non-private attributes from args
                # Prefix with 'arg_' to avoid conflicts with log_command parameters
                args_dict = {f'arg_{k}': v for k, v in vars(args).items() if not k.startswith('_')}
                context.update(args_dict)

            # Add/override with explicit log_context
            for key, value in log_context.items():
                if callable(value):
                    # It's a function to extract from args
                    try:
                        context[key] = value(args)
                    except (AttributeError, TypeError):
                        pass  # Skip if extraction fails
                else:
                    # Static value
                    context[key] = value

            # Run with logging context
            with EnvironmentLogger.log_command(env_name, command_name, **context) as logger:
                # Pass logger to function if it accepts it
                import inspect
                sig = inspect.signature(func)
                if 'logger' in sig.parameters:
                    kwargs['logger'] = logger
                return func(self, args, *extra_args, **kwargs)

        return wrapper
    return decorator


def with_workspace_logging(command_name: str, log_args: bool = True, **log_context):
    """Decorator for workspace commands that automatically sets up logging.

    Args:
        command_name: Name of the command for logging (e.g., "init", "list", "model scan")
        log_args: If True, automatically logs all args attributes (default: True)
        **log_context: Additional static context to log

    Example:
        @with_workspace_logging("init")  # Automatically logs all args
        def init(self, args):
            # All logging automatically goes to workspace log
            result = self.workspace_factory.create(...)

        @with_workspace_logging("model scan", log_args=False, custom_field="value")
        def model_scan(self, args):
            # Only logs custom_field, not args
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(self, args, *extra_args, **kwargs):
            # Ensure workspace logger is initialized
            # This is needed because the decorator runs before the method body
            # Import here to avoid circular imports
            from ..cli_utils import get_workspace_optional

            workspace = get_workspace_optional()
            if workspace:
                WorkspaceLogger.set_workspace_path(workspace.path)

            # Build context
            context = {}

            # Auto-capture all args attributes if enabled
            if log_args and hasattr(args, '__dict__'):
                # Get all non-private attributes from args
                # Prefix with 'arg_' to avoid conflicts with log_command parameters
                args_dict = {f'arg_{k}': v for k, v in vars(args).items() if not k.startswith('_')}
                context.update(args_dict)

            # Add/override with explicit log_context
            for key, value in log_context.items():
                if callable(value):
                    # It's a function to extract from args
                    try:
                        context[key] = value(args)
                    except (AttributeError, TypeError):
                        pass  # Skip if extraction fails
                else:
                    # Static value
                    context[key] = value

            # Run with logging context
            with WorkspaceLogger.log_command(command_name, **context):
                return func(self, args, *extra_args, **kwargs)

        return wrapper
    return decorator
