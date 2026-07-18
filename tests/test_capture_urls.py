from django.test import override_settings


@override_settings(ROOT_URLCONF="tests.capture_urls", MEDIA_URL="/media/")
def test_capture_urls_serves_media(client, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    (tmp_path / "smoke.txt").write_bytes(b"ok")
    resp = client.get("/media/smoke.txt")
    assert resp.status_code == 200
    assert b"ok" in b"".join(resp.streaming_content)
