#!/usr/bin/env python3
"""
Comfy Registry CLI - A simple command-line interface for the Comfy API

Usage: uv run registry <command> [options]
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class RegistryClient:
    def __init__(self, base_url: str = "https://api.comfy.org", token: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.token = token or os.environ.get("COMFY_API_TOKEN")

    def _make_request(
        self, method: str, path: str, data: dict[str, Any] | None = None, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"

        if params:
            query_params = {}
            for k, v in params.items():
                if v is not None:
                    if isinstance(v, bool):
                        query_params[k] = "true" if v else "false"
                    elif isinstance(v, list):
                        query_params[k] = ",".join(str(x) for x in v)
                    else:
                        query_params[k] = str(v)
            if query_params:
                url += "?" + urllib.parse.urlencode(query_params)

        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        req_data = None
        if data:
            req_data = json.dumps(data).encode("utf-8")

        request = urllib.request.Request(url, data=req_data, headers=headers, method=method)

        try:
            with urllib.request.urlopen(request) as response:
                if response.status in (200, 201):
                    return json.loads(response.read().decode("utf-8"))
                elif response.status == 204:
                    return {"success": True, "message": "Operation completed successfully"}
                else:
                    return {"error": f"HTTP {response.status}", "message": response.read().decode("utf-8")}
        except urllib.error.HTTPError as e:
            error_msg = e.read().decode("utf-8") if e.fp else str(e)
            return {"error": f"HTTP {e.code}", "message": error_msg}
        except urllib.error.URLError as e:
            return {"error": "Connection error", "message": str(e)}

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._make_request("GET", path, params=params)

    def post(self, path: str, data: dict[str, Any], params: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._make_request("POST", path, data=data, params=params)

    def put(self, path: str, data: dict[str, Any], params: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._make_request("PUT", path, data=data, params=params)

    def delete(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._make_request("DELETE", path, params=params)


def print_json(data: dict[str, Any]) -> None:
    print(json.dumps(data, indent=2))


def filter_comfy_nodes_by_name(result: dict[str, Any], name_filter: str) -> dict[str, Any]:
    """Filter ComfyNode results by comfy_node_name field."""
    if not name_filter or "error" in result:
        return result

    # Handle different possible response structures
    # For comfy-nodes endpoint, data is in "comfy_nodes" key, not "data"
    data = result.get("comfy_nodes", result.get("data", []))
    if not isinstance(data, list):
        # If data is not a list, check if the result itself is the node
        if isinstance(result, dict) and result.get("comfy_node_name") == name_filter:
            return result
        else:
            # Return empty result with same structure as input
            empty_result = result.copy()
            if "comfy_nodes" in result:
                empty_result["comfy_nodes"] = []
            else:
                empty_result["data"] = []
            empty_result["message"] = f"No nodes found with name '{name_filter}'"
            return empty_result

    # Filter the data array
    filtered_data = [
        item for item in data
        if isinstance(item, dict) and item.get("comfy_node_name") == name_filter
    ]

    # Return filtered result with same structure
    filtered_result = result.copy()
    if "comfy_nodes" in result:
        filtered_result["comfy_nodes"] = filtered_data
    else:
        filtered_result["data"] = filtered_data

    if not filtered_data:
        filtered_result["message"] = f"No nodes found with name '{name_filter}'"

    return filtered_result


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--token", help="API token (or set COMFY_API_TOKEN env var)")
    parser.add_argument("--base-url", default="https://api.comfy.org", help="Base API URL")


def add_users_commands(subparsers) -> None:
    users_parser = subparsers.add_parser("users", help="User operations")
    users_subparsers = users_parser.add_subparsers(dest="users_action", help="User actions")

    get_user_parser = users_subparsers.add_parser("get", help="Get current user info")
    add_common_args(get_user_parser)

    list_publishers_parser = users_subparsers.add_parser("publishers", help="List publishers for current user")
    add_common_args(list_publishers_parser)


def add_publishers_commands(subparsers) -> None:
    pub_parser = subparsers.add_parser("publishers", help="Publisher operations")
    pub_subparsers = pub_parser.add_subparsers(dest="publishers_action", help="Publisher actions")

    list_parser = pub_subparsers.add_parser("list", help="List all publishers")
    add_common_args(list_parser)

    get_parser = pub_subparsers.add_parser("get", help="Get publisher by ID")
    get_parser.add_argument("publisher_id", help="Publisher ID")
    add_common_args(get_parser)

    validate_parser = pub_subparsers.add_parser("validate", help="Validate publisher username")
    validate_parser.add_argument("username", help="Username to validate")
    add_common_args(validate_parser)

    create_parser = pub_subparsers.add_parser("create", help="Create new publisher")
    create_parser.add_argument("--name", required=True, help="Publisher name")
    create_parser.add_argument("--id", required=True, help="Publisher ID (username)")
    create_parser.add_argument("--description", help="Description")
    create_parser.add_argument("--website", help="Website URL")
    create_parser.add_argument("--support", help="Support URL")
    create_parser.add_argument("--source-code-repo", help="Source code repository URL")
    create_parser.add_argument("--logo", help="Logo URL")
    add_common_args(create_parser)


def add_nodes_commands(subparsers) -> None:
    nodes_parser = subparsers.add_parser("nodes", help="Node operations")
    nodes_subparsers = nodes_parser.add_subparsers(dest="nodes_action", help="Node actions")

    list_parser = nodes_subparsers.add_parser("list", help="List all nodes")
    list_parser.add_argument("--page", type=int, default=1, help="Page number")
    list_parser.add_argument("--limit", type=int, default=10, help="Items per page")
    list_parser.add_argument("--include-banned", action="store_true", help="Include banned nodes")
    list_parser.add_argument("--timestamp", help="Filter by timestamp (ISO format)")
    list_parser.add_argument("--latest", action="store_true", help="Get latest from database")
    add_common_args(list_parser)

    search_parser = nodes_subparsers.add_parser("search", help="Search nodes")
    search_parser.add_argument("--query", help="Search query")
    search_parser.add_argument("--page", type=int, default=1, help="Page number")
    search_parser.add_argument("--limit", type=int, default=10, help="Items per page")
    search_parser.add_argument("--include-banned", action="store_true", help="Include banned nodes")
    add_common_args(search_parser)

    get_parser = nodes_subparsers.add_parser("get", help="Get node by ID")
    get_parser.add_argument("node_id", help="Node ID")
    add_common_args(get_parser)

    install_parser = nodes_subparsers.add_parser("install", help="Get node installation info")
    install_parser.add_argument("node_id", help="Node ID")
    install_parser.add_argument("--version", help="Specific version")
    add_common_args(install_parser)

    versions_parser = nodes_subparsers.add_parser("versions", help="List node versions")
    versions_parser.add_argument("node_id", help="Node ID")
    versions_parser.add_argument("--statuses", nargs="+", help="Filter by statuses")
    versions_parser.add_argument("--include-status-reason", action="store_true", help="Include status reasons")
    add_common_args(versions_parser)

    comfy_nodes_parser = nodes_subparsers.add_parser("comfy-nodes", help="Get ComfyNode metadata")
    comfy_nodes_parser.add_argument("node_id", help="Node ID")
    comfy_nodes_parser.add_argument("version", help="Version")
    comfy_nodes_parser.add_argument("--comfy-node-id", help="Specific ComfyNode ID to get")
    comfy_nodes_parser.add_argument("--name", help="Filter by comfy_node_name field")
    comfy_nodes_parser.add_argument("--page", type=int, help="Specific page to show (1-based)")
    comfy_nodes_parser.add_argument("--limit", type=int, help="Maximum number of pages to show")
    add_common_args(comfy_nodes_parser)


def add_git_commands(subparsers) -> None:
    git_parser = subparsers.add_parser("git", help="Git/CI operations")
    git_subparsers = git_parser.add_subparsers(dest="git_action", help="Git actions")

    commit_parser = git_subparsers.add_parser("commit", help="Get commit data")
    commit_parser.add_argument("--commit-id", help="Commit ID")
    commit_parser.add_argument("--os", help="Operating system filter")
    commit_parser.add_argument("--workflow", help="Workflow name filter")
    commit_parser.add_argument("--branch", help="Branch filter")
    commit_parser.add_argument("--repo", default="comfyanonymous/ComfyUI", help="Repository name")
    commit_parser.add_argument("--page", type=int, default=1, help="Page number")
    commit_parser.add_argument("--page-size", type=int, default=10, help="Page size")
    add_common_args(commit_parser)

    summary_parser = git_subparsers.add_parser("summary", help="Get commit summaries")
    summary_parser.add_argument("--repo", default="comfyanonymous/ComfyUI", help="Repository name")
    summary_parser.add_argument("--branch", help="Branch name filter")
    summary_parser.add_argument("--page", type=int, default=1, help="Page number")
    summary_parser.add_argument("--page-size", type=int, default=10, help="Page size")
    add_common_args(summary_parser)

    branches_parser = git_subparsers.add_parser("branches", help="Get repository branches")
    branches_parser.add_argument("--repo", required=True, help="Repository name")
    add_common_args(branches_parser)

    workflow_parser = git_subparsers.add_parser("workflow", help="Get workflow result")
    workflow_parser.add_argument("workflow_id", help="Workflow result ID")
    add_common_args(workflow_parser)


def handle_users_command(client: RegistryClient, args: argparse.Namespace) -> None:
    if args.users_action == "get":
        result = client.get("/users")
    elif args.users_action == "publishers":
        result = client.get("/users/publishers/")
    else:
        print("Unknown users action")
        return

    print_json(result)


def handle_publishers_command(client: RegistryClient, args: argparse.Namespace) -> None:
    if args.publishers_action == "list":
        result = client.get("/publishers")
    elif args.publishers_action == "get":
        result = client.get(f"/publishers/{args.publisher_id}")
    elif args.publishers_action == "validate":
        result = client.get("/publishers/validate", {"username": args.username})
    elif args.publishers_action == "create":
        data = {
            "name": args.name,
            "id": args.id,
        }
        if args.description:
            data["description"] = args.description
        if args.website:
            data["website"] = args.website
        if args.support:
            data["support"] = args.support
        if args.source_code_repo:
            data["source_code_repo"] = args.source_code_repo
        if args.logo:
            data["logo"] = args.logo

        result = client.post("/publishers", data)
    else:
        print("Unknown publishers action")
        return

    print_json(result)


def handle_nodes_command(client: RegistryClient, args: argparse.Namespace) -> None:
    if args.nodes_action == "list":
        params = {
            "page": args.page,
            "limit": args.limit,
            "include_banned": args.include_banned,
        }
        if hasattr(args, "timestamp") and args.timestamp:
            params["timestamp"] = args.timestamp
        if hasattr(args, "latest") and args.latest:
            params["latest"] = args.latest

        result = client.get("/nodes", params)
    elif args.nodes_action == "search":
        params = {
            "page": args.page,
            "limit": args.limit,
            "include_banned": args.include_banned,
        }
        if args.query:
            params["search"] = args.query

        result = client.get("/nodes/search", params)
    elif args.nodes_action == "get":
        result = client.get(f"/nodes/{args.node_id}")
    elif args.nodes_action == "install":
        params = {}
        if args.version:
            params["version"] = args.version

        result = client.get(f"/nodes/{args.node_id}/install", params)
    elif args.nodes_action == "versions":
        params = {}
        if args.statuses:
            params["statuses"] = args.statuses
        if args.include_status_reason:
            params["include_status_reason"] = args.include_status_reason

        result = client.get(f"/nodes/{args.node_id}/versions", params)
    elif args.nodes_action == "comfy-nodes":
        if args.comfy_node_id:
            # Get specific ComfyNode by ID
            result = client.get(f"/nodes/{args.node_id}/versions/{args.version}/comfy-nodes/{args.comfy_node_id}")
            print_json(result)
            return
        else:
            # Handle pagination for full metadata listing
            handle_comfy_nodes_pagination(client, args)
            return
    else:
        print("Unknown nodes action")
        return

    print_json(result)


def handle_comfy_nodes_pagination(client: RegistryClient, args: argparse.Namespace) -> None:
    """Handle paginated ComfyNode metadata fetching with full output support."""
    base_path = f"/nodes/{args.node_id}/versions/{args.version}/comfy-nodes"
    name_filter = getattr(args, 'name', None)

    if args.page is not None:
        # Show specific page
        params = {"page": args.page, "limit": 50}  # Use reasonable page size
        result = client.get(base_path, params)

        if name_filter:
            result = filter_comfy_nodes_by_name(result, name_filter)

        print_json(result)
        return

    if args.limit is not None:
        # Show limited number of pages
        found_match = False
        for page_num in range(1, args.limit + 1):
            params = {"page": page_num, "limit": 50}
            result = client.get(base_path, params)

            if "error" in result:
                print(f"Error on page {page_num}: {result}")
                break

            # Store original data before filtering for pagination logic
            original_data = result.get("comfy_nodes", result.get("data", [])) if isinstance(result.get("comfy_nodes", result.get("data")), list) else []

            if name_filter:
                result = filter_comfy_nodes_by_name(result, name_filter)
                # If we found a match and it's not empty, we can stop here
                filtered_nodes = result.get("comfy_nodes", result.get("data", []))
                if filtered_nodes and len(filtered_nodes) > 0:
                    found_match = True
                    print(f"\n{'='*60}")
                    print(f"MATCH FOUND on PAGE {page_num}")
                    print('='*60)
                    print_json(result)
                    print(f"\nFound match for '{name_filter}', stopping search")
                    break
            else:
                print(f"\n{'='*60}")
                print(f"PAGE {page_num}")
                print('='*60)
                print_json(result)

            # Check if we have data to determine if there are more pages
            # Use original data for pagination logic, not filtered data
            if not original_data or len(original_data) < 50:  # Less than full page means we're at the end
                print(f"\nReached end of data at page {page_num}")
                break

        # If we were filtering and didn't find a match in the limited pages, let the user know
        if name_filter and not found_match:
            print(f"\nNo nodes found with comfy_node_name '{name_filter}' in first {args.limit} pages")
        return

    # Default: Loop through all pages and dump to terminal
    page_num = 1
    found_match = False
    while True:
        params = {"page": page_num, "limit": 50}
        result = client.get(base_path, params)

        if "error" in result:
            if page_num == 1:
                print(f"Error fetching data: {result}")
            else:
                print(f"Reached end of data at page {page_num}")
            break

        # Store original data for pagination logic
        original_data = result.get("comfy_nodes", result.get("data", [])) if isinstance(result.get("comfy_nodes", result.get("data")), list) else []

        if name_filter:
            result = filter_comfy_nodes_by_name(result, name_filter)
            # If we found a match and it's not empty, we can stop here
            filtered_nodes = result.get("comfy_nodes", result.get("data", []))
            if filtered_nodes and len(filtered_nodes) > 0:
                found_match = True
                print(f"\n{'='*60}")
                print(f"MATCH FOUND on PAGE {page_num}")
                print('='*60)
                print_json(result)
                print(f"\nFound match for '{name_filter}', stopping search")
                break
        else:
            print(f"\n{'='*60}")
            print(f"PAGE {page_num}")
            print('='*60)
            print_json(result)

        # Check if we have data to determine if there are more pages
        if not original_data or len(original_data) < 50:  # Less than full page means we're at the end
            print(f"\nReached end of data at page {page_num}")
            break

        page_num += 1

        # Safety check to prevent infinite loops
        if page_num > 1000:
            print("\nStopping after 1000 pages to prevent infinite loop")
            break

    # If we were filtering and didn't find a match, let the user know
    if name_filter and not found_match:
        print(f"\nNo nodes found with comfy_node_name '{name_filter}' after searching {page_num} pages")


def handle_git_command(client: RegistryClient, args: argparse.Namespace) -> None:
    if args.git_action == "commit":
        params = {
            "repoName": args.repo,
            "page": args.page,
            "pageSize": args.page_size,
        }
        if args.commit_id:
            params["commitId"] = args.commit_id
        if args.os:
            params["operatingSystem"] = args.os
        if args.workflow:
            params["workflowName"] = args.workflow
        if args.branch:
            params["branch"] = args.branch

        result = client.get("/gitcommit", params)
    elif args.git_action == "summary":
        params = {
            "repoName": args.repo,
            "page": args.page,
            "pageSize": args.page_size,
        }
        if args.branch:
            params["branchName"] = args.branch

        result = client.get("/gitcommitsummary", params)
    elif args.git_action == "branches":
        result = client.get("/branch", {"repo_name": args.repo})
    elif args.git_action == "workflow":
        result = client.get(f"/workflowresult/{args.workflow_id}")
    else:
        print("Unknown git action")
        return

    print_json(result)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Comfy Registry CLI - Interface for the Comfy API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Environment Variables:
  COMFY_API_TOKEN    API token for authentication

Examples:
  uv run registry nodes search --query "upscale"
  uv run registry nodes get node-id-here
  uv run registry nodes comfy-nodes comfyui_tinyterranodes 2.0.9
  uv run registry nodes comfy-nodes comfyui_tinyterranodes 2.0.9 --page 2
  uv run registry nodes comfy-nodes comfyui_tinyterranodes 2.0.9 --limit 5
  uv run registry nodes comfy-nodes comfyui_tinyterranodes 2.0.9 --name "ttN pipe2DETAILER"
  uv run registry publishers list
  uv run registry git summary --repo comfyanonymous/ComfyUI
  uv run registry users get --token your-token-here
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    add_users_commands(subparsers)
    add_publishers_commands(subparsers)
    add_nodes_commands(subparsers)
    add_git_commands(subparsers)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    client = RegistryClient(
        base_url=getattr(args, "base_url", "https://api.comfy.org"),
        token=getattr(args, "token", None)
    )

    try:
        if args.command == "users":
            handle_users_command(client, args)
        elif args.command == "publishers":
            handle_publishers_command(client, args)
        elif args.command == "nodes":
            handle_nodes_command(client, args)
        elif args.command == "git":
            handle_git_command(client, args)
        else:
            print(f"Unknown command: {args.command}")
            sys.exit(1)
    except KeyboardInterrupt:
        print("\nOperation cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
