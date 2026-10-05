import json

import pytest

from nanobot.security.workspace_access import WorkspaceScopeError, default_workspace_scope
from nanobot.session.manager import SessionManager
from nanobot.webui.workspaces import (
    WebUIWorkspaceController,
    read_webui_default_access_mode,
    read_webui_workspace_state,
    webui_workspace_state_path,
    workspaces_payload,
    write_webui_default_access_mode,
)


def test_workspace_state_defaults_when_file_missing(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.webui.workspaces.get_webui_dir", lambda: tmp_path / "webui")

    state = read_webui_workspace_state()

    assert state["default_access_mode"] == "default"
    assert webui_workspace_state_path() == tmp_path / "webui" / "workspace-state.json"


def test_workspace_state_ignores_legacy_project_history(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.webui.workspaces.get_webui_dir", lambda: tmp_path / "webui")
    project = tmp_path / "project"
    project.mkdir()
    path = webui_workspace_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "recent_projects": [
                    {"project_path": str(project)},
                    {"project_path": str(tmp_path / "missing")},
                ],
                "last_scope": {
                    "project_path": str(project),
                    "access_mode": "full",
                },
            }
        ),
        encoding="utf-8",
    )

    state = read_webui_workspace_state()

    assert "recent_projects" not in state
    assert "last_scope" not in state
    assert state["default_access_mode"] == "default"


def test_workspace_payload_is_config_data_dir_scoped(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.webui.workspaces.get_webui_dir", lambda: tmp_path / "webui")
    default = tmp_path / "default"
    default.mkdir()

    payload = workspaces_payload(
        default_workspace=default,
        default_restrict_to_workspace=False,
        controls_available=True,
    )

    assert payload["default_scope"]["project_path"] == str(default.resolve())
    assert payload["default_scope"]["access_mode"] == "full"
    assert payload["default_access_mode"] == "default"
    assert payload["controls"]["can_change_project"] is True


def test_workspace_payload_hides_mutable_state_when_controls_unavailable(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("nanobot.webui.workspaces.get_webui_dir", lambda: tmp_path / "webui")
    default = tmp_path / "default"
    default.mkdir()

    payload = workspaces_payload(
        default_workspace=default,
        default_restrict_to_workspace=False,
        controls_available=False,
    )

    assert payload["default_scope"]["project_path"] == str(default.resolve())
    assert payload["controls"]["can_change_project"] is False
    assert payload["controls"]["can_use_full_access"] is False


def test_remote_managed_projects_are_restricted_to_persistent_project_root(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setenv("NANOBOT_WEBUI_REMOTE_PROJECTS", "1")
    default = tmp_path / "workspace"
    (default / "projects").mkdir(parents=True)
    controller = WebUIWorkspaceController(
        session_manager=None,
        default_workspace=default,
        default_restrict_to_workspace=True,
    )

    payload = controller.payload(controls_available=False)
    assert payload["controls"] == {
        "can_change_project": True,
        "can_use_full_access": False,
        "managed_project_root": str((default / "projects").resolve()),
    }

    project = default / "projects" / "賽事分析"
    scope = controller.scope_for_new_chat(
        {"workspace_scope": {"project_path": str(project), "access_mode": "restricted"}},
        controls_available=False,
    )
    assert project.is_dir()
    assert scope.project_path == project.resolve()
    assert scope.restrict_to_workspace is True

    with pytest.raises(WorkspaceScopeError):
        controller.scope_for_new_chat(
            {"workspace_scope": {"project_path": str(project), "access_mode": "full"}},
            controls_available=False,
        )
    with pytest.raises(WorkspaceScopeError):
        controller.scope_for_new_chat(
            {"workspace_scope": {"project_path": str(tmp_path / "outside"), "access_mode": "restricted"}},
            controls_available=False,
        )
    assert not (tmp_path / "outside").exists()
    (default / "projects" / "link").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(WorkspaceScopeError):
        controller.scope_for_new_chat(
            {"workspace_scope": {
                "project_path": str(default / "projects" / "link" / "escaped"),
                "access_mode": "restricted",
            }},
            controls_available=False,
        )
    assert not (tmp_path / "escaped").exists()


def test_workspace_payload_uses_webui_default_access_mode(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.webui.workspaces.get_webui_dir", lambda: tmp_path / "webui")
    default = tmp_path / "default"
    default.mkdir()

    assert write_webui_default_access_mode("full") is True
    assert write_webui_default_access_mode("full") is False

    payload = workspaces_payload(
        default_workspace=default,
        default_restrict_to_workspace=True,
        controls_available=True,
    )

    assert payload["default_access_mode"] == "full"
    assert payload["default_scope"]["project_path"] == str(default.resolve())
    assert payload["default_scope"]["access_mode"] == "full"


def test_legacy_restricted_webui_default_access_mode_maps_to_default(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.webui.workspaces.get_webui_dir", lambda: tmp_path / "webui")

    assert write_webui_default_access_mode("restricted") is False
    assert read_webui_default_access_mode() == "default"


def test_webui_default_access_applies_to_unscoped_old_sessions(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.webui.workspaces.get_webui_dir", lambda: tmp_path / "webui")
    default = tmp_path / "default"
    default.mkdir()
    sessions = SessionManager(tmp_path / "sessions")
    sessions.save(sessions.get_or_create("websocket:old-chat"))
    write_webui_default_access_mode("full")
    controller = WebUIWorkspaceController(
        session_manager=sessions,
        default_workspace=default,
        default_restrict_to_workspace=True,
    )

    scope = controller.scope_for_session_key("websocket:old-chat")
    new_scope = controller.scope_for_new_chat({}, controls_available=True)

    assert scope.project_path == default.resolve()
    assert scope.access_mode == "full"
    assert new_scope.access_mode == "full"


def test_webui_default_access_does_not_override_explicit_session_scope(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.webui.workspaces.get_webui_dir", lambda: tmp_path / "webui")
    default = tmp_path / "default"
    project = tmp_path / "project"
    default.mkdir()
    project.mkdir()
    sessions = SessionManager(tmp_path / "sessions")
    controller = WebUIWorkspaceController(
        session_manager=sessions,
        default_workspace=default,
        default_restrict_to_workspace=True,
    )
    explicit = default_workspace_scope(project, restrict_to_workspace=False)
    controller.persist_scope("explicit-chat", explicit)

    scope = controller.scope_for_session_key("websocket:explicit-chat")

    assert scope.project_path == project.resolve()
    assert scope.access_mode == "full"
