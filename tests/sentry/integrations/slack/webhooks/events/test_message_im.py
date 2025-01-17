from unittest.mock import patch

import orjson
import pytest
import responses
from slack_sdk.web import SlackResponse

from sentry.models.identity import Identity, IdentityStatus
from sentry.silo.base import SiloMode
from sentry.testutils.cases import IntegratedApiTestCase
from sentry.testutils.helpers import get_response_text, override_options
from sentry.testutils.silo import assume_test_silo_mode

from . import BaseEventTest

MESSAGE_IM_EVENT = """{
    "type": "message",
    "channel": "DOxxxxxx",
    "user": "Uxxxxxxx",
    "text": "helloo",
    "message_ts": "123456789.9875"
}"""

MESSAGE_IM_EVENT_NO_TEXT = """{
    "type": "message",
    "channel": "DOxxxxxx",
    "user": "Uxxxxxxx",
    "message_ts": "123456789.9875"
}"""

MESSAGE_IM_EVENT_UNLINK = """{
    "type": "message",
    "text": "unlink",
    "user": "UXXXXXXX1",
    "team": "TXXXXXXX1",
    "channel": "DTPJWTJ2D"
}"""

MESSAGE_IM_EVENT_LINK = """{
    "type": "message",
    "text": "link",
    "user": "UXXXXXXX1",
    "team": "TXXXXXXX1",
    "channel": "DTPJWTJ2D"
}"""

MESSAGE_IM_BOT_EVENT = """{
    "type": "message",
    "channel": "DOxxxxxx",
    "user": "Uxxxxxxx",
    "text": "helloo",
    "bot_id": "bot_id",
    "message_ts": "123456789.9875"
}"""


class MessageIMEventTest(BaseEventTest, IntegratedApiTestCase):
    def get_block_section_text(self, data):
        blocks = data["blocks"]
        return blocks[0]["text"]["text"], blocks[1]["text"]["text"]

    @pytest.fixture(autouse=True)
    def mock_chat_postMessage(self):
        with patch(
            "slack_sdk.web.client.WebClient.chat_postMessage",
            return_value=SlackResponse(
                client=None,
                http_verb="POST",
                api_url="https://slack.com/api/chat.postMessage",
                req_args={},
                data={"ok": True},
                headers={},
                status_code=200,
            ),
        ) as self.mock_post:
            yield

    @responses.activate
    def test_identifying_channel_correctly(self):
        responses.add(responses.POST, "https://slack.com/api/chat.postMessage", json={"ok": True})
        event_data = orjson.loads(MESSAGE_IM_EVENT)
        self.post_webhook(event_data=event_data)
        request = responses.calls[0].request
        data = orjson.loads(request.body)
        assert data.get("channel") == event_data["channel"]

    @override_options({"slack.event-endpoint-sdk": True})
    def test_identifying_channel_correctly_sdk(self):
        event_data = orjson.loads(MESSAGE_IM_EVENT)
        self.post_webhook(event_data=event_data)
        data = self.mock_post.call_args[1]
        assert data.get("channel") == event_data["channel"]

    def test_identifying_channel_correctly_sdk_la(self):
        with override_options({"slack.event-endpoint-sdk-integration-ids": [self.integration.id]}):
            event_data = orjson.loads(MESSAGE_IM_EVENT)
            self.post_webhook(event_data=event_data)
            data = self.mock_post.call_args[1]
            assert data.get("channel") == event_data["channel"]

    @responses.activate
    def test_user_message_im_notification_platform(self):
        responses.add(responses.POST, "https://slack.com/api/chat.postMessage", json={"ok": True})
        resp = self.post_webhook(event_data=orjson.loads(MESSAGE_IM_EVENT))
        assert resp.status_code == 200, resp.content

        assert len(responses.calls) == 1
        request = responses.calls[0].request
        assert request.headers["Authorization"] == "Bearer xoxb-xxxxxxxxx-xxxxxxxxxx-xxxxxxxxxxxx"
        data = orjson.loads(request.body)
        heading, contents = self.get_block_section_text(data)
        assert heading == "Unknown command: `helloo`"
        assert (
            contents
            == "Here are the commands you can use. Commands not working? Re-install the app!"
        )

    @override_options({"slack.event-endpoint-sdk": True})
    def test_user_message_im_notification_platform_sdk(self):
        resp = self.post_webhook(event_data=orjson.loads(MESSAGE_IM_EVENT))
        assert resp.status_code == 200, resp.content

        data = self.mock_post.call_args[1]
        heading, contents = self.get_block_section_text(data)
        assert heading == "Unknown command: `helloo`"
        assert (
            contents
            == "Here are the commands you can use. Commands not working? Re-install the app!"
        )

    @responses.activate
    def test_user_message_link(self):
        """
        Test that when a user types in "link" to the DM we reply with the correct response.
        """
        with assume_test_silo_mode(SiloMode.CONTROL):
            self.create_identity_provider(type="slack", external_id="TXXXXXXX1")

        responses.add(responses.POST, "https://slack.com/api/chat.postMessage", json={"ok": True})
        resp = self.post_webhook(event_data=orjson.loads(MESSAGE_IM_EVENT_LINK))
        assert resp.status_code == 200, resp.content

        assert len(responses.calls) == 1
        request = responses.calls[0].request
        assert request.headers["Authorization"] == "Bearer xoxb-xxxxxxxxx-xxxxxxxxxx-xxxxxxxxxxxx"
        data = orjson.loads(request.body)
        assert "Link your Slack identity" in get_response_text(data)

    @override_options({"slack.event-endpoint-sdk": True})
    def test_user_message_link_sdk(self):
        """
        Test that when a user types in "link" to the DM we reply with the correct response.
        """
        with assume_test_silo_mode(SiloMode.CONTROL):
            self.create_identity_provider(type="slack", external_id="TXXXXXXX1")

        resp = self.post_webhook(event_data=orjson.loads(MESSAGE_IM_EVENT_LINK))
        assert resp.status_code == 200, resp.content

        data = self.mock_post.call_args[1]
        assert "Link your Slack identity" in get_response_text(data)

    @responses.activate
    def test_user_message_already_linked(self):
        """
        Test that when a user who has already linked their identity types in
        "link" to the DM we reply with the correct response.
        """
        with assume_test_silo_mode(SiloMode.CONTROL):
            idp = self.create_identity_provider(type="slack", external_id="TXXXXXXX1")
            Identity.objects.create(
                external_id="UXXXXXXX1",
                idp=idp,
                user=self.user,
                status=IdentityStatus.VALID,
                scopes=[],
            )

        responses.add(responses.POST, "https://slack.com/api/chat.postMessage", json={"ok": True})
        resp = self.post_webhook(event_data=orjson.loads(MESSAGE_IM_EVENT_LINK))
        assert resp.status_code == 200, resp.content

        assert len(responses.calls) == 1
        request = responses.calls[0].request
        assert request.headers["Authorization"] == "Bearer xoxb-xxxxxxxxx-xxxxxxxxxx-xxxxxxxxxxxx"
        data = orjson.loads(request.body)
        assert "You are already linked" in get_response_text(data)

    @override_options({"slack.event-endpoint-sdk": True})
    def test_user_message_already_linked_sdk(self):
        """
        Test that when a user who has already linked their identity types in
        "link" to the DM we reply with the correct response.
        """
        with assume_test_silo_mode(SiloMode.CONTROL):
            idp = self.create_identity_provider(type="slack", external_id="TXXXXXXX1")
            Identity.objects.create(
                external_id="UXXXXXXX1",
                idp=idp,
                user=self.user,
                status=IdentityStatus.VALID,
                scopes=[],
            )

        resp = self.post_webhook(event_data=orjson.loads(MESSAGE_IM_EVENT_LINK))
        assert resp.status_code == 200, resp.content

        data = self.mock_post.call_args[1]
        assert "You are already linked" in get_response_text(data)

    @responses.activate
    def test_user_message_unlink(self):
        """
        Test that when a user types in "unlink" to the DM we reply with the correct response.
        """
        with assume_test_silo_mode(SiloMode.CONTROL):
            idp = self.create_identity_provider(type="slack", external_id="TXXXXXXX1")
            Identity.objects.create(
                external_id="UXXXXXXX1",
                idp=idp,
                user=self.user,
                status=IdentityStatus.VALID,
                scopes=[],
            )

        responses.add(responses.POST, "https://slack.com/api/chat.postMessage", json={"ok": True})
        resp = self.post_webhook(event_data=orjson.loads(MESSAGE_IM_EVENT_UNLINK))
        assert resp.status_code == 200, resp.content

        assert len(responses.calls) == 1
        request = responses.calls[0].request
        assert request.headers["Authorization"] == "Bearer xoxb-xxxxxxxxx-xxxxxxxxxx-xxxxxxxxxxxx"
        data = orjson.loads(request.body)
        assert "Click here to unlink your identity" in get_response_text(data)

    @override_options({"slack.event-endpoint-sdk": True})
    def test_user_message_unlink_sdk(self):
        """
        Test that when a user types in "unlink" to the DM we reply with the correct response.
        """
        with assume_test_silo_mode(SiloMode.CONTROL):
            idp = self.create_identity_provider(type="slack", external_id="TXXXXXXX1")
            Identity.objects.create(
                external_id="UXXXXXXX1",
                idp=idp,
                user=self.user,
                status=IdentityStatus.VALID,
                scopes=[],
            )

        resp = self.post_webhook(event_data=orjson.loads(MESSAGE_IM_EVENT_UNLINK))
        assert resp.status_code == 200, resp.content

        data = self.mock_post.call_args[1]
        assert "Click here to unlink your identity" in get_response_text(data)

    @responses.activate
    def test_user_message_already_unlinked(self):
        """
        Test that when a user without an Identity types in "unlink" to the DM we
        reply with the correct response.
        """
        with assume_test_silo_mode(SiloMode.CONTROL):
            self.create_identity_provider(type="slack", external_id="TXXXXXXX1")

        responses.add(responses.POST, "https://slack.com/api/chat.postMessage", json={"ok": True})
        resp = self.post_webhook(event_data=orjson.loads(MESSAGE_IM_EVENT_UNLINK))
        assert resp.status_code == 200, resp.content

        assert len(responses.calls) == 1
        request = responses.calls[0].request
        assert request.headers["Authorization"] == "Bearer xoxb-xxxxxxxxx-xxxxxxxxxx-xxxxxxxxxxxx"
        data = orjson.loads(request.body)
        assert "You do not have a linked identity to unlink" in get_response_text(data)

    @override_options({"slack.event-endpoint-sdk": True})
    def test_user_message_already_unlinked_sdk(self):
        """
        Test that when a user without an Identity types in "unlink" to the DM we
        reply with the correct response.
        """
        with assume_test_silo_mode(SiloMode.CONTROL):
            self.create_identity_provider(type="slack", external_id="TXXXXXXX1")

        resp = self.post_webhook(event_data=orjson.loads(MESSAGE_IM_EVENT_UNLINK))
        assert resp.status_code == 200, resp.content

        data = self.mock_post.call_args[1]
        assert "You do not have a linked identity to unlink" in get_response_text(data)

    def test_bot_message_im(self):
        resp = self.post_webhook(event_data=orjson.loads(MESSAGE_IM_BOT_EVENT))
        assert resp.status_code == 200, resp.content

    @responses.activate
    def test_user_message_im_no_text(self):
        responses.add(responses.POST, "https://slack.com/api/chat.postMessage", json={"ok": True})
        resp = self.post_webhook(event_data=orjson.loads(MESSAGE_IM_EVENT_NO_TEXT))
        assert resp.status_code == 200, resp.content
        assert len(responses.calls) == 0

    @override_options({"slack.event-endpoint-sdk": True})
    def test_user_message_im_no_text_sdk(self):
        resp = self.post_webhook(event_data=orjson.loads(MESSAGE_IM_EVENT_NO_TEXT))
        assert resp.status_code == 200, resp.content
        assert not self.mock_post.called
