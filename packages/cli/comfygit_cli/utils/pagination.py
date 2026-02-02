"""Simple pagination utility for CLI output."""

import sys
from collections.abc import Callable
from typing import TypeVar

T = TypeVar('T')


def paginate(
    items: list[T],
    render_item: Callable[[T], None],
    page_size: int = 5,
    header: str = ""
) -> None:
    """Display items with pagination controls.

    Auto-detects if stdout is a TTY. If piped, dumps all items without pagination.

    Args:
        items: List of items to paginate
        render_item: Function to render a single item
        page_size: Number of items per page
        header: Optional header to display before results
    """
    if not items:
        return

    # Auto-detect: if not a TTY (piped/redirected), dump everything
    if not sys.stdout.isatty():
        if header:
            print(header)
        for item in items:
            render_item(item)
        return

    # Interactive pagination for TTY
    total_items = len(items)
    total_pages = (total_items + page_size - 1) // page_size
    current_page = 0

    while True:
        # Clear screen and show header
        print("\033[2J\033[H", end="")  # Clear screen, move to top

        if header:
            print(header)

        # Calculate page bounds
        start_idx = current_page * page_size
        end_idx = min(start_idx + page_size, total_items)

        # Display items for current page
        for item in items[start_idx:end_idx]:
            render_item(item)

        # Display pagination controls
        print(f"\n{'─' * 60}")
        print(f"Page {current_page + 1}/{total_pages} (showing {start_idx + 1}-{end_idx} of {total_items})")

        # Build prompt based on available navigation
        options = []
        if current_page < total_pages - 1:
            options.append("[n]ext")
        if current_page > 0:
            options.append("[p]rev")
        options.append("[q]uit")

        prompt = f"{' | '.join(options)}: "

        try:
            choice = input(prompt).lower().strip()
        except (EOFError, KeyboardInterrupt):
            print("\n")
            break

        if choice == 'n' and current_page < total_pages - 1:
            current_page += 1
        elif choice == 'p' and current_page > 0:
            current_page -= 1
        elif choice == 'q':
            break
        # Invalid input - just redisplay current page
