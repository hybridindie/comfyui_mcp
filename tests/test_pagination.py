"""Unit tests for the paginate() helper."""

from comfyui_mcp.pagination import paginate


class TestPaginate:
    def test_basic_slicing(self):
        items = list(range(20))
        result = paginate(items, offset=0, limit=5)
        assert result["items"] == [0, 1, 2, 3, 4]
        assert result["total"] == 20
        assert result["offset"] == 0
        assert result["limit"] == 5
        assert result["has_more"] is True

    def test_offset_beyond_end(self):
        items = list(range(5))
        result = paginate(items, offset=100, limit=5)
        assert result["items"] == []
        assert result["total"] == 5
        assert result["has_more"] is False

    def test_limit_clamped_to_max(self):
        items = list(range(200))
        result = paginate(items, offset=0, limit=999, max_limit=50)
        assert result["limit"] == 50
        assert len(result["items"]) == 50

    def test_negative_offset_treated_as_zero(self):
        items = list(range(10))
        result = paginate(items, offset=-5, limit=3)
        assert result["offset"] == 0
        assert result["items"] == [0, 1, 2]

    def test_none_limit_uses_default(self):
        items = list(range(50))
        result = paginate(items, offset=0, limit=None, default_limit=10)
        assert result["limit"] == 10
        assert len(result["items"]) == 10

    def test_zero_limit_uses_default(self):
        items = list(range(50))
        result = paginate(items, offset=0, limit=0, default_limit=10)
        assert result["limit"] == 10
        assert len(result["items"]) == 10

    def test_has_more_true_when_more_items(self):
        items = list(range(10))
        result = paginate(items, offset=0, limit=5)
        assert result["has_more"] is True

    def test_has_more_false_at_exact_end(self):
        items = list(range(10))
        result = paginate(items, offset=5, limit=5)
        assert result["has_more"] is False

    def test_has_more_false_past_end(self):
        items = list(range(10))
        result = paginate(items, offset=8, limit=5)
        assert result["items"] == [8, 9]
        assert result["has_more"] is False

    def test_empty_items(self):
        result = paginate([], offset=0, limit=10)
        assert result["items"] == []
        assert result["total"] == 0
        assert result["has_more"] is False

    def test_envelope_keys(self):
        result = paginate([1, 2, 3])
        assert set(result.keys()) == {"items", "total", "offset", "limit", "has_more"}
