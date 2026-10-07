def test_defaults_parse_lists():
    from app.config.settings import settings

    assert settings.cancellation_action_mx_type_list == ["camt.056"]
    assert settings.poll_folder_list == ["inbox", "junkemail"]
    assert "Mail.Send" in settings.graph_scope_list
    assert settings.cst_mailbox == "shreyapalavalli@gmail.com"


def test_test_isolation_overrides():
    from app.config.settings import settings

    assert settings.poller_enabled is False
    assert settings.token_cache_path.endswith("cache.json")
    assert settings.database_path.endswith("test.db")
    assert settings.poll_interval_seconds == 30
    assert settings.frontend_origin == "http://localhost:5000"


def test_subject_body_helper(load_fixture):
    from tests.conftest import subject_body

    fx = load_fixture("mt199_sgu_in_narrative")
    assert subject_body(fx) == {"subject": fx["subject"], "body": fx["body"]}
