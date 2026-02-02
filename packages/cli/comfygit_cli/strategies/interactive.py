"""Interactive resolution strategies for CLI."""


from comfygit_core.models.protocols import (
    ModelResolutionStrategy,
    NodeResolutionStrategy,
)
from comfygit_core.models.shared import ModelWithLocation
from comfygit_core.models.workflow import (
    ModelResolutionContext,
    NodeResolutionContext,
    ResolvedModel,
    ResolvedNodePackage,
    ScoredMatch,
    WorkflowNodeWidgetRef,
)


class InteractiveNodeStrategy(NodeResolutionStrategy):
    """Interactive node resolution with unified search."""

    def __init__(self) -> None:
        """Initialize strategy (stateless - context passed per resolution)."""
        self._last_choice: str | None = None  # Track last user choice for optional detection

    def _unified_choice_prompt(self, prompt_text: str, num_options: int, has_browse: bool = False) -> str:
        """Unified choice prompt with inline manual/skip/optional/refine options.

        Args:
            prompt_text: The choice prompt like "Choice [1]/r/m/o/s: "
            num_options: Number of valid numeric options (1-based)
            has_browse: Whether option 0 (browse) is available

        Returns:
            User's choice as string (number, 'm', 'o', 's', 'r', or '0' for browse)
        """
        while True:
            choice = input(prompt_text).strip().lower()

            # Default to '1' if empty
            if not choice:
                return "1"

            # Check special options
            if choice in ('m', 's', 'o', 'r'):
                return choice

            # Check browse option
            if has_browse and choice == '0':
                return '0'

            # Check numeric range
            if choice.isdigit():
                idx = int(choice)
                if 1 <= idx <= num_options:
                    return choice

            print("  Invalid choice, try again")

    def _get_manual_package_id(self, node_type: str) -> ResolvedNodePackage | None:
        """Get package ID from manual user input."""
        pkg_id = input("Enter package ID: ").strip()
        if not pkg_id:
            return None

        print(f"  Note: Package '{pkg_id}' will be verified during install")
        return ResolvedNodePackage(
            node_type=node_type,
            match_type="manual",
            package_id=pkg_id
        )

    def _get_optional_package(self, node_type: str) -> ResolvedNodePackage:
        """Get package ID from manual user input."""
        return ResolvedNodePackage(
            node_type=node_type,
            match_type="optional"
        )

    def resolve_unknown_node(
        self,
        node_type: str,
        possible: list[ResolvedNodePackage],
        context: "NodeResolutionContext"
    ) -> ResolvedNodePackage | None:
        """Prompt user to resolve unknown node.

        Args:
            node_type: The unknown node type
            possible: List of possible package matches
            context: Resolution context with search function and installed packages

        Returns:
            ResolvedNodePackage or None to skip
        """
        # Case 1: Ambiguous from global table (multiple matches)
        if possible and len(possible) > 1:
            return self._resolve_ambiguous(node_type, possible, context)

        # Case 2: Single match from global table - confirm
        # NOTE: Shouldn't be called since automatic resolution should handle this
        if len(possible) == 1:
            pkg = possible[0]
            print(f"\n✓ Found in registry: {pkg.package_id}")
            print(f"  For node: {node_type}")

            choice = input("Accept? [Y/n]: ").strip().lower()
            if choice in ('', 'y', 'yes'):
                return pkg
            # User rejected - fall through to search

        # Case 3: No matches or user rejected single match - use unified search with refinement
        print(f"\n⚠️  Node not found in registry: {node_type}")

        if not context.search_fn:
            # No search available - can only mark optional, manual, or skip
            print("\n  [m] - Manually enter package ID")
            print("  [o] - Mark as optional (workflow works without it)")
            print("  [s] - Skip (leave unresolved)")
            choice = self._unified_choice_prompt("Choice [m]/o/s: ", num_options=0, has_browse=False)

            if choice == 'm':
                self._last_choice = 'manual'
                return self._get_manual_package_id(node_type)
            elif choice == 'o':
                self._last_choice = 'optional'
                print(f"  ✓ Marked '{node_type}' as optional")
                return self._get_optional_package(node_type)
            self._last_choice = 'skip'
            return None

        # Search with refinement loop
        search_term = node_type

        while True:
            print(f"🔍 Searching for: {search_term}")

            results = context.search_fn(
                node_type=search_term,
                installed_packages=context.installed_packages,
                include_registry=True,
                limit=5
            )

            if results:
                # Show results with refinement option
                result = self._show_search_results_with_refinement(
                    node_type, search_term, results, context
                )

                if result == "REFINE":
                    # User wants to refine search
                    new_term = input("\nEnter new search term: ").strip()
                    if new_term:
                        search_term = new_term
                        continue
                    else:
                        print("  Keeping previous search term")
                        continue
                else:
                    # User made a choice (package, optional, manual, or skip)
                    # Type narrowing: result is ResolvedNodePackage | None
                    assert result is None or isinstance(result, ResolvedNodePackage)
                    return result
            else:
                # No results found
                print("  No packages found")
                print("\n  [r] - Refine search")
                print("  [m] - Manually enter package ID")
                print("  [o] - Mark as optional (workflow works without it)")
                print("  [s] - Skip (leave unresolved)")
                choice = self._unified_choice_prompt("Choice [r]/m/o/s: ", num_options=0, has_browse=False)

                if choice == 'r':
                    new_term = input("\nEnter new search term: ").strip()
                    if new_term:
                        search_term = new_term
                        continue
                elif choice == 'm':
                    self._last_choice = 'manual'
                    return self._get_manual_package_id(node_type)
                elif choice == 'o':
                    self._last_choice = 'optional'
                    print(f"  ✓ Marked '{node_type}' as optional")
                    return self._get_optional_package(node_type)
                self._last_choice = 'skip'
                return None

    def _resolve_ambiguous(
        self,
        node_type: str,
        possible: list[ResolvedNodePackage],
        context: "NodeResolutionContext"
    ) -> ResolvedNodePackage | None:
        """Handle ambiguous matches from global table."""
        print(f"\n🔍 Found {len(possible)} matches for '{node_type}':")
        display_count = min(5, len(possible))
        for i, pkg in enumerate(possible[:display_count], 1):
            display_name = pkg.package_data.display_name if pkg.package_data else pkg.package_id
            desc = pkg.package_data.description if pkg.package_data else "No description"
            print(f"  {i}. {display_name or pkg.package_id}")
            if desc and len(desc) > 60:
                desc = desc[:57] + "..."
            print(f"     {desc}")

        has_browse = len(possible) > 5
        if has_browse:
            print(f"  0. Browse all {len(possible)} matches")

        print("\n  [1-9] - Select package to install")
        print("  [o]   - Mark as optional (workflow works without it)")
        print("  [m]   - Manually enter package ID")
        print("  [s]   - Skip (leave unresolved)")

        choice = self._unified_choice_prompt(
            "Choice [1]/o/m/s: ",
            num_options=display_count,
            has_browse=has_browse
        )

        if choice == 's':
            self._last_choice = 'skip'
            return None
        elif choice == 'o':
            # Return None to skip - caller will check _last_choice for optional
            self._last_choice = 'optional'
            print(f"  ✓ Marked '{node_type}' as optional")
            return self._get_optional_package(node_type)
        elif choice == 'm':
            self._last_choice = 'manual'
            return self._get_manual_package_id(node_type)
        elif choice == '0':
            self._last_choice = 'browse'
            selected = self._browse_all_packages(possible, context)
            if selected == "BACK":
                return None
            elif isinstance(selected, ResolvedNodePackage):
                return self._create_resolved_from_match(node_type, selected)
            return None
        else:
            self._last_choice = 'select'
            idx = int(choice) - 1
            selected = possible[idx]
            # Update match_type to ensure it's saved to node_mappings
            # User selected from ambiguous list, so this counts as user confirmation
            return self._create_resolved_from_match(node_type, selected)

    def _show_search_results_with_refinement(
        self,
        node_type: str,
        search_term: str,
        results: list,
        context: "NodeResolutionContext"
    ) -> ResolvedNodePackage | None | str:
        """Show search results with refinement option.

        Returns:
            ResolvedNodePackage - user selected a package
            "REFINE" - user wants to refine search
            None - user skipped or marked optional
        """
        print(f"\nFound {len(results)} potential matches:\n")

        display_count = min(5, len(results))
        for i, match in enumerate(results[:display_count], 1):
            pkg_id = match.package_id
            desc = (match.package_data.description or "No description")[:60] if match.package_data else ""
            installed_marker = " (installed)" if pkg_id in context.installed_packages else ""

            print(f"  {i}. {pkg_id}{installed_marker}")
            if desc:
                print(f"     {desc}")
            print()

        print("  [1-5] - Select package to install")
        print("  [r]   - Refine search")
        print("  [m]   - Manually enter package ID")
        print("  [o]   - Mark as optional (workflow works without it)")
        print("  [s]   - Skip (leave unresolved)")

        choice = self._unified_choice_prompt(
            "Choice [1]/r/m/o/s: ",
            num_options=display_count,
            has_browse=False
        )

        if choice == 's':
            self._last_choice = 'skip'
            return None
        elif choice == 'r':
            self._last_choice = 'refine'
            return "REFINE"
        elif choice == 'o':
            self._last_choice = 'optional'
            print(f"  ✓ Marked '{node_type}' as optional")
            return self._get_optional_package(node_type)
        elif choice == 'm':
            self._last_choice = 'manual'
            return self._get_manual_package_id(node_type)
        else:
            self._last_choice = 'select'
            idx = int(choice) - 1
            selected = results[idx]
            print(f"\n✓ Selected: {selected.package_id}")
            return self._create_resolved_from_match(node_type, selected)

    def _create_resolved_from_match(
        self,
        node_type: str,
        match: ResolvedNodePackage
    ) -> ResolvedNodePackage:
        """Create ResolvedNodePackage from user-confirmed match.

        Args:
            node_type: The node type being resolved
            match: ResolvedNodePackage to update with user confirmation

        Returns:
            ResolvedNodePackage with match_type="user_confirmed"
        """
        # Use existing confidence or default to 1.0
        confidence: float = getattr(match, 'match_confidence', None) or 1.0
        versions = getattr(match, 'versions', [])

        return ResolvedNodePackage(
            package_id=match.package_id,
            package_data=match.package_data,
            node_type=node_type,
            versions=versions,
            match_type="user_confirmed",
            match_confidence=confidence
        )

    def _browse_all_packages(
        self,
        results: list[ResolvedNodePackage],
        context: "NodeResolutionContext"
    ) -> ResolvedNodePackage | str | None:
        """Browse all matches with pagination.

        Returns:
            ResolvedNodePackage if user selects a package
            "BACK" if user goes back
            None if user quits
        """
        page = 0
        page_size = 10
        total_pages = (len(results) + page_size - 1) // page_size

        while True:
            start = page * page_size
            end = min(start + page_size, len(results))

            print(f"\nAll matches (Page {page + 1}/{total_pages}):\n")

            for i, match in enumerate(results[start:end], start + 1):
                pkg_id = match.package_id
                installed_marker = " (installed)" if pkg_id in context.installed_packages else ""
                print(f"  {i}. {pkg_id}{installed_marker}")

            print("\n[N]ext, [P]rev, number, [B]ack, or [Q]uit:")

            choice = input("Choice: ").strip().lower()

            if choice == 'n':
                if page < total_pages - 1:
                    page += 1
                else:
                    print("  Already on last page")
            elif choice == 'p':
                if page > 0:
                    page -= 1
                else:
                    print("  Already on first page")
            elif choice == 'b':
                return "BACK"
            elif choice == 'q':
                return None
            elif choice.isdigit():
                idx = int(choice) - 1
                if 0 <= idx < len(results):
                    return results[idx]
                else:
                    print("  Invalid number")
            else:
                print("  Invalid choice")


    def confirm_node_install(self, package: ResolvedNodePackage) -> bool:
        """Always confirm since user already made the choice."""
        return True


class InteractiveModelStrategy(ModelResolutionStrategy):
    """Interactive model resolution with user prompts."""

    def _unified_choice_prompt(self, prompt_text: str, num_options: int, has_browse: bool = False) -> str:
        """Unified choice prompt with inline refine/skip/optional/download options.

        Args:
            prompt_text: The choice prompt like "Choice [1]/r/o/s: "
            num_options: Number of valid numeric options (1-based)
            has_browse: Whether option 0 (browse) is available

        Returns:
            User's choice as string (number, 'r', 'o', 's', 'd', or '0' for browse)
        """
        while True:
            choice = input(prompt_text).strip().lower()

            # Default to '1' if empty
            if not choice:
                return "1"

            # Check special options
            if choice in ('r', 's', 'o', 'd'):
                return choice

            # Check browse option
            if has_browse and choice == '0':
                return '0'

            # Check numeric range
            if choice.isdigit():
                idx = int(choice)
                if 1 <= idx <= num_options:
                    return choice

            print("  Invalid choice, try again")

    def resolve_model(
        self,
        reference: WorkflowNodeWidgetRef,
        candidates: list[ResolvedModel],
        context: ModelResolutionContext
    ) -> ResolvedModel | None:
        """Unified model resolution - handles both ambiguous and missing models.

        Args:
            reference: The model reference from workflow
            candidates: List of potential matches (empty for missing models)
            context: Resolution context with search function and workflow info

        Returns:
            ResolvedModel with resolved_model set (or None for optional unresolved)
            None to skip resolution
        """
        # Case 1: Multiple candidates (ambiguous)
        if len(candidates) > 1:
            return self._handle_ambiguous(reference, candidates, context)

        # Case 2: Single candidate (confirm)
        if len(candidates) == 1:
            return self._handle_single_candidate(reference, candidates[0], context)

        # Case 3: No candidates (missing - use search)
        return self._handle_missing(reference, context)

    def _handle_ambiguous(
        self,
        reference: WorkflowNodeWidgetRef,
        candidates: list[ResolvedModel],
        context: ModelResolutionContext
    ) -> ResolvedModel | None:
        """Handle ambiguous models (multiple matches)."""

        print(f"\n🔍 Multiple matches for model in node #{reference.node_id}:")
        print(f"  Looking for: {reference.widget_value}")
        print("  Found matches:")

        display_count = min(10, len(candidates))
        for i, resolved in enumerate(candidates[:display_count], 1):
            model = resolved.resolved_model
            if model:
                size_mb = model.file_size / (1024 * 1024)
                print(f"  {i}. {model.relative_path} ({size_mb:.1f} MB)")

        print("\n  [1-9] - Select model")
        print("  [o]   - Mark as optional (select from above)")
        print("  [s]   - Skip")

        choice = self._unified_choice_prompt(
            "Choice [1]/o/s: ",
            num_options=display_count,
            has_browse=False
        )

        if choice == 's':
            return None
        elif choice == 'o':
            # User wants to mark as optional - prompt for which model
            model_choice = input("  Which model? [1]: ").strip() or "1"
            idx = int(model_choice) - 1
            selected = candidates[idx]
            # Return as optional
            return ResolvedModel(
                workflow=context.workflow_name,
                reference=reference,
                resolved_model=selected.resolved_model,
                is_optional=True,
                match_type="user_confirmed",
                match_confidence=1.0
            )
        else:
            idx = int(choice) - 1
            selected = candidates[idx]
            if selected.resolved_model:
                print(f"  ✓ Selected: {selected.resolved_model.relative_path}")
            return ResolvedModel(
                workflow=context.workflow_name,
                reference=reference,
                resolved_model=selected.resolved_model,
                is_optional=False,
                match_type="user_confirmed",
                match_confidence=1.0
            )

    def _handle_single_candidate(
        self,
        reference: WorkflowNodeWidgetRef,
        candidate: ResolvedModel,
        context: ModelResolutionContext
    ) -> ResolvedModel | None:
        """Handle single candidate (confirm with user)."""
        model = candidate.resolved_model
        if not model:
            return None

        print(f"\n✓ Found match for: {reference.widget_value}")
        print(f"  {model.relative_path} ({model.file_size / (1024 * 1024):.1f} MB)")

        choice = input("Accept? [Y/n/o]: ").strip().lower()

        if choice in ('', 'y', 'yes'):
            return ResolvedModel(
                workflow=context.workflow_name,
                reference=reference,
                resolved_model=model,
                is_optional=False,
                match_type="user_confirmed",
                match_confidence=1.0
            )
        elif choice == 'o':
            return ResolvedModel(
                workflow=context.workflow_name,
                reference=reference,
                resolved_model=model,
                is_optional=True,
                match_type="user_confirmed",
                match_confidence=1.0
            )
        else:
            return None

    def _handle_missing(
        self,
        reference: WorkflowNodeWidgetRef,
        context: ModelResolutionContext
    ) -> ResolvedModel | None:
        """Handle missing models with search and refinement loop."""
        print(f"\n⚠️  Model not found: {reference.widget_value}")
        print(f"  in node #{reference.node_id} ({reference.node_type})")

        if not context.search_fn:
            # No search available - can only mark optional, download, or skip
            options = "\n  [o] - Mark as optional"
            if context.downloader:
                options += "\n  [d] - Download from URL"
            options += "\n  [s] - Skip"

            prompt = "Choice [o]/s: " if not context.downloader else "Choice [o]/d/s: "
            print(options)
            choice = self._unified_choice_prompt(prompt, num_options=0, has_browse=False)

            if choice == 'o':
                return ResolvedModel(
                    workflow=context.workflow_name,
                    reference=reference,
                    resolved_model=None,
                    is_optional=True,
                    match_type="optional_unresolved",
                    match_confidence=1.0
                )
            elif choice == 'd' and context.downloader:
                return self._handle_download(reference, context)
            return None

        # Search with refinement loop
        search_term = reference.widget_value

        while True:
            print(f"\n🔍 Searching for: {search_term}")

            results = context.search_fn(
                search_term=search_term,
                node_type=reference.node_type,
                limit=5
            )

            if results:
                # Show results with refinement option
                result = self._show_search_results_with_refinement(
                    reference, results, context
                )

                if result == "REFINE":
                    # User wants to refine search
                    new_term = input("\nEnter new search term: ").strip()
                    if new_term:
                        search_term = new_term
                        continue
                    else:
                        print("  Keeping previous search term")
                        continue
                else:
                    # User made a choice (model, optional, or skip)
                    assert isinstance(result, ResolvedModel) or result is None
                    return result
            else:
                # No results found
                print("  No models found")
                print("\n  [r] - Refine search")
                if context.downloader:
                    print("  [d] - Download from URL")
                print("  [o] - Mark as optional")
                print("  [s] - Skip")

                prompt = "Choice [r]/o/s: " if not context.downloader else "Choice [r]/d/o/s: "
                choice = self._unified_choice_prompt(prompt, num_options=0, has_browse=False)

                if choice == 'r':
                    new_term = input("\nEnter new search term: ").strip()
                    if new_term:
                        search_term = new_term
                        continue
                elif choice == 'd' and context.downloader:
                    result = self._handle_download(reference, context)
                    if result is not None:
                        return result
                    # User pressed back - continue to show menu again
                    continue
                elif choice == 'o':
                    return ResolvedModel(
                        workflow=context.workflow_name,
                        reference=reference,
                        resolved_model=None,
                        is_optional=True,
                        match_type="optional_unresolved",
                        match_confidence=1.0
                    )
                return None

    def _show_search_results_with_refinement(
        self,
        reference: WorkflowNodeWidgetRef,
        results: list[ScoredMatch],
        context: ModelResolutionContext
    ) -> ResolvedModel | None | str:
        """Show search results with refinement option.

        Shows up to 9 results max (per UX doc - no pagination).

        Returns:
            ResolvedModel - user selected a model
            "REFINE" - user wants to refine search
            None - user skipped
        """
        # Show up to 9 matches (UX doc spec - no pagination)
        display_count = min(9, len(results))
        print(f"\nFound {len(results)} matches:\n")

        for i, match in enumerate(results[:display_count], 1):
            model = match.model
            size_gb = model.file_size / (1024 * 1024 * 1024)
            confidence = match.confidence.capitalize()
            print(f"  {i}. {model.relative_path} ({size_gb:.2f} GB)")
            print(f"     {confidence} confidence match\n")

        print("  [r] Refine search")
        if context.downloader:
            print("  [d] Download from URL")
        print("  [o] Mark as optional")
        print("  [s] Skip\n")

        prompt = "Choice [1]/r/o/s: " if not context.downloader else "Choice [1]/r/d/o/s: "
        choice = self._unified_choice_prompt(
            prompt,
            num_options=display_count,
            has_browse=False
        )

        if choice == 's':
            return None
        elif choice == 'r':
            return "REFINE"
        elif choice == 'd' and context.downloader:
            result = self._handle_download(reference, context)
            if result is not None:
                return result
            # User pressed back - return to search results
            return "REFINE"
        elif choice == 'o':
            return ResolvedModel(
                workflow=context.workflow_name,
                reference=reference,
                resolved_model=None,
                is_optional=True,
                match_type="optional_unresolved",
                match_confidence=1.0
            )
        else:
            idx = int(choice) - 1
            selected = results[idx].model
            print(f"\n✓ Selected: {selected.relative_path}")
            return ResolvedModel(
                workflow=context.workflow_name,
                reference=reference,
                resolved_model=selected,
                is_optional=False,
                match_type="user_confirmed",
                match_confidence=1.0
            )


    def _handle_download(
        self,
        reference: WorkflowNodeWidgetRef,
        context: ModelResolutionContext
    ) -> ResolvedModel | None:
        """Handle download intent collection with path confirmation.

        Returns download intent instead of immediately downloading the model.
        Actual downloads happen in batch at the end of resolution.

        Args:
            reference: Model reference from workflow
            context: Resolution context

        Returns:
            ResolvedModel with download_intent if user provides URL, None to skip
        """
        from pathlib import Path

        if not context.downloader:
            print("  Download not available")
            return None

        # Step 1: Get URL
        url = input("\nEnter download URL: ").strip()
        if not url:
            print("  Cancelled")
            return None

        # Step 2: Suggest path
        suggested_path = context.downloader.suggest_path(
            url=url,
            node_type=reference.node_type,
            filename_hint=reference.widget_value
        )

        # Step 3: Path confirmation loop
        while True:
            print("\nModel will be downloaded to:")
            print(f"  {suggested_path}")
            print("\n[Y] Continue  [m] Change path  [b] Back to menu")

            choice = input("Choice [Y]/m/b: ").strip().lower()

            if choice == 'b':
                return None  # Back to menu
            elif choice == 'm':
                new_path = input("Enter path: ").strip()
                if new_path:
                    suggested_path = Path(new_path)
                continue
            elif choice in ('', 'y'):
                break

        # Step 4: Return download intent (actual download happens in batch at end)
        print(f"  ✓ Download queued: {suggested_path}")
        return ResolvedModel(
            workflow=context.workflow_name,
            reference=reference,
            resolved_model=None,  # Not downloaded yet
            model_source=url,
            is_optional=False,
            match_type="download_intent",
            target_path=suggested_path
        )

    def _browse_all_models(self, results: list[ScoredMatch]) -> ModelWithLocation | str | None:
        """Browse all fuzzy search results with pagination.

        Returns:
            ModelWithLocation if user selects a model
            "BACK" if user cancels
            None if user quits
        """
        page = 0
        page_size = 10
        total_pages = (len(results) + page_size - 1) // page_size

        while True:
            start = page * page_size
            end = min(start + page_size, len(results))

            print(f"\nAll matches (Page {page + 1}/{total_pages}):\n")

            for i, match in enumerate(results[start:end], start + 1):
                model = match.model
                size_gb = model.file_size / (1024 * 1024 * 1024)
                print(f"  {i}. {model.relative_path} ({size_gb:.2f} GB)")

            print("\n[N]ext, [P]rev, number, [B]ack, or [Q]uit:")

            choice = input("Choice: ").strip().lower()

            if choice == 'n':
                if page < total_pages - 1:
                    page += 1
                else:
                    print("  Already on last page")
            elif choice == 'p':
                if page > 0:
                    page -= 1
                else:
                    print("  Already on first page")
            elif choice == 'b':
                return "BACK"
            elif choice == 'q':
                return None
            elif choice.isdigit():
                idx = int(choice) - 1
                if 0 <= idx < len(results):
                    return results[idx].model
                else:
                    print("  Invalid number")
            else:
                print("  Invalid choice")


