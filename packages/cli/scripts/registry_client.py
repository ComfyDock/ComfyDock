#!/usr/bin/env python3
"""Shared registry client for ComfyUI API interactions."""

import asyncio

import aiohttp
from comfygit_core.logging.logging_config import get_logger

logger = get_logger(__name__)


class RegistryClient:
    """Async client for ComfyUI registry API."""

    def __init__(self, base_url: str = "https://api.comfy.org", concurrency: int = 10):
        self.base_url = base_url
        self.session = None
        self.concurrency = concurrency
        self.semaphore = asyncio.Semaphore(concurrency)

    async def __aenter__(self):
        connector = aiohttp.TCPConnector(
            limit=max(self.concurrency * 2, 100),
            limit_per_host=max(self.concurrency, 50),
            force_close=True
        )
        timeout = aiohttp.ClientTimeout(
            total=30,
            connect=10,
            sock_read=10
        )
        self.session = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def get_all_nodes(self, page_size: int = 100, max_pages: int | None = None) -> list[dict]:
        """Fetch all nodes from registry."""
        all_nodes = []
        page = 1
        total_pages = None

        while True:
            if max_pages and page > max_pages:
                logger.info(f"Reached max_pages limit ({max_pages})")
                break

            logger.debug(f"Fetching nodes page {page}...")
            url = f"{self.base_url}/nodes"
            params = {"page": page, "limit": page_size}

            try:
                async with self.session.get(url, params=params) as response:
                    if response.status != 200:
                        logger.error(f"Failed to fetch nodes page {page}: {response.status}")
                        break

                    data = await response.json()
                    nodes = data.get("nodes", [])

                    if nodes:
                        all_nodes.extend(nodes)
                        logger.debug(f"Page {page}: Found {len(nodes)} nodes")

                    if total_pages is None:
                        total_pages = data.get("totalPages", 1)
                        logger.info(f"Total pages to fetch: {total_pages}")

                    if page >= total_pages or not nodes:
                        break

                    page += 1
                    await asyncio.sleep(0.1)  # Rate limit between pages

            except Exception as e:
                logger.error(f"Error fetching page {page}: {e}")
                break

        logger.info(f"Fetched {len(all_nodes)} nodes from registry")
        return all_nodes

    async def get_node(self, node_id: str) -> dict | None:
        """Get single node by ID."""
        url = f"{self.base_url}/nodes/{node_id}"

        try:
            async with self.session.get(url) as response:
                if response.status != 200:
                    logger.error(f"Failed to fetch node {node_id}: {response.status}")
                    return None
                return await response.json()
        except Exception as e:
            logger.error(f"Error fetching node {node_id}: {e}")
            return None

    async def get_node_versions(self, node_id: str) -> list[dict]:
        """Get all versions for a node."""
        url = f"{self.base_url}/nodes/{node_id}/versions"

        try:
            async with self.session.get(url) as response:
                if response.status != 200:
                    logger.debug(f"No versions for {node_id}: {response.status}")
                    return []

                versions = await response.json()
                if not isinstance(versions, list):
                    logger.warning(f"Unexpected versions format for {node_id}")
                    return []

                # Filter active versions and sort
                active_versions = [v for v in versions if not v.get("deprecated", False)]
                active_versions.sort(key=lambda v: v.get("version", ""))

                return active_versions

        except Exception as e:
            logger.warning(f"Error fetching versions for {node_id}: {e}")
            return []

    async def get_install_info(self, node_id: str, version: str) -> dict | None:
        """Get install info for specific version."""
        url = f"{self.base_url}/nodes/{node_id}/install"
        params = {"version": version}

        try:
            async with self.session.get(url, params=params) as response:
                if response.status != 200:
                    logger.debug(f"No install info for {node_id}@{version}")
                    return None
                return await response.json()
        except Exception as e:
            logger.debug(f"Error fetching install info for {node_id}@{version}: {e}")
            return None

    async def get_comfy_nodes(self, node_id: str, version: str) -> list[dict] | None:
        """Get comfy-nodes metadata for a specific version with pagination."""
        all_comfy_nodes = []
        page = 1
        total_pages = None
        max_pages = 100

        while page <= max_pages:
            url = f"{self.base_url}/nodes/{node_id}/versions/{version}/comfy-nodes"
            params = {"page": page}

            try:
                async with self.session.get(url, params=params) as response:
                    if response.status != 200:
                        if page == 1:
                            logger.debug(f"No comfy-nodes for {node_id}@{version}")
                        return all_comfy_nodes if all_comfy_nodes else None

                    data = await response.json()
                    comfy_nodes = data.get("comfy_nodes", [])

                    if comfy_nodes:
                        all_comfy_nodes.extend(comfy_nodes)
                        logger.debug(f"Page {page}: Found {len(comfy_nodes)} comfy-nodes for {node_id}@{version}")

                    if total_pages is None:
                        total_pages = data.get("totalPages", data.get("totalNumberOfPages", 1))
                        if total_pages > 1:
                            logger.debug(f"Node {node_id}@{version} has {total_pages} pages of metadata")

                    if page >= total_pages or not comfy_nodes:
                        break

                    page += 1
                    await asyncio.sleep(0.05)

            except Exception as e:
                logger.debug(f"Error fetching comfy-nodes page {page} for {node_id}@{version}: {e}")
                break

        if all_comfy_nodes:
            logger.debug(f"Total: Found {len(all_comfy_nodes)} comfy-nodes across {page - 1} pages for {node_id}@{version}")

        return all_comfy_nodes if all_comfy_nodes else None
