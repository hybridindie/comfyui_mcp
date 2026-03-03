"""Tests for path sanitization."""

import pytest

from comfyui_mcp.security.sanitizer import PathSanitizer, PathValidationError


class TestPathSanitizer:
    @pytest.fixture
    def sanitizer(self):
        return PathSanitizer(
            allowed_extensions=[".png", ".jpg", ".jpeg", ".webp", ".json"],
            max_size_mb=50,
        )

    def test_clean_filename_passes(self, sanitizer):
        result = sanitizer.validate_filename("image_001.png")
        assert result == "image_001.png"

    def test_subdirectory_filename_passes(self, sanitizer):
        result = sanitizer.validate_filename("subfolder/image.png")
        assert result == "subfolder/image.png"

    def test_path_traversal_blocked(self, sanitizer):
        with pytest.raises(PathValidationError, match="traversal"):
            sanitizer.validate_filename("../../etc/passwd")

    def test_path_traversal_encoded_blocked(self, sanitizer):
        with pytest.raises(PathValidationError, match="traversal"):
            sanitizer.validate_filename("..%2F..%2Fetc%2Fpasswd")

    def test_null_byte_blocked(self, sanitizer):
        with pytest.raises(PathValidationError, match="null"):
            sanitizer.validate_filename("image.png\x00.sh")

    def test_absolute_path_blocked(self, sanitizer):
        with pytest.raises(PathValidationError, match="absolute"):
            sanitizer.validate_filename("/etc/passwd")

    def test_disallowed_extension_blocked(self, sanitizer):
        with pytest.raises(PathValidationError, match="extension"):
            sanitizer.validate_filename("script.py")

    def test_no_extension_blocked(self, sanitizer):
        with pytest.raises(PathValidationError, match="extension"):
            sanitizer.validate_filename("Makefile")

    def test_double_extension_uses_last(self, sanitizer):
        result = sanitizer.validate_filename("photo.backup.png")
        assert result == "photo.backup.png"

    def test_validate_size_passes(self, sanitizer):
        sanitizer.validate_size(1024 * 1024)  # 1 MB

    def test_validate_size_too_large(self, sanitizer):
        with pytest.raises(PathValidationError, match="size"):
            sanitizer.validate_size(100 * 1024 * 1024)  # 100 MB

    def test_backslash_traversal_blocked(self, sanitizer):
        with pytest.raises(PathValidationError, match="traversal"):
            sanitizer.validate_filename("..\\..\\windows\\system32")
