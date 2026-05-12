from comfygit_core.lifecycle.comfyui_readiness import resolve_comfyui_endpoint


def test_resolve_comfyui_endpoint_defaults_to_localhost():
    endpoint = resolve_comfyui_endpoint([])

    assert endpoint.bind_host == "127.0.0.1"
    assert endpoint.check_host == "127.0.0.1"
    assert endpoint.port == 8188
    assert endpoint.base_url == "http://127.0.0.1:8188"


def test_resolve_comfyui_endpoint_uses_last_port_override():
    endpoint = resolve_comfyui_endpoint(["--port", "8190", "--port=8200"])

    assert endpoint.port == 8200
    assert endpoint.base_url == "http://127.0.0.1:8200"


def test_resolve_comfyui_endpoint_maps_wildcard_listen_to_local_probe():
    endpoint = resolve_comfyui_endpoint(["--listen", "0.0.0.0", "--port", "8190"])

    assert endpoint.bind_host == "0.0.0.0"
    assert endpoint.check_host == "127.0.0.1"
    assert endpoint.base_url == "http://127.0.0.1:8190"


def test_resolve_comfyui_endpoint_preserves_explicit_listen_host():
    endpoint = resolve_comfyui_endpoint(["--listen", "100.99.14.94", "--port", "8190"])

    assert endpoint.bind_host == "100.99.14.94"
    assert endpoint.check_host == "100.99.14.94"
    assert endpoint.base_url == "http://100.99.14.94:8190"


def test_resolve_comfyui_endpoint_handles_bare_listen_flag():
    endpoint = resolve_comfyui_endpoint(["--listen", "--port", "8190"])

    assert endpoint.bind_host == "0.0.0.0"
    assert endpoint.check_host == "127.0.0.1"
    assert endpoint.port == 8190
