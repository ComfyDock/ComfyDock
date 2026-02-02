#!/usr/bin/env python3
"""Test concurrent API requests to ComfyUI registry."""

import argparse
import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import datetime

import aiohttp


@dataclass
class RequestResult:
    """Track individual request results."""
    node_id: str
    success: bool
    duration: float
    error: str | None = None
    status_code: int | None = None
    version_count: int = 0


@dataclass
class TestResults:
    """Aggregate test results."""
    total_requests: int = 0
    successful: int = 0
    failed: int = 0
    total_duration: float = 0
    errors_by_type: dict[str, int] = field(default_factory=dict)
    failed_nodes: list[str] = field(default_factory=list)
    results: list[RequestResult] = field(default_factory=list)


class ConcurrentAPITester:
    """Test concurrent API requests with configurable concurrency."""

    def __init__(self, base_url: str = "https://api.comfy.org", concurrency: int = 20):
        self.base_url = base_url
        self.concurrency = concurrency
        self.semaphore = asyncio.Semaphore(concurrency)

    async def get_nodes_list(self, limit: int = 50) -> list[str]:
        """Get first page of nodes."""
        async with aiohttp.ClientSession() as session:
            url = f"{self.base_url}/nodes"
            params = {"page": 1, "limit": limit}

            try:
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        nodes = data.get("nodes", [])
                        return [node["id"] for node in nodes]
                    else:
                        print(f"Failed to get nodes list: HTTP {response.status}")
                        return []
            except Exception as e:
                print(f"Error fetching nodes list: {e}")
                return []

    async def fetch_versions(self, session: aiohttp.ClientSession, node_id: str) -> RequestResult:
        """Fetch versions for a single node."""
        url = f"{self.base_url}/nodes/{node_id}/versions"
        start_time = time.time()

        async with self.semaphore:  # Limit concurrent requests
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    duration = time.time() - start_time

                    if response.status == 200:
                        versions = await response.json()
                        return RequestResult(
                            node_id=node_id,
                            success=True,
                            duration=duration,
                            status_code=response.status,
                            version_count=len(versions) if isinstance(versions, list) else 0
                        )
                    else:
                        error_text = await response.text()
                        return RequestResult(
                            node_id=node_id,
                            success=False,
                            duration=duration,
                            status_code=response.status,
                            error=f"HTTP {response.status}: {error_text[:100]}"
                        )

            except asyncio.TimeoutError:
                duration = time.time() - start_time
                return RequestResult(
                    node_id=node_id,
                    success=False,
                    duration=duration,
                    error="Timeout (10s)"
                )
            except aiohttp.ClientError as e:
                duration = time.time() - start_time
                return RequestResult(
                    node_id=node_id,
                    success=False,
                    duration=duration,
                    error=f"ClientError: {str(e)[:100]}"
                )
            except Exception as e:
                duration = time.time() - start_time
                return RequestResult(
                    node_id=node_id,
                    success=False,
                    duration=duration,
                    error=f"Unexpected: {str(e)[:100]}"
                )

    async def run_concurrent_test(self, node_ids: list[str]) -> TestResults:
        """Run concurrent version fetches for given nodes."""
        results = TestResults()
        results.total_requests = len(node_ids)

        print(f"\n{'='*60}")
        print(f"Starting concurrent test with {self.concurrency} max connections")
        print(f"Testing {len(node_ids)} nodes")
        print(f"{'='*60}\n")

        # Create connector with connection pooling
        connector = aiohttp.TCPConnector(
            limit=self.concurrency,
            limit_per_host=self.concurrency
        )

        async with aiohttp.ClientSession(connector=connector) as session:
            # Create tasks for all nodes
            tasks = [self.fetch_versions(session, node_id) for node_id in node_ids]

            # Run all tasks concurrently
            start_time = time.time()
            request_results = await asyncio.gather(*tasks, return_exceptions=False)
            results.total_duration = time.time() - start_time

            # Process results
            for result in request_results:
                results.results.append(result)

                if result.success:
                    results.successful += 1
                else:
                    results.failed += 1
                    results.failed_nodes.append(result.node_id)

                    # Categorize errors
                    if result.error:
                        if "Timeout" in result.error:
                            error_type = "Timeout"
                        elif "HTTP" in result.error:
                            error_type = f"HTTP {result.status_code}"
                        elif "ClientError" in result.error:
                            error_type = "ClientError"
                        else:
                            error_type = "Other"

                        results.errors_by_type[error_type] = results.errors_by_type.get(error_type, 0) + 1

        return results

    def print_results(self, results: TestResults):
        """Print formatted test results."""
        print(f"\n{'='*60}")
        print(f"Test Results - Concurrency: {self.concurrency}")
        print(f"{'='*60}\n")

        print(f"Total requests: {results.total_requests}")
        print(f"Successful: {results.successful} ({results.successful/results.total_requests*100:.1f}%)")
        print(f"Failed: {results.failed} ({results.failed/results.total_requests*100:.1f}%)")
        print(f"Total duration: {results.total_duration:.2f}s")
        print(f"Avg time per request: {results.total_duration/results.total_requests:.3f}s")

        if results.successful > 0:
            successful_results = [r for r in results.results if r.success]
            avg_duration = sum(r.duration for r in successful_results) / len(successful_results)
            min_duration = min(r.duration for r in successful_results)
            max_duration = max(r.duration for r in successful_results)

            print("\nSuccessful request stats:")
            print(f"  Average: {avg_duration:.3f}s")
            print(f"  Min: {min_duration:.3f}s")
            print(f"  Max: {max_duration:.3f}s")

            # Version counts
            total_versions = sum(r.version_count for r in successful_results)
            print(f"  Total versions fetched: {total_versions}")

        if results.errors_by_type:
            print("\nErrors by type:")
            for error_type, count in sorted(results.errors_by_type.items()):
                print(f"  {error_type}: {count}")

        if results.failed_nodes:
            print(f"\nFailed nodes ({len(results.failed_nodes)}):")
            for node_id in results.failed_nodes[:5]:  # Show first 5
                result = next(r for r in results.results if r.node_id == node_id and not r.success)
                print(f"  - {node_id}: {result.error}")
            if len(results.failed_nodes) > 5:
                print(f"  ... and {len(results.failed_nodes) - 5} more")

        # Calculate theoretical time without concurrency
        if results.successful > 0:
            sequential_time = sum(r.duration for r in results.results if r.success)
            speedup = sequential_time / results.total_duration
            print("\nPerformance:")
            print(f"  Sequential time (estimated): {sequential_time:.2f}s")
            print(f"  Concurrent time: {results.total_duration:.2f}s")
            print(f"  Speedup: {speedup:.1f}x")
            print(f"  Efficiency: {speedup/self.concurrency*100:.1f}%")


async def test_multiple_concurrency_levels(node_ids: list[str], levels: list[int]):
    """Test multiple concurrency levels."""
    all_results = {}

    for concurrency in levels:
        print(f"\n{'#'*60}")
        print(f"Testing with concurrency level: {concurrency}")
        print(f"{'#'*60}")

        tester = ConcurrentAPITester(concurrency=concurrency)
        results = await tester.run_concurrent_test(node_ids)
        tester.print_results(results)
        all_results[concurrency] = results

        # Wait between tests to avoid rate limiting
        if concurrency != levels[-1]:
            print("\nWaiting 2 seconds before next test...")
            await asyncio.sleep(2)

    # Summary comparison
    print(f"\n{'='*60}")
    print("Summary Comparison")
    print(f"{'='*60}\n")

    print(f"{'Concurrency':<12} {'Duration':<10} {'Success%':<10} {'Speedup':<10}")
    print("-" * 45)

    for concurrency, results in all_results.items():
        success_pct = results.successful / results.total_requests * 100
        base_duration = list(all_results.values())[0].total_duration
        speedup = base_duration / results.total_duration if results.total_duration > 0 else 0

        print(f"{concurrency:<12} {results.total_duration:<10.2f} {success_pct:<10.1f} {speedup:<10.1f}x")


async def main():
    parser = argparse.ArgumentParser(description="Test concurrent API requests to ComfyUI registry")
    parser.add_argument("--concurrency", type=int, default=20,
                       help="Number of concurrent requests (default: 20)")
    parser.add_argument("--nodes", type=int, default=20,
                       help="Number of nodes to test (default: 20)")
    parser.add_argument("--test-levels", nargs="+", type=int,
                       help="Test multiple concurrency levels (e.g., --test-levels 1 5 10 20 50)")
    parser.add_argument("--json-output", type=str,
                       help="Save results to JSON file")

    args = parser.parse_args()

    # Get list of nodes
    print("Fetching nodes list...")
    tester = ConcurrentAPITester()
    node_ids = await tester.get_nodes_list(limit=max(50, args.nodes))

    if not node_ids:
        print("Failed to get nodes list!")
        return

    # Limit to requested number
    node_ids = node_ids[:args.nodes]
    print(f"Got {len(node_ids)} nodes")

    # Run tests
    if args.test_levels:
        await test_multiple_concurrency_levels(node_ids, args.test_levels)
    else:
        tester = ConcurrentAPITester(concurrency=args.concurrency)
        results = await tester.run_concurrent_test(node_ids)
        tester.print_results(results)

        # Save JSON output if requested
        if args.json_output:
            output_data = {
                "timestamp": datetime.now().isoformat(),
                "concurrency": args.concurrency,
                "total_requests": results.total_requests,
                "successful": results.successful,
                "failed": results.failed,
                "duration": results.total_duration,
                "errors_by_type": results.errors_by_type,
                "failed_nodes": results.failed_nodes,
                "results": [
                    {
                        "node_id": r.node_id,
                        "success": r.success,
                        "duration": r.duration,
                        "error": r.error,
                        "status_code": r.status_code,
                        "version_count": r.version_count
                    }
                    for r in results.results
                ]
            }

            with open(args.json_output, 'w') as f:
                json.dump(output_data, f, indent=2)
            print(f"\nResults saved to {args.json_output}")


if __name__ == "__main__":
    asyncio.run(main())
