import pytest

from nevo.ai_gateway.config import AiGatewaySettings
from nevo.ai_gateway.safety import safety_from_settings
from nevo.visuals.config import VisualGenerationSettings


@pytest.mark.parametrize("settings_type", [AiGatewaySettings, VisualGenerationSettings])
def test_policy_switch_reaches_every_lesson_checker(monkeypatch, settings_type):
    monkeypatch.setenv("SAFETY_POLICY_V2_ENABLED", "true")
    assert safety_from_settings(settings_type())._policy_v2 is True

    monkeypatch.setenv("SAFETY_POLICY_V2_ENABLED", "false")
    assert safety_from_settings(settings_type())._policy_v2 is False
