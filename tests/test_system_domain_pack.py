"""Tests for system domain pack structure and shim imports (Phase 1)."""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SYSTEM_PACK = REPO_ROOT / "model-packs" / "system"


# ===================================================================
# Test: System domain-lib file layout
# ===================================================================


class TestSystemDomainLibExists:
    def test_system_health_in_domain_lib(self):
        assert (SYSTEM_PACK / "domain-lib" / "system_health.py").is_file()

    def test_sensors_directory(self):
        assert (SYSTEM_PACK / "domain-lib" / "sensors").is_dir()

    def test_sensors_files(self):
        sensors_dir = SYSTEM_PACK / "domain-lib" / "sensors"
        expected = [
            "hw_disk.py", "hw_gpu.py", "hw_http_queue.py",
            "hw_loop_latency.py", "hw_memory.py", "hw_temp.py",
        ]
        for name in expected:
            assert (sensors_dir / name).is_file(), f"Missing: {name}"

    def test_environmental_sensors_not_in_system(self):
        """Sanity: environmental_sensors belongs to agriculture, not system."""
        assert not (SYSTEM_PACK / "domain-lib" / "environmental_sensors.py").exists()


# ===================================================================
# Test: Shim imports still work
# ===================================================================


class TestSystemShimImports:
    def test_shim_system_health(self):
        from lumina.lib.system_health import SystemHealthMonitor
        assert callable(SystemHealthMonitor)

    def test_shim_hw_gpu(self):
        from lumina.systools.hw_gpu import get_gpu_usage
        assert callable(get_gpu_usage)

    def test_shim_hw_http_queue(self):
        from lumina.systools.hw_http_queue import increment
        assert callable(increment)


# ===================================================================
# Test: System pack integrity
# ===================================================================


class TestSystemPackIntegrity:
    def test_cfg_dir_exists(self):
        assert (SYSTEM_PACK / "cfg").is_dir()

    def test_controllers_exist(self):
        ctrl = SYSTEM_PACK / "controllers"
        assert (ctrl / "runtime_adapters.py").is_file()
        assert (ctrl / "tool_adapters.py").is_file()

    def test_pack_yaml_exists(self):
        assert (SYSTEM_PACK / "pack.yaml").is_file()
