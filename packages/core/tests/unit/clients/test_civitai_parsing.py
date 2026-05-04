"""Comprehensive tests for CivitAI API response parsing."""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from comfygit_core.caching.api_cache import APICacheManager
from comfygit_core.clients.civitai_client import CivitAIClient
from comfygit_core.models.civitai import (
    CivitAIFile,
    CivitAIModel,
    CivitAIModelVersion,
    FileFormat,
    FileHashes,
    FloatPrecision,
    ModelSize,
    ModelType,
)


@pytest.fixture
def cache_manager():
    """Create a temporary cache manager for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield APICacheManager(cache_base_path=Path(tmpdir))


class TestCivitAIResponseParsing:
    """Test parsing of real CivitAI API responses."""

    def test_unknown_provider_enums_are_preserved(self):
        """CivitAI can add enum values before docs/models are updated."""
        parsed = CivitAIFile.from_api_data({
            "id": 1,
            "name": "diffusers-model",
            "sizeKB": 1.0,
            "metadata": {
                "fp": "bf16",
                "size": "custom",
                "format": "Diffusers",
            },
        })

        assert parsed.fp == "bf16"
        assert parsed.size == "custom"
        assert parsed.format == "Diffusers"

    @patch("urllib.request.urlopen")
    def test_parse_model_search_response(self, mock_urlopen, cache_manager):
        """Test parsing complex model search response with TextualInversion."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = json.dumps({
            "items": [
                {
                    "id": 3036,
                    "name": "CharTurner - Character Turnaround helper for 1.5 AND 2.1!",
                    "description": "<h1>CharTurner</h1><p>Edit: <strong>controlNet</strong> works...",
                    "type": "TextualInversion",
                    "poi": False,
                    "nsfw": False,
                    "allowNoCredit": True,
                    "allowCommercialUse": "Rent",
                    "allowDerivatives": True,
                    "allowDifferentLicense": True,
                    "stats": {
                        "downloadCount": 56206,
                        "favoriteCount": 7433,
                        "commentCount": 236,
                        "ratingCount": 56,
                        "rating": 4.63
                    },
                    "creator": {
                        "username": "mousewrites",
                        "image": "https://imagecache.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/bdfe115f-4430-4ee7-31bc-eff38f86c500/width=96/mousewrites.jpeg"
                    },
                    "tags": [
                        "character",
                        "consistent character",
                        "turnaround",
                        "model sheet"
                    ],
                    "modelVersions": [
                        {
                            "id": 9857,
                            "modelId": 3036,
                            "name": "CharTurner V2 - For 2.1",
                            "createdAt": "2023-02-12T22:44:01.442Z",
                            "updatedAt": "2023-03-15T18:58:13.476Z",
                            "trainedWords": ["21charturnerv2"],
                            "baseModel": "SD 2.1",
                            "earlyAccessTimeFrame": 0,
                            "description": "<p>I'm not great at prompting for 2.1 yet...</p>",
                            "stats": {
                                "downloadCount": 25874,
                                "ratingCount": 7,
                                "rating": 4.29
                            },
                            "files": [
                                {
                                    "name": "21charturnerv2.pt",
                                    "id": 9500,
                                    "sizeKB": 17.017578125,
                                    "type": "Model",
                                    "metadata": {
                                        "fp": "fp16",
                                        "size": "full",
                                        "format": "PickleTensor"
                                    },
                                    "pickleScanResult": "Success",
                                    "pickleScanMessage": "No Pickle imports",
                                    "virusScanResult": "Success",
                                    "scannedAt": "2023-02-12T22:45:53.210Z",
                                    "hashes": {
                                        "AutoV2": "F253ABB016",
                                        "SHA256": "F253ABB016C22DD426D6E482F4F8C3960766DE6E4C02F151478BFB98F6985383",
                                        "CRC32": "F500AADD",
                                        "BLAKE3": "E7163C1A3F6B135A3E473CDD749BC1E6F4ED2D1AB43FEB1ACC4BEB1E5C205260"
                                    },
                                    "downloadUrl": "https://civitai.com/api/download/models/9857",
                                    "primary": True
                                }
                            ],
                            "images": [
                                {
                                    "url": "https://imagecache.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/d197481b-1c21-4c14-c7fd-708f838a1000/width=450/96744.jpeg",
                                    "nsfw": False,
                                    "width": 1238,
                                    "height": 1293,
                                    "hash": "UAEVA;?]JoR6+^OaNxxC^jXSWXjF?G$~s.WY",
                                    "meta": None
                                }
                            ],
                            "downloadUrl": "https://civitai.com/api/download/models/9857"
                        }
                    ]
                }
            ],
            "metadata": {
                "totalItems": "1676",
                "currentPage": "1",
                "pageSize": "3",
                "totalPages": "559",
                "nextPage": "https://civitai.com/api/v1/models?limit=3&types=TextualInversion&page=2"
            }
        }).encode()
        mock_urlopen.return_value.__enter__.return_value = mock_response

        client = CivitAIClient(cache_manager=cache_manager)
        response = client.search_models(limit=3, types=[ModelType.TEXTUAL_INVERSION])

        # Test response metadata
        assert response.total_items == 1676
        assert response.current_page == 1
        assert response.page_size == 3
        assert response.total_pages == 559
        assert response.next_page is not None

        # Test model parsing
        model = response.items[0]
        assert model.id == 3036
        assert model.name == "CharTurner - Character Turnaround helper for 1.5 AND 2.1!"
        assert model.type == ModelType.TEXTUAL_INVERSION
        assert not model.nsfw
        assert len(model.tags) == 4
        assert "character" in model.tags

        # Test creator
        assert model.creator is not None
        assert model.creator.username == "mousewrites"
        assert model.creator.image is not None

        # Test stats
        assert model.download_count == 56206
        assert model.favorite_count == 7433
        assert model.rating == 4.63

        # Test version parsing
        assert len(model.model_versions) == 1
        version = model.model_versions[0]
        assert version.id == 9857
        assert version.model_id == 3036
        assert version.name == "CharTurner V2 - For 2.1"
        assert version.base_model == "SD 2.1"
        assert version.trained_words == ["21charturnerv2"]

        # Test file parsing
        assert len(version.files) == 1
        file = version.files[0]
        assert file.id == 9500
        assert file.name == "21charturnerv2.pt"
        assert file.size_kb == 17.017578125
        assert file.primary
        assert file.fp == FloatPrecision.FP16
        assert file.size == ModelSize.FULL
        assert file.format == FileFormat.PICKLE_TENSOR

        # Test hash parsing
        assert file.hashes is not None
        assert file.hashes.auto_v2 == "F253ABB016"
        assert file.hashes.sha256 == "F253ABB016C22DD426D6E482F4F8C3960766DE6E4C02F151478BFB98F6985383"
        assert file.hashes.crc32 == "F500AADD"
        assert file.hashes.blake3 == "E7163C1A3F6B135A3E473CDD749BC1E6F4ED2D1AB43FEB1ACC4BEB1E5C205260"

    @patch("urllib.request.urlopen")
    def test_parse_single_model_with_tags_as_objects(self, mock_urlopen, cache_manager):
        """Test parsing single model response with tags as objects."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = json.dumps({
            "id": 1102,
            "name": "SynthwavePunk",
            "description": "<p>This is a 50/50 Merge...</p>",
            "type": "Checkpoint",
            "poi": False,
            "nsfw": False,
            "allowNoCredit": True,
            "allowCommercialUse": "Sell",
            "allowDerivatives": True,
            "allowDifferentLicense": True,
            "stats": {
                "downloadCount": 15347,
                "favoriteCount": 2540,
                "commentCount": 22,
                "ratingCount": 27,
                "rating": 4.93
            },
            "creator": {
                "username": "justmaier",
                "image": "https://imagecache.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/6046154e-6d32-4500-8772-602edb4a4600/width=96/justmaier.jpeg"
            },
            "tags": [
                {"name": "punk"},
                {"name": "synthwave"},
                {"name": "style"}
            ],
            "modelVersions": [
                {
                    "id": 1292,
                    "modelId": 1102,
                    "name": "V3 Alpha",
                    "createdAt": "2022-12-07T10:40:26.799Z",
                    "updatedAt": "2023-02-18T23:08:24.115Z",
                    "trainedWords": ["nvinkpunk", "snthwve style", "style of joemadureira"],
                    "baseModel": "SD 1.5",
                    "earlyAccessTimeFrame": 0,
                    "description": "<p>I wanted something that gave characters...</p>",
                    "stats": {
                        "downloadCount": 761,
                        "ratingCount": 5,
                        "rating": 5
                    },
                    "files": [
                        {
                            "name": "synthwavepunk_v3Alpha.ckpt",
                            "id": 5149,
                            "sizeKB": 2082918.40625,
                            "type": "Model",
                            "metadata": {
                                "fp": "fp16",
                                "size": "full",
                                "format": "PickleTensor"
                            },
                            "pickleScanResult": "Success",
                            "pickleScanMessage": "**Detected Pickle imports (5)**\n```\ncollections.OrderedDict\ntorch._utils._rebuild_tensor_v2\ntorch.HalfStorage\ntorch.IntStorage\ntorch.FloatStorage\n```",
                            "virusScanResult": "Success",
                            "scannedAt": "2023-01-14T03:05:15.488Z",
                            "hashes": {
                                "AutoV1": "9CE5CEA2",
                                "AutoV2": "76F3EED071",
                                "SHA256": "76F3EED071327C9075053368D6997CD613AF949D10B2D3034CEF30A1D1D9FEBA",
                                "CRC32": "F15BA0A8",
                                "BLAKE3": "F83958C6BD911A59456186EA466C2C17B1827178324CF03CC6C427FB064FFFF9"
                            },
                            "downloadUrl": "https://civitai.com/api/download/models/1292?type=Model&format=PickleTensor"
                        },
                        {
                            "name": "synthwavepunk_v3Alpha.safetensors",
                            "id": 194,
                            "sizeKB": 2082691,
                            "type": "Model",
                            "metadata": {
                                "fp": "fp16",
                                "size": "full",
                                "format": "SafeTensor"
                            },
                            "pickleScanResult": "Success",
                            "pickleScanMessage": "No Pickle imports",
                            "virusScanResult": "Success",
                            "scannedAt": "2022-12-07T10:49:05.931Z",
                            "hashes": {
                                "AutoV1": "5D83B27C",
                                "AutoV2": "EE2AB6D872",
                                "SHA256": "EE2AB6D8723611D9A2FA9B0C8CE5A3770A84189A92B53D5E6CF44B02B9F8E033",
                                "CRC32": "97DD6FF4",
                                "BLAKE3": "910E778DE880D7EA9511A075B5D4C59B9ED1EE7A9C6B98FFE4EB5C198F0E5240"
                            },
                            "downloadUrl": "https://civitai.com/api/download/models/1292",
                            "primary": True
                        }
                    ],
                    "images": [
                        {
                            "url": "https://imagecache.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/e82adceb-cae1-45c5-ab39-74850d027200/width=450/10650.jpeg",
                            "nsfw": True,
                            "width": 512,
                            "height": 704,
                            "hash": "USI=DS+|?^V[7z55K#X-DkV[IVtQR*$%V?In",
                            "meta": {
                                "ENSD": "31337",
                                "Size": "512x704",
                                "seed": 107073939,
                                "Model": "joMad+synth-ink-25",
                                "steps": 24,
                                "prompt": "style of joemadureira...",
                                "sampler": "DPM++ 2M Karras",
                                "cfgScale": 7,
                                "Batch pos": "2",
                                "Batch size": "4",
                                "Model hash": "5d83b27c",
                                "negativePrompt": "cartoon, 3d..."
                            }
                        }
                    ],
                    "downloadUrl": "https://civitai.com/api/download/models/1292"
                }
            ]
        }).encode()
        mock_urlopen.return_value.__enter__.return_value = mock_response

        client = CivitAIClient(cache_manager=cache_manager)
        model = client.get_model(1102)

        assert model is not None
        assert model.id == 1102
        assert model.name == "SynthwavePunk"
        assert model.type == ModelType.CHECKPOINT

        # Test tags parsing from objects
        assert len(model.tags) == 3
        assert "punk" in model.tags
        assert "synthwave" in model.tags
        assert "style" in model.tags

        # Test multiple files in version
        version = model.model_versions[0]
        assert len(version.files) == 2

        # Test file with query params in URL
        ckpt_file = version.files[0]
        assert "?type=Model&format=PickleTensor" in ckpt_file.download_url
        assert ckpt_file.pickle_scan_message is not None
        assert "Detected Pickle imports" in ckpt_file.pickle_scan_message

        # Test primary file designation
        safetensors_file = version.files[1]
        assert safetensors_file.primary
        assert safetensors_file.format == FileFormat.SAFETENSOR

        # Test image metadata parsing
        image = version.images[0]
        assert image.nsfw
        assert image.meta is not None
        assert isinstance(image.meta, dict)
        assert image.meta.get("seed") == 107073939

    @patch("urllib.request.urlopen")
    def test_parse_model_version_response(self, mock_urlopen, cache_manager):
        """Test parsing model version endpoint response with parent model info."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = json.dumps({
            "id": 1318,
            "modelId": 1244,
            "name": "toad",
            "createdAt": "2022-12-08T19:58:49.765Z",
            "updatedAt": "2022-12-08T20:24:50.330Z",
            "trainedWords": ["ttdddd"],
            "baseModel": "SD 1.5",
            "earlyAccessTimeFrame": 0,
            "description": None,
            "stats": {
                "downloadCount": 438,
                "ratingCount": 1,
                "rating": 5
            },
            "model": {
                "name": "froggy style",
                "type": "Checkpoint",
                "nsfw": False,
                "poi": False
            },
            "files": [
                {
                    "name": "froggyStyle_toad.ckpt",
                    "id": 289,
                    "sizeKB": 2546414.971679688,
                    "type": "Model",
                    "metadata": {
                        "fp": "fp16",
                        "size": "full",
                        "format": "PickleTensor"
                    },
                    "pickleScanResult": "Success",
                    "pickleScanMessage": "**Detected Pickle imports (3)**\n```\ncollections.OrderedDict\ntorch.HalfStorage\ntorch._utils._rebuild_tensor_v2\n```",
                    "virusScanResult": "Success",
                    "scannedAt": "2022-12-08T20:15:36.133Z",
                    "hashes": {
                        "AutoV1": "5F06AA6F",
                        "AutoV2": "0DF040C8CD",
                        "SHA256": "0DF040C8CD48125174B54C251A87822E8ED61D529A92C42C1FA1BEF483B10B0D",
                        "CRC32": "32AEB036",
                        "BLAKE3": "7E2030574C35F33545951E6588A19E41D88CEBB30598C17805A87EFFD0DB0A99"
                    },
                    "primary": True,
                    "downloadUrl": "https://civitai.com/api/download/models/1318"
                }
            ],
            "images": [
                {
                    "url": "https://imagecache.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/c6ed4a9d-ae75-463b-7762-da0455cc5700/width=450/10852.jpeg",
                    "nsfw": False,
                    "width": 832,
                    "height": 832,
                    "hash": "U8Civ__MTeSP?utJ9IDj?^Ek=}RQyEE1-Vr=",
                    "meta": None
                }
            ],
            "downloadUrl": "https://civitai.com/api/download/models/1318"
        }).encode()
        mock_urlopen.return_value.__enter__.return_value = mock_response

        client = CivitAIClient(cache_manager=cache_manager)
        version = client.get_model_version(1318)

        assert version is not None
        assert version.id == 1318
        assert version.model_id == 1244
        assert version.name == "toad"
        assert version.description is None  # Test null handling
        assert version.base_model == "SD 1.5"

        # Test parent model info
        assert version.model is not None
        assert version.model.name == "froggy style"
        assert version.model.type == "Checkpoint"
        assert not version.model.nsfw
        assert not version.model.poi

        # Test file with precise float size
        file = version.files[0]
        assert file.size_kb == 2546414.971679688
        assert file.primary

        # Test complete hash set
        hashes = file.hashes
        assert hashes.auto_v1 == "5F06AA6F"
        assert hashes.auto_v2 == "0DF040C8CD"
        assert hashes.sha256 == "0DF040C8CD48125174B54C251A87822E8ED61D529A92C42C1FA1BEF483B10B0D"
        assert hashes.crc32 == "32AEB036"
        assert hashes.blake3 == "7E2030574C35F33545951E6588A19E41D88CEBB30598C17805A87EFFD0DB0A99"

        # Test image with null meta
        image = version.images[0]
        assert image.meta is None
        assert image.width == 832
        assert image.height == 832

    @patch("urllib.request.urlopen")
    def test_parse_tags_response(self, mock_urlopen, cache_manager):
        """Test parsing tags endpoint response."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = json.dumps({
            "items": [
                {
                    "name": "Pepe Larraz",
                    "modelCount": 1,
                    "link": "https://civitai.com/api/v1/models?tag=Pepe Larraz"
                },
                {
                    "name": "comic book",
                    "modelCount": 7,
                    "link": "https://civitai.com/api/v1/models?tag=comic book"
                },
                {
                    "name": "style",
                    "modelCount": 91,
                    "link": "https://civitai.com/api/v1/models?tag=style"
                }
            ],
            "metadata": {
                "totalItems": "200",
                "currentPage": "1",
                "pageSize": "3",
                "totalPages": "67",
                "nextPage": "https://civitai.com/api/v1/tags?limit=3&page=2"
            }
        }).encode()
        mock_urlopen.return_value.__enter__.return_value = mock_response

        client = CivitAIClient(cache_manager=cache_manager)
        tags = client.get_tags(limit=3)

        assert len(tags) == 3
        assert tags[0].name == "Pepe Larraz"
        assert tags[0].model_count == 1
        assert tags[1].name == "comic book"
        assert tags[1].model_count == 7
        assert tags[2].name == "style"
        assert tags[2].model_count == 91

    @patch("urllib.request.urlopen")
    def test_edge_cases_empty_arrays_and_nulls(self, mock_urlopen, cache_manager):
        """Test handling of edge cases like empty arrays and null values."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = json.dumps({
            "items": [
                {
                    "id": 8109,
                    "name": "Test Model",
                    "description": None,
                    "type": "TextualInversion",
                    "poi": False,
                    "nsfw": False,
                    "stats": {
                        "downloadCount": 4698,
                        "favoriteCount": 0,
                        "commentCount": 0,
                        "ratingCount": 11,
                        "rating": 5
                    },
                    "creator": None,
                    "tags": [],
                    "modelVersions": [
                        {
                            "id": 9573,
                            "modelId": 8109,
                            "name": "1.0",
                            "createdAt": "2023-02-12T00:07:29.189Z",
                            "updatedAt": "2023-02-23T18:08:51.680Z",
                            "trainedWords": [],  # Empty array
                            "baseModel": "SD 1.4",
                            "earlyAccessTimeFrame": 0,
                            "description": None,  # Null description
                            "stats": {
                                "downloadCount": 4698,
                                "ratingCount": 11,
                                "rating": 5
                            },
                            "files": [],  # Empty files array
                            "images": [],  # Empty images array
                            "downloadUrl": "https://civitai.com/api/download/models/9573"
                        }
                    ]
                }
            ],
            "metadata": {
                "totalItems": "1",
                "currentPage": "1",
                "pageSize": "1",
                "totalPages": "1",
                "nextPage": None
            }
        }).encode()
        mock_urlopen.return_value.__enter__.return_value = mock_response

        client = CivitAIClient(cache_manager=cache_manager)
        response = client.search_models(limit=1)

        model = response.items[0]
        assert model.description is None
        assert model.creator is None
        assert model.tags == []

        version = model.model_versions[0]
        assert version.trained_words == []
        assert version.description is None
        assert version.files == []
        assert version.images == []

    def test_helper_methods(self):
        """Test helper methods on model objects."""
        # Create a model with versions and files
        model = CivitAIModel(
            id=1,
            name="Test Model",
            type=ModelType.CHECKPOINT,
            model_versions=[
                CivitAIModelVersion(
                    id=1,
                    model_id=1,
                    name="v1.0",
                    files=[
                        CivitAIFile(
                            id=1,
                            name="model.safetensors",
                            size_kb=1000,
                            primary=False,
                            hashes=FileHashes(
                                sha256="ABC123",
                                auto_v2="DEF456"
                            )
                        ),
                        CivitAIFile(
                            id=2,
                            name="model-primary.ckpt",
                            size_kb=2000,
                            primary=True,
                            hashes=FileHashes(
                                sha256="XYZ789",
                                blake3="BLAKE123"
                            )
                        )
                    ]
                ),
                CivitAIModelVersion(
                    id=2,
                    model_id=1,
                    name="v2.0",
                    files=[
                        CivitAIFile(
                            id=3,
                            name="model-v2.safetensors",
                            size_kb=1500,
                            hashes=FileHashes(
                                sha256="SEARCH123",
                                crc32="CRC123"
                            )
                        )
                    ]
                )
            ]
        )

        # Test get_latest_version
        latest = model.get_latest_version()
        assert latest is not None
        assert latest.id == 1  # First in list is latest

        # Test get_primary_file
        primary_file = model.get_primary_file()
        assert primary_file is not None
        assert primary_file.id == 2
        assert primary_file.primary

        # Test find_file_by_hash
        found_file = model.find_file_by_hash("SEARCH123")
        assert found_file is not None
        assert found_file.id == 3

        # Test hash case insensitivity
        found_file = model.find_file_by_hash("search123")
        assert found_file is not None
        assert found_file.id == 3

        # Test get_preferred_hash
        file = model.model_versions[0].files[0]
        preferred = file.get_preferred_hash()
        assert preferred == "ABC123"  # SHA256 is preferred

        file_no_sha = CivitAIFile(
            id=99,
            name="test.pt",
            size_kb=100,
            hashes=FileHashes(auto_v1="AUTO1", crc32="CRC1")
        )
        assert file_no_sha.get_preferred_hash() == "AUTO1"
