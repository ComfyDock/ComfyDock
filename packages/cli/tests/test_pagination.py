"""Tests for pagination utility with TTY detection."""

import sys
from io import StringIO
from unittest.mock import patch

from comfygit_cli.utils.pagination import paginate


def test_paginate_dumps_all_when_not_tty():
    """When stdout is not a TTY (piped), paginate should dump all items."""
    items = [f"item_{i}" for i in range(20)]
    output = StringIO()

    def render_item(item):
        print(item)

    # Mock isatty to return False (piped output)
    with patch.object(sys.stdout, 'isatty', return_value=False):
        with patch('sys.stdout', output):
            with patch('builtins.print', side_effect=lambda *args, **kwargs: output.write(' '.join(str(a) for a in args) + '\n')):
                paginate(items, render_item, page_size=5, header="Test Header")

    result = output.getvalue()

    # Should contain header
    assert "Test Header" in result

    # Should contain all items (not just first page)
    for item in items:
        assert item in result

    # Should NOT contain pagination controls
    assert "Page" not in result
    assert "[n]ext" not in result


def test_paginate_shows_first_page_when_tty():
    """When stdout is a TTY, paginate should show interactive controls."""
    items = [f"item_{i}" for i in range(20)]

    def render_item(item):
        pass  # We'll capture via mock

    # Mock isatty to return True (interactive terminal)
    # Mock input to quit immediately
    with patch.object(sys.stdout, 'isatty', return_value=True):
        with patch('builtins.input', return_value='q'):
            with patch('builtins.print') as mock_print:
                paginate(items, render_item, page_size=5, header="Test Header")

    # Should have printed pagination controls
    calls = [str(call) for call in mock_print.call_args_list]
    ''.join(calls)

    # Should contain page indicator
    assert any("Page" in call for call in calls)


def test_paginate_handles_empty_list():
    """Paginate should handle empty list gracefully."""
    items = []

    def render_item(item):
        raise AssertionError("Should not be called for empty list")

    # Should not raise, should not call render_item
    with patch.object(sys.stdout, 'isatty', return_value=False):
        paginate(items, render_item)

    with patch.object(sys.stdout, 'isatty', return_value=True):
        paginate(items, render_item)
