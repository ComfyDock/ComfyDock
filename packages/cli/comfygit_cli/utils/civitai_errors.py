"""Civitai error handling utilities."""


def show_civitai_auth_help() -> None:
    """Display helpful message for Civitai authentication errors."""
    print("\n💡 Civitai API key required")
    print("   1. Get your API key from: https://civitai.com/user/account")
    print("   2. Add it to ComfyGit: cg auth set civitai")
    print("   3. Try downloading again")
