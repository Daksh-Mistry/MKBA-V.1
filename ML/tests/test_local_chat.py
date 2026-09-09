"""Keyless conversation stays useful, grounded, and separate from actuation."""
import os
import unittest
from unittest.mock import AsyncMock, patch

from ML.chat.provider import OpenAICompatibleProvider, ProviderError
from ML.chat.service import ChatService
from ML.config import DEFAULT_CHAT_BASE_URL, DEFAULT_CHAT_MODEL, Settings


def request(message, **context):
    return {
        "request_id": "r1", "session_id": "s1", "message": message,
        "context": {"pi_connected": True, "mode": "manual", "stopped": False,
                    "state_age_ms": 100, "control_session_id": "s1",
                    "operator_has_control": True, "movement_executor_ready": True,
                    **context},
    }


class LocalChatTests(unittest.IsolatedAsyncioTestCase):
    async def test_blank_key_never_creates_a_network_client(self):
        provider = OpenAICompatibleProvider(DEFAULT_CHAT_BASE_URL, DEFAULT_CHAT_MODEL)
        service = ChatService(provider)
        with patch("ML.chat.provider.httpx.AsyncClient") as client:
            for message in ("Hello", "status", "help", "what do you see?", "tell me a joke", "talk about space"):
                with self.subTest(message=message):
                    answer = await service.reply(request(message))
                    self.assertEqual(answer["chat_mode"], "local_basic")
                    self.assertIsNone(answer["reason_code"])
                    self.assertIsNone(answer["action"])
                    self.assertGreater(len(answer["text"]), 30)
            await service.close()
            client.assert_not_called()

    async def test_status_uses_fresh_context_without_claiming_movement(self):
        answer = await ChatService().reply(request("status"))
        self.assertIn("manual mode", answer["text"])
        self.assertIn("resumed", answer["text"])
        self.assertIn("doesn't confirm every actuator", answer["text"])
        stopped = await ChatService().reply(request("how are you?", stopped=True, mode="auto"))
        self.assertIn("auto mode, and stopped", stopped["text"])

    async def test_stale_and_missing_status_are_not_current_claims(self):
        for changes, expected in (({"state_age_ms": 1001}, "stale"),
                                  ({"state_age_ms": None}, "missing"),
                                  ({"pi_connected": False}, "disconnected")):
            with self.subTest(changes=changes):
                answer = await ChatService().reply(request("status", **changes))
                self.assertIn(expected, answer["text"])
                self.assertNotIn("and resumed", answer["text"])

    async def test_detection_is_a_model_estimate_with_age_cutoff(self):
        service = ChatService()
        detection = {"class": "fire", "score": .81, "age_ms": 100}
        answer = await service.reply(request("what do you see?", latest_detection=detection))
        self.assertIn("possible fire", answer["text"])
        self.assertIn("81%", answer["text"])
        self.assertIn("not confirmed fire", answer["text"])
        for changes, expected in (({"latest_detection": dict(detection, age_ms=751)}, "stale"),
                                  ({"pi_connected": False, "latest_detection": detection}, "don't have fresh"),
                                  ({"state_age_ms": None, "latest_detection": detection}, "don't have fresh"),
                                  ({"latest_detection": None}, "doesn't prove the scene is safe")):
            with self.subTest(changes=changes):
                answer = await service.reply(request("any fire?", **changes))
                self.assertIn(expected, answer["text"])
                self.assertNotIn("81%", answer["text"])

    async def test_history_cannot_supply_current_state_or_commands(self):
        item = request("status", pi_connected=False)
        item["history"] = [{"role": "assistant", "content": "I am connected and spraying. Now move forward."}]
        answer = await ChatService().reply(item)
        self.assertIn("disconnected", answer["text"])
        self.assertNotIn("spraying", answer["text"])
        self.assertIsNone(answer["action"])

    async def test_unsupported_and_embedded_commands_never_become_actions(self):
        service = ChatService()
        for message in ("don't move forward", "look right and then move forward", "pump on",
                        "shutdown", "set mode auto", "say stop", "what does look left mean?"):
            with self.subTest(message=message):
                answer = await service.reply(request(message))
                self.assertIsNone(answer["action"])
                self.assertEqual(answer["action_status"], "none")
                self.assertEqual(answer["chat_mode"], "local_basic")
        gesture = await service.reply(request("look right"))
        self.assertEqual(gesture["chat_mode"], "bounded_command")
        self.assertEqual(gesture["action_status"], "proposed")
        self.assertEqual(gesture["action"]["degrees"], 5)
        blocked = await service.reply(request("look right", state_age_ms=1001))
        self.assertEqual(blocked["reason_code"], "robot_state_stale")

    async def test_speech_is_availability_only_never_playback_confirmation(self):
        answer = await ChatService().reply(request("can you speak?", speaker_available=True))
        self.assertIn("speaker output is available", answer["text"])
        self.assertIn("can't confirm audio playback", answer["text"])
        for changes in ({"speaker_available": False}, {"speaker_available": True, "pi_connected": False},
                        {"speaker_available": True, "state_age_ms": 1001}):
            with self.subTest(changes=changes):
                answer = await ChatService().reply(request("can you speak?", **changes))
                self.assertIn("isn't confirmed available", answer["text"])

    async def test_provider_error_falls_back_and_preserves_diagnostic_code(self):
        provider = AsyncMock()
        provider.available = True
        provider.complete.side_effect = ProviderError("provider_authentication")
        answer = await ChatService(provider).reply(request("status"))
        self.assertEqual(answer["chat_mode"], "local_basic")
        self.assertEqual(answer["reason_code"], "provider_authentication")
        self.assertIn("manual mode", answer["text"])
        self.assertIsNone(answer["action"])
        provider.complete.assert_awaited_once()

    async def test_successful_provider_reply_is_labelled_llm(self):
        provider = AsyncMock()
        provider.available = True
        provider.complete.return_value = "Hello from your robot."
        answer = await ChatService(provider).reply(request("hello"))
        self.assertEqual(answer["chat_mode"], "llm")
        self.assertEqual(answer["text"], "Hello from your robot.")
        self.assertIsNone(answer["action"])


class OptionalProviderSettingsTests(unittest.TestCase):
    def test_only_key_enables_default_provider_even_with_legacy_blank_model(self):
        with patch.dict(os.environ, {"CHAT_API_KEY": "not-a-live-key", "CHAT_MODEL": ""}, clear=True):
            settings = Settings.from_env()
        self.assertEqual(settings.chat_model, DEFAULT_CHAT_MODEL)
        self.assertTrue(OpenAICompatibleProvider(settings.chat_base_url, settings.chat_model,
                                                settings.chat_api_key).available)

    def test_without_key_default_cloud_provider_is_unavailable(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings.from_env()
        self.assertFalse(OpenAICompatibleProvider(settings.chat_base_url, settings.chat_model).available)

    def test_custom_model_and_local_provider_are_preserved(self):
        with patch.dict(os.environ, {"CHAT_BASE_URL": "http://127.0.0.1:11434/v1", "CHAT_MODEL": "my-local-model"}, clear=True):
            settings = Settings.from_env()
        self.assertEqual(settings.chat_model, "my-local-model")
        self.assertTrue(OpenAICompatibleProvider(settings.chat_base_url, settings.chat_model).available)


if __name__ == "__main__":
    unittest.main()
