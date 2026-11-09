from types import SimpleNamespace
from app.security import orchestrator


def test_prompt_forbids_missing_tools_list():
    caps = SimpleNamespace(shell_enabled=True, shell_sudo=True, shell_auto_run=True)
    msg = orchestrator._shell_capability_message(caps)
    assert msg is not None
    text = msg.content
    assert "missing_tools.txt" in text
    assert "INSTALL IT" in text
