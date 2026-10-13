"""NANOBOT_ACCOUNTS on the WebSocket channel: identity, ownership, quota. [badmintonGPT fork]"""

from __future__ import annotations

import asyncio
import functools
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import websockets

from nanobot import accounts
from nanobot.channels.websocket import WebSocketChannel
from nanobot.session.manager import Session, SessionManager

ALICE = {"Cf-Access-Authenticated-User-Email": "alice@uni.edu"}
BOB = {"Cf-Access-Authenticated-User-Email": "bob@uni.edu"}
BOSS = {"Cf-Access-Authenticated-User-Email": "boss@lab.org"}


@pytest.fixture(autouse=True)
def accounts_env(tmp_path, monkeypatch):
    monkeypatch.setenv("NANOBOT_ACCOUNTS", "1")
    monkeypatch.setenv("NANOBOT_ACCOUNTS_WHITELIST", "boss@lab.org")
    monkeypatch.delenv("NANOBOT_ACCOUNTS_QUOTA_USD", raising=False)
    monkeypatch.delenv("CF_ACCESS_TEAM_DOMAIN", raising=False)
    monkeypatch.delenv("CF_ACCESS_AUD", raising=False)
    monkeypatch.setattr("nanobot.webui.workspaces.get_webui_dir", lambda: tmp_path / "webui")
    monkeypatch.setattr("nanobot.webui.sidebar_state.get_webui_dir", lambda: tmp_path / "webui")
    led = accounts.Ledger(tmp_path / "accounts.db")
    accounts.set_ledger_for_tests(led)
    yield led
    accounts.set_ledger_for_tests(None)
    led.close()


@pytest.fixture()
def bus() -> MagicMock:
    b = MagicMock()
    b.publish_inbound = AsyncMock()
    return b


def _seed(workspace: Path, keys: list[str]) -> SessionManager:
    sm = SessionManager(workspace)
    for k in keys:
        s = Session(key=k)
        s.add_message("user", f"hi from {k}")
        sm.save(s)
    return sm


def _ch(bus: Any, sm: SessionManager, port: int) -> WebSocketChannel:
    return WebSocketChannel(
        {
            "enabled": True,
            "allowFrom": ["*"],
            "host": "127.0.0.1",
            "port": port,
            "path": "/",
            "websocketRequiresToken": False,
        },
        bus,
        session_manager=sm,
    )


async def _get(url: str, headers: dict[str, str] | None = None) -> httpx.Response:
    return await asyncio.to_thread(
        functools.partial(httpx.get, url, headers=headers or {}, timeout=5.0)
    )


async def _token(base: str, who: dict[str, str]) -> str:
    resp = await _get(f"{base}/webui/bootstrap", who)
    assert resp.status_code == 200, resp.text
    return resp.json()["token"]


async def _recv(client: Any, event: str) -> dict[str, Any]:
    for _ in range(20):
        msg = json.loads(await asyncio.wait_for(client.recv(), timeout=3))
        if msg.get("event") == event:
            return msg
    raise AssertionError(f"no {event} event")


@pytest.mark.asyncio
async def test_http_surface_is_scoped_to_the_account(bus, tmp_path, accounts_env) -> None:
    led = accounts_env
    sm = _seed(tmp_path, ["websocket:a1", "websocket:b1", "websocket:legacy"])
    led.claim("websocket:a1", "alice@uni.edu")
    led.claim("websocket:b1", "bob@uni.edu")
    channel = _ch(bus, sm, 29961)
    base = "http://127.0.0.1:29961"
    task = asyncio.create_task(channel.start())
    await asyncio.sleep(0.3)
    try:
        boot = (await _get(f"{base}/webui/bootstrap", ALICE)).json()
        assert boot["account"]["email"] == "alice@uni.edu"
        assert boot["account"]["quota_usd"] == 3.0
        assert boot["account"]["can_manage_settings"] is False
        auth = {**ALICE, "Authorization": f"Bearer {boot['token']}"}

        listed = (await _get(f"{base}/api/sessions", auth)).json()["sessions"]
        assert [s["key"] for s in listed] == ["websocket:a1"]
        assert (await _get(f"{base}/api/sessions/websocket:a1/messages", auth)).status_code == 200
        for key in ("websocket:b1", "websocket:legacy"):
            assert (await _get(f"{base}/api/sessions/{key}/messages", auth)).status_code == 404
            assert (await _get(f"{base}/api/sessions/{key}/webui-thread", auth)).status_code == 404
            assert (await _get(f"{base}/api/sessions/{key}/delete", auth)).status_code == 404
        assert sm.read_session_file("websocket:b1") is not None

        assert (await _get(f"{base}/api/settings", auth)).status_code == 403
        usage = (await _get(f"{base}/api/usage", auth)).json()
        assert usage["enabled"] and usage["remaining_usd"] == 3.0
        assert usage["breakdown"]["llm"]["calls"] == 0

        boss_auth = {**BOSS, "Authorization": f"Bearer {await _token(base, BOSS)}"}
        assert (await _get(f"{base}/api/settings", boss_auth)).status_code != 403
        assert (await _get(f"{base}/api/usage", boss_auth)).json()["unlimited"] is True

        # Loopback without a proxy identity = host/dev local user (whitelisted).
        local = (await _get(f"{base}/webui/bootstrap")).json()["account"]
        assert local["email"] == "local@localhost" and local["unlimited"] is True
    finally:
        await channel.stop()
        await task


@pytest.mark.asyncio
async def test_ws_chat_ownership_commands_and_quota(bus, tmp_path, accounts_env) -> None:
    led = accounts_env
    sm = _seed(tmp_path, ["websocket:b1"])
    led.claim("websocket:b1", "bob@uni.edu")
    channel = _ch(bus, sm, 29962)
    task = asyncio.create_task(channel.start())
    await asyncio.sleep(0.3)
    try:
        async with websockets.connect(
            "ws://127.0.0.1:29962/?client_id=t", additional_headers=ALICE
        ) as client:
            ready = await _recv(client, "ready")
            assert led.owner(f"websocket:{ready['chat_id']}") is None  # claimed on first use
            await client.send(
                json.dumps({"type": "attach", "chat_id": ready["chat_id"]})
            )
            await _recv(client, "attached")
            assert led.owner(f"websocket:{ready['chat_id']}") == "alice@uni.edu"

            await client.send(json.dumps({"type": "attach", "chat_id": "b1"}))
            err = await _recv(client, "error")
            assert err["detail"] == "chat_forbidden"

            await client.send(json.dumps({"type": "message", "chat_id": "b1", "content": "hi"}))
            assert (await _recv(client, "error"))["detail"] == "chat_forbidden"

            await client.send(json.dumps({"type": "new_chat"}))
            new_id = (await _recv(client, "attached"))["chat_id"]
            assert led.owner(f"websocket:{new_id}") == "alice@uni.edu"

            await client.send(
                json.dumps({"type": "message", "chat_id": new_id, "content": "/restart"})
            )
            assert (await _recv(client, "error"))["detail"] == "command_forbidden"

            await client.send(json.dumps({"type": "message", "chat_id": new_id, "content": "hi"}))
            await asyncio.sleep(0.2)
            inbound = bus.publish_inbound.await_args.args[0]
            assert inbound.metadata[accounts.ACCOUNT_METADATA_KEY] == "alice@uni.edu"

            led.record_llm(
                email="alice@uni.edu", session_key=None, model="m", usage={}, cost_usd=3.0
            )
            calls = bus.publish_inbound.await_count
            await client.send(json.dumps({"type": "message", "chat_id": new_id, "content": "hi"}))
            err = await _recv(client, "error")
            assert err["detail"] == "quota_exhausted" and err["quota_usd"] == 3.0
            assert bus.publish_inbound.await_count == calls
    finally:
        await channel.stop()
        await task


@pytest.mark.asyncio
async def test_legacy_sessions_adopted_by_configured_owner(
    bus, tmp_path, accounts_env, monkeypatch
) -> None:
    monkeypatch.setenv("NANOBOT_ACCOUNTS_LEGACY_OWNER", "Boss@lab.org")
    sm = _seed(tmp_path, ["websocket:old1", "websocket:old2"])
    accounts_env.claim("websocket:old2", "bob@uni.edu")
    channel = _ch(bus, sm, 29963)
    task = asyncio.create_task(channel.start())
    await asyncio.sleep(0.3)
    try:
        assert accounts_env.owner("websocket:old1") == "boss@lab.org"
        assert accounts_env.owner("websocket:old2") == "bob@uni.edu"
    finally:
        await channel.stop()
        await task


@pytest.mark.asyncio
async def test_remote_request_without_identity_is_rejected(bus, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.channels.websocket._is_localhost", lambda _c: False)
    monkeypatch.setenv("NANOBOT_WEBUI_TRUST_PROXY", "1")  # as in the Docker deploy
    channel = _ch(bus, _seed(tmp_path, []), 29964)
    base = "http://127.0.0.1:29964"
    task = asyncio.create_task(channel.start())
    await asyncio.sleep(0.3)
    try:
        assert (await _get(f"{base}/webui/bootstrap")).status_code == 401
        assert (await _get(f"{base}/api/sessions")).status_code == 401
        assert (await _get(f"{base}/webui/bootstrap", ALICE)).status_code == 200
        with pytest.raises(websockets.exceptions.InvalidStatus):
            async with websockets.connect("ws://127.0.0.1:29964/"):
                pass
    finally:
        await channel.stop()
        await task


@pytest.mark.asyncio
async def test_puzzle_answer_is_checked_per_account(bus, tmp_path, monkeypatch) -> None:
    from urllib.parse import quote

    from nanobot import puzzle

    monkeypatch.setenv("NANOBOT_PUZZLE_ANSWER", "謎底")
    store = puzzle.PuzzleStore(tmp_path / "puzzle.db")
    puzzle.set_store_for_tests(store)
    channel = _ch(bus, _seed(tmp_path, []), 29965)
    base = "http://127.0.0.1:29965"
    task = asyncio.create_task(channel.start())
    await asyncio.sleep(0.3)
    try:
        assert (await _get(f"{base}/api/puzzle")).status_code == 401
        alice = {**ALICE, "Authorization": f"Bearer {await _token(base, ALICE)}"}
        bob = {**BOB, "Authorization": f"Bearer {await _token(base, BOB)}"}

        status = (await _get(f"{base}/api/puzzle", alice)).json()
        assert status == {"configured": True, "solved": False, "wrong_count": 0, "retry_after_s": 0}
        assert "謎底" not in (await _get(f"{base}/api/puzzle", alice)).text

        wrong = await _get(f"{base}/api/puzzle/answer?answer={quote('殺球')}", alice)
        assert wrong.status_code == 200
        assert wrong.json()["correct"] is False and wrong.json()["retry_after_s"] == 30

        locked = await _get(f"{base}/api/puzzle/answer?answer={quote('謎底')}", alice)
        assert locked.status_code == 429 and locked.headers["Retry-After"] in {"29", "30"}

        right = await _get(f"{base}/api/puzzle/answer?answer={quote('謎底')}", bob)
        assert right.status_code == 200 and right.json()["correct"] is True
        assert (await _get(f"{base}/api/puzzle", bob)).json()["solved"] is True
        assert (await _get(f"{base}/api/puzzle", alice)).json()["solved"] is False

        assert (await _get(f"{base}/api/puzzle/answer?answer=", alice)).status_code == 400

        monkeypatch.delenv("NANOBOT_PUZZLE_ANSWER")
        assert (await _get(f"{base}/api/puzzle", alice)).json() == {"configured": False}
    finally:
        await channel.stop()
        await task
        puzzle.set_store_for_tests(None)
        store.close()
