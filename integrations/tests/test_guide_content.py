from integrations.docs import DOCS_ROOT


def test_guide_has_required_content():
    text = (DOCS_ROOT / "integrations/sis-webhook.md").read_text(encoding="utf-8")
    for anchor in [
        "## Verifying the signature",
        "## Idempotency & corrections",
        "X-Libli-Signature",
        "```python",
        "```javascript",
        "```php",
    ]:
        assert anchor in text, anchor
    # Both a canonical (real) example and the test sample exist.
    assert '"test": true' in text  # the test sample
    assert text.count('"event": "result_finalized"') >= 2  # canonical + test
    # UTF-8 key + lowercase-hex verification guidance is present.
    assert "UTF-8" in text
