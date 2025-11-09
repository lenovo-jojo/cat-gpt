import sys
import types

# Provide a stub so importing ac_parser_encoder during tests does not require GUI deps.
screenshot_stub = types.ModuleType("screenshot_util")
def _noop_screenshot():
    return None
screenshot_stub.screenshot_dolphin_window = _noop_screenshot
sys.modules.setdefault("screenshot_util", screenshot_stub)

import ac_parser_encoder


def test_inject_feeling_chatty_option_rewrites_first_choice():
    sample = (
        "<Open Choice Menu>"
        " First option <Clear Text>"
        "<Choice 1 Jump [1234]>"
        "<Choice 2 Jump [5678]>"
    )

    result = ac_parser_encoder._inject_feeling_chatty_option(sample)
    assert result is not None
    assert ac_parser_encoder.FEELING_CHATTY_LABEL in result
    assert "<Choice 1 Jump [1234]>" in result
    # ensure whitespace trimmed to the original framing
    assert result.startswith("<Open Choice Menu>")


def test_injected_choice_round_trips_through_encoder():
    sample = (
        "<Open Choice Menu>"
        " Option A<Choice 1 Jump [1234]>"
        "<Choice 2 Jump [5678]>"
    )
    modified = ac_parser_encoder._inject_feeling_chatty_option(sample)
    assert modified is not None

    round_tripped = ac_parser_encoder.parse_ac_text(
        ac_parser_encoder.encode_ac_text(modified)
    )
    assert ac_parser_encoder.FEELING_CHATTY_LABEL in round_tripped
    assert "<Choice 1 Jump [1234]>" in round_tripped


def test_conversation_state_allows_menu_after_single_line():
    state = ac_parser_encoder.ConversationState()

    state.observe_text("Hello there!<Press A>")
    assert state.lines_seen == 1
    assert not state.ready_for_chatty

    state.observe_text(
        "<Open Choice Menu> Option<Choice 1 Jump [1111]>"
        "<Choice 2 Jump [2222]>"
    )

    assert state.ready_for_chatty
