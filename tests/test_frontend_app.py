import pytest

flask = pytest.importorskip("flask")  # frontend deps live in frontend/requirements.txt

from frontend import app as frontend_app  # noqa: E402


@pytest.fixture
def client():
    return frontend_app.app.test_client()


def test_default_api_base_is_the_backend_port():
    # The backend must run on 8000: the Microsoft redirect URI is registered as localhost:8000/auth/callback.
    assert frontend_app.API_BASE == "http://localhost:8000"


@pytest.mark.parametrize("path", ["/", "/queue", "/activity", "/system",
                                  "/swift/swi04003-2026-09-08T06:43:03.23847.2373755Z"])
def test_pages_render_and_inject_api_base(client, path):
    response = client.get(path)
    assert response.status_code == 200
    assert b"window.SWIFT_API_BASE" in response.data


def test_detail_page_embeds_reference_as_json_not_html(client):
    response = client.get("/swift/" + "%3Cscript%3Ealert(1)%3C%2Fscript%3E")
    assert response.status_code == 200
    assert b"<script>alert(1)</script>" not in response.data
