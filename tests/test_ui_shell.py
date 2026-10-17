import pytest

from penny.contracts import Level
from penny.ui import APP_NAME
from penny.ui.quiz import QUESTIONS, level_for, score
from penny.ui.session import Player, get_player, reset_player
from penny.ui.text import dollars, md, weeks
from ui_helpers import click, has_button, launch

RIGHT = [q.options[q.answer] for q in QUESTIONS]

# ------------------------------------------------------------------ pure pieces


@pytest.mark.parametrize(
    ("answers", "correct", "level"),
    [
        ([1, 1, 0], 3, Level.BUILDER),
        ([1, 1, 2], 2, Level.SAVER),
        ([0, 1, 0], 2, Level.SAVER),
        ([1, 0, 1], 1, Level.STARTER),
        ([None, None, None], 0, Level.STARTER),
        ([0, 0, 1], 0, Level.STARTER),
    ],
)
def test_the_quiz_is_scored_in_code(answers, correct, level):
    assert score(answers) == correct
    assert level_for(answers) is level


def test_every_question_has_three_options_and_a_valid_answer():
    assert len(QUESTIONS) == 3
    for question in QUESTIONS:
        assert len(question.options) == 3 and 0 <= question.answer < 3


def test_text_helpers():
    assert [dollars(c) for c in (750, 5, 0, -120)] == ["$7.50", "$0.05", "$0.00", "-$1.20"]
    assert md("Save $7.50 of your $60.00") == "Save \\$7.50 of your \\$60.00"
    assert md("no money here") == "no money here"
    assert [weeks(n) for n in (0, 1, 2)] == ["0 weeks", "1 week", "2 weeks"]


def test_a_new_player_starts_empty_and_is_called_friend():
    player = Player()
    assert (player.started, player.coins, player.xp, player.streak) == (False, 0, 0, 0)
    assert player.display_name == "friend" and player.level is Level.STARTER
    assert Player(nickname="  Sam ").display_name == "Sam"


def test_progress_values_are_clamped_and_xp_wraps_per_level():
    assert Player(xp=250).xp_in_level == 50
    assert Player(saved_cents=3000).goal_progress == 0.5
    assert Player(saved_cents=99_999).goal_progress == 1.0
    assert Player(saved_cents=-5).goal_progress == 0.0


def test_the_player_becomes_the_kid_context_agents_receive():
    kid = Player(nickname="Sam", level=Level.SAVER).kid()
    assert (kid.nickname, kid.level) == ("Sam", Level.SAVER)
    assert Player().kid().nickname == "friend"


def test_get_player_creates_once_and_reset_replaces():
    state: dict = {}
    first = get_player(state)
    first.coins = 40
    assert get_player(state) is first
    assert reset_player(state).coins == 0 and get_player(state) is not first


# ------------------------------------------------------------------ the running app


def test_first_run_shows_the_setup_screen_and_no_tabs():
    app = launch()
    assert app.main.title[0].value == f"Welcome to {APP_NAME}"
    assert len(app.tabs) == 0
    assert app.sidebar.title[0].value == APP_NAME
    assert [r.label for r in app.radio] == [q.text.replace("$", "\\$") for q in QUESTIONS]
    assert all(r.value is None for r in app.radio)  # nothing is pre-selected
    assert not has_button(app, "Restart setup")


def answer(app, picks):
    for i, pick in enumerate(picks):
        if pick is not None:
            app.radio(key=f"quiz_{i}").set_value(pick)
    return app


def test_all_three_right_starts_the_app_as_a_builder_with_the_nickname():
    app = launch()
    app.text_input[0].input("  Sam ")
    click(answer(app, RIGHT), "Start learning")
    player = app.session_state["player"]
    assert (player.started, player.nickname, player.level) == (True, "Sam", Level.BUILDER)
    assert [t.label for t in app.tabs] == ["Chat", "Play", "Portfolio and Markets", "Goals"]
    assert "Hi, Sam." in app.sidebar.caption[0].value
    assert app.sidebar.metric[0].value == "Builder"
    assert len(app.main.title) == 0  # the welcome screen is gone


def test_two_right_is_a_saver_and_unanswered_is_a_starter():
    app = launch()
    click(answer(app, [RIGHT[0], RIGHT[1], "Tax"]), "Start learning")
    assert app.session_state["player"].level is Level.SAVER

    app = launch()
    click(app, "Start learning")
    player = app.session_state["player"]
    assert (player.level, player.display_name) == (Level.STARTER, "friend")


def test_skip_starts_as_a_starter_without_the_quiz():
    app = click(launch(), "Skip, start as a Starter")
    player = app.session_state["player"]
    assert (player.started, player.level, player.nickname) == (True, Level.STARTER, "")
    assert len(app.tabs) == 4


def test_the_sidebar_shows_level_coins_streak_xp_and_goal():
    player = Player(
        started=True, nickname="Sam", level=Level.SAVER, coins=120, xp=145, streak=1,
        saved_cents=1500,
    )  # fmt: skip
    app = launch(player=player)
    metrics = {m.label: m.value for m in app.sidebar.metric}
    assert metrics == {"Level": "Saver", "Coins": "120", "Drop streak": "1 week"}
    captions = [c.value for c in app.sidebar.caption]
    assert "Hi, Sam. Little drops fill the jar." in captions
    assert any("never a real name" in c for c in captions)


def test_restart_goes_back_to_setup_and_clears_progress():
    app = launch(player=Player(started=True, nickname="Sam", coins=50))
    click(app, "Restart setup")
    player = app.session_state["player"]
    assert (player.started, player.coins, player.nickname) == (False, 0, "")
    assert app.main.title[0].value == f"Welcome to {APP_NAME}"
