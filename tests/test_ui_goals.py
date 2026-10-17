import pytest

from penny.engines.goal import plan_goal
from penny.ui import goals
from penny.ui.session import Player, reset_player
from ui_helpers import click, launch


def started(**kwargs) -> Player:
    return Player(started=True, nickname="Sam", **kwargs)


# ------------------------------------------------------------------ logic


def test_the_options_are_the_presets_plus_an_own_goal():
    assert goals.goal_options() == [
        "Game $60.00",
        "Bike $120.00",
        "Concert ticket $45.00",
        "My own goal",
    ]


def test_the_current_option_follows_the_players_goal():
    assert goals.current_option(Player()) == "Game $60.00"
    assert goals.current_option(Player(goal_name="Bike", goal_cents=12000)) == "Bike $120.00"
    assert goals.current_option(Player(goal_name="Bike", goal_cents=9900)) == "My own goal"
    assert goals.current_option(Player(goal_name="Skateboard", goal_cents=4500)) == "My own goal"


def test_choosing_a_preset_sets_the_goal():
    player = Player()
    goals.choose_preset(player, "Concert ticket $45.00")
    assert (player.goal_name, player.goal_cents) == ("Concert ticket", 4500)
    with pytest.raises(ValueError, match="not a preset"):
        goals.choose_preset(player, "Pony $9.00")


@pytest.mark.parametrize(
    ("name", "price", "goal"),
    [
        ("Skateboard", 45, ("Skateboard", 4500)),
        ("  Lego set ", 19.99, ("Lego set", 1999)),
        ("", 1, ("My goal", 100)),
        ("Laptop", 1000, ("Laptop", 100_000)),
    ],
)
def test_an_own_goal_is_stored_in_whole_cents(name, price, goal):
    player = Player()
    goals.choose_own(player, name, price)
    assert (player.goal_name, player.goal_cents) == goal


@pytest.mark.parametrize("price", [0, 0.99, 1000.01, -5])
def test_an_own_goal_must_cost_between_one_dollar_and_the_limit(price):
    with pytest.raises(ValueError, match=r"from \$1 to \$1000"):
        goals.choose_own(Player(), "Thing", price)


def test_the_plan_uses_saved_money_only_when_asked():
    player = Player(saved_cents=2000)
    assert goals.plan_for(player, 8, use_saved=True, yearly_rate_pct=0).per_week_cents == 500
    assert goals.plan_for(player, 8, use_saved=False, yearly_rate_pct=0).per_week_cents == 750
    assert goals.plan_for(player, 8, False, 3).interest_cents == 12


@pytest.mark.parametrize(
    ("plan", "name", "text"),
    [
        (
            plan_goal(6000, 8),
            "Game",
            "Put $7.50 in your jar every week for 8 weeks to reach $60.00 for your game.",
        ),
        (
            plan_goal(500, 1),
            "Snack",
            "Put $5.00 in your jar this week to reach $5.00 for your Snack.",
        ),
        (
            plan_goal(6000, 8, 2000),
            "Game",
            "Put $5.00 in your jar every week for 8 weeks to reach $60.00 for your game. That counts the $20.00 you already have.",
        ),
        (
            plan_goal(6000, 8, 0, 3),
            "Game",
            "Put $7.49 in your jar every week for 8 weeks to reach $60.00 for your game. The bank adds $0.12 in interest along the way.",
        ),
        (
            plan_goal(6000, 8, 7000),
            "Game",
            "You already have enough for your game. Little drops filled the jar.",
        ),
    ],
)
def test_the_summary_reads_like_a_sentence_from_penny(plan, name, text):
    assert goals.summary(plan, name) == text


@pytest.mark.parametrize(
    ("name", "words"),
    [
        ("Game", "your game"),
        ("Concert ticket", "your concert ticket"),
        ("My goal", "your goal"),
        ("Skateboard", "your Skateboard"),
        ("LEGO set", "your LEGO set"),
    ],
)
def test_goal_names_read_naturally_inside_a_sentence(name, words):
    assert goals.goal_words(name) == words


def test_chart_rows_are_dollars_by_week():
    assert goals.chart_rows(plan_goal(1500, 3)) == [
        {"Week": 1, "Balance": 5.0},
        {"Week": 2, "Balance": 10.0},
        {"Week": 3, "Balance": 15.0},
    ]


def test_family_prompts_cycle():
    assert [goals.next_prompt(i) for i in range(len(goals.FAMILY_PROMPTS))] == [1, 2, 3, 0]


# ------------------------------------------------------------------ the Goals tab, running


def metrics(app) -> dict:
    wanted = ("Save each week", "You put in", "Interest earned")
    return {m.label: m.value for m in app.main.metric if m.label in wanted}


def test_the_tab_opens_with_the_default_goal_and_its_plan():
    app = launch(player=started())
    assert app.segmented_control(key="goal_choice").value == "Game $60.00"
    assert app.slider(key="goal_weeks").value == 8
    assert metrics(app) == {
        "Save each week": "$7.50",
        "You put in": "$60.00",
        "Interest earned": "$0.00",
    }
    assert any(
        m.value == "Put \\$7.50 in your jar every week for 8 weeks to reach \\$60.00 for your game."
        for m in app.markdown
    )
    assert any(m.value == goals.FAMILY_PROMPTS[0] for m in app.markdown)
    assert len(app.get("vega_lite_chart")) == 1


def test_picking_another_goal_updates_the_plan_and_the_players_goal():
    app = launch(player=started())
    app.segmented_control(key="goal_choice").set_value("Bike $120.00").run()
    player = app.session_state["player"]
    assert (player.goal_name, player.goal_cents) == ("Bike", 12000)
    assert metrics(app)["Save each week"] == "$15.00"


def test_more_weeks_means_less_each_week():
    app = launch(player=started())
    app.slider(key="goal_weeks").set_value(12).run()
    assert metrics(app)["Save each week"] == "$5.00"


def test_an_own_goal_shows_its_fields_and_sets_the_goal():
    app = launch(player=started())
    assert not [t for t in app.text_input if t.key == "goal_own_name"]
    app.segmented_control(key="goal_choice").set_value("My own goal").run()
    assert app.session_state["player"].goal_name == "My goal"
    assert app.session_state["player"].goal_cents == 2000
    app.text_input(key="goal_own_name").input("Skateboard").run()
    app.number_input(key="goal_own_price").set_value(45.0).run()
    player = app.session_state["player"]
    assert (player.goal_name, player.goal_cents) == ("Skateboard", 4500)
    assert metrics(app)["Save each week"] == "$5.63"  # 4500 / 8, rounded up to a whole cent


def test_money_from_the_games_can_count_toward_the_goal():
    app = launch(player=started(saved_cents=2000))
    toggle = app.toggle(key="goal_use_saved")
    assert toggle.value is True and toggle.label == "Count the \\$20.00 I have saved in the games"
    assert metrics(app)["Save each week"] == "$5.00"
    toggle.set_value(False).run()
    assert metrics(app)["Save each week"] == "$7.50"


def test_the_saved_toggle_is_hidden_when_nothing_is_saved():
    app = launch(player=started())
    assert not [t for t in app.toggle if t.key == "goal_use_saved"]


def test_interest_needs_the_toggle_and_then_shows_its_rate():
    app = launch(player=started())
    assert not [s for s in app.slider if s.key == "goal_rate"]
    app.toggle(key="goal_interest").set_value(True).run()
    assert app.slider(key="goal_rate").value == 3.0
    assert metrics(app) == {
        "Save each week": "$7.49",
        "You put in": "$59.92",
        "Interest earned": "$0.12",
    }


def test_another_question_cycles_the_family_challenge():
    app = click(launch(player=started()), "Another question")
    assert any(m.value == goals.FAMILY_PROMPTS[1] for m in app.markdown)
    assert app.session_state["family_prompt"] == 1


def test_restart_setup_also_resets_the_goal_widgets():
    state = {
        "player": started(goal_name="Bike", goal_cents=12000),
        "goal_choice": "Bike $120.00",
        "goal_weeks": 20,
        "family_prompt": 2,
    }
    fresh = reset_player(state)
    assert set(state) == {"player"} and (fresh.goal_name, fresh.goal_cents) == ("Game", 6000)
