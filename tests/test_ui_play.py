import pytest

from penny.contracts import Level
from penny.ui import games
from penny.ui.session import Player, reset_player
from ui_helpers import click, has_button, launch


def started(level=Level.STARTER, **kwargs) -> Player:
    return Player(started=True, nickname="Sam", level=level, **kwargs)


def with_piggy(seed=1, **kwargs) -> Player:
    player = started(**kwargs)
    games.start_piggy(player, seed=seed)
    return player


def with_lemonade(seed=1, **kwargs) -> Player:
    player = started(**kwargs)
    games.start_lemonade(player, seed=seed)
    return player


# ------------------------------------------------------------------ piggy bank logic


def test_a_week_of_saving_updates_the_jar_and_every_reward():
    player = with_piggy()
    facts = games.play_piggy_week(player, 1000, buy=False)
    assert player.piggy.data["saved_cents"] == 1000 and player.piggy.day == 2
    assert (player.coins, player.xp, player.streak, player.saved_cents) == (120, 20, 1, 1000)
    assert player.piggy_last is facts


def test_the_streak_grows_with_each_deposit_and_resets_on_a_week_with_none():
    player = with_piggy()
    for _ in range(2):
        games.play_piggy_week(player, 500, buy=False)
        games.next_piggy_week(player)
    assert player.streak == 2
    games.play_piggy_week(player, 0, buy=False)
    assert player.streak == 0


def test_affordability_follows_the_engines_temptation_price():
    player = with_piggy()
    price = player.piggy.data["event"]["price_cents"]
    assert games.can_afford_temptation(player, 1000 - price) is True
    assert games.can_afford_temptation(player, 1000 - price + 100) is False


def test_after_the_last_week_next_starts_a_new_game_but_keeps_the_rewards():
    player = with_piggy()
    for week in range(4):
        facts = games.play_piggy_week(player, 1000, buy=False)
        assert facts.finished is (week == 3)
        if week < 3:
            games.next_piggy_week(player)
    coins = player.coins
    assert player.piggy.finished and coins == 3 * 120 + 220
    games.next_piggy_week(player)
    assert (player.piggy.day, player.piggy.data["saved_cents"], player.piggy_last) == (1, 0, None)
    assert (player.coins, player.saved_cents, player.streak) == (coins, 4000, 4)


def piggy_text(save, buy=False, weeks=1):
    player = with_piggy()
    facts = None
    for _ in range(weeks):
        price = player.piggy.data["event"]["price_cents"]
        amount = min(save, 1000 - price) if buy else save
        facts = games.play_piggy_week(player, amount, buy=buy)
        if not facts.finished:
            games.next_piggy_week(player)
    return games.piggy_feedback(facts)


def test_piggy_feedback_covers_each_kind_of_week():
    assert piggy_text(0) == (
        "No drops in the jar this week. That is okay. What could you save next week?"
    )
    skipped = piggy_text(700)
    assert skipped.startswith("You saved $7.00 and skipped ") and skipped.endswith("in your jar.")
    bought = piggy_text(1000, buy=True)
    assert " and bought " in bought and "choose them on purpose" in bought
    assert bought.split("bought ")[1][0].islower()  # the temptation reads as part of a sentence


def test_piggy_feedback_closes_the_game_with_the_goal_result():
    assert piggy_text(1000, weeks=4).endswith(
        "You reached your $30.00 goal. Little drops filled the jar."
    )
    assert piggy_text(200, weeks=4).endswith(
        "You finished with $8.00 of $30.00. What would you change next time?"
    )


# ------------------------------------------------------------------ lemonade logic


def test_a_lemonade_day_updates_profit_history_and_rewards():
    player = with_lemonade()
    facts = games.play_lemonade_day(player, 75, 20)  # day one is always sunny: $11.00 profit
    assert facts.profit_cents == 1100 and player.lemonade_profits == [1100]
    assert (player.coins, player.xp, player.saved_cents) == (110, 25, 1100)
    assert player.lemonade.day == 2 and player.streak == 0  # the streak belongs to the jar


def test_a_losing_day_is_recorded_but_never_takes_from_the_jar():
    player = with_lemonade(saved_cents=500)
    facts = games.play_lemonade_day(player, 150, 60)
    assert facts.profit_cents < 0 and player.lemonade_profits == [facts.profit_cents]
    assert player.saved_cents == 500 and player.coins == 5


def test_after_day_three_next_starts_a_new_run_with_an_empty_chart():
    player = with_lemonade()
    for day in range(3):
        facts = games.play_lemonade_day(player, 75, 15)
        assert facts.finished is (day == 2)
        if day < 2:
            games.next_lemonade_day(player)
    assert len(player.lemonade_profits) == 3
    games.next_lemonade_day(player)
    assert (player.lemonade.day, player.lemonade_profits, player.lemonade_last) == (1, [], None)


@pytest.mark.parametrize(
    ("price", "cups", "start", "end"),
    [
        (
            75,
            10,
            "You sold out, and about 10 more people wanted a cup.",
            "You kept $5.50 as profit.",
        ),
        (75, 40, "20 cups went unsold, and each one cost you $0.20.", "You kept $7.00 as profit."),
        (75, 20, "You made exactly as many cups as people wanted.", "You kept $11.00 as profit."),
        (150, 60, "58 cups went unsold", "You lost money today, and that is useful to learn from."),
    ],
)
def test_lemonade_feedback_explains_what_happened(price, cups, start, end):
    player = with_lemonade()
    text = games.lemonade_feedback(games.play_lemonade_day(player, price, cups), 20)
    assert text.startswith(start) and text.endswith(end)


def test_the_last_day_adds_the_total():
    player = with_lemonade()
    facts = None
    for _ in range(3):
        facts = games.play_lemonade_day(player, 75, 15)
        if not facts.finished:
            games.next_lemonade_day(player)
    total = sum(player.lemonade_profits)
    assert games.lemonade_feedback(facts, 20).endswith(
        f"That was the last day. Your total profit was ${total / 100:.2f}."
    )


def test_harder_levels_play_harder_games():
    builder = with_piggy(level=Level.BUILDER)
    assert (builder.piggy.total_days, builder.piggy.data["goal_cents"]) == (6, 7000)
    assert with_lemonade(level=Level.BUILDER).lemonade.data["cost_per_cup_cents"] == 30


def test_seeds_are_random_unless_given():
    assert len({games.new_seed() for _ in range(20)}) > 1
    assert with_piggy(seed=5).piggy == with_piggy(seed=5).piggy


# ------------------------------------------------------------------ the Play tab, running


def sidebar(app) -> dict:
    return {m.label: m.value for m in app.sidebar.metric}


def assistant_text(app) -> str:
    return app.chat_message[-1].markdown[0].value


def test_the_play_tab_opens_on_the_piggy_bank_with_this_weeks_choices():
    player = with_piggy()
    app = launch(player=player)
    assert app.radio(key="game").value == "Piggy Bank"
    assert "Week 1 of 4" in [s.value for s in app.subheader]
    assert app.slider(key="piggy_save").value == 5
    assert app.radio(key="piggy_buy").options == ["Skip it", "Buy it"]
    temptation = player.piggy.data["event"]["name"]
    assert any(temptation in m.value for m in app.markdown)


def test_finishing_a_week_shows_feedback_and_updates_the_sidebar():
    app = launch(player=with_piggy())
    app.slider(key="piggy_save").set_value(10).run()
    click(app, "Finish the week")
    assert assistant_text(app).startswith("You saved \\$10.00 and skipped ")
    assert sidebar(app) == {"Level": "Starter", "Coins": "120", "Drop streak": "1 week"}
    assert any("+120 coins, +20 XP. Drop streak: 1 week." == c.value for c in app.caption)
    assert has_button(app, "Next week") and not has_button(app, "Finish the week")
    click(app, "Next week")
    assert "Week 2 of 4" in [s.value for s in app.subheader]


def test_the_temptation_can_be_bought_only_when_there_is_money_left():
    player = with_piggy()
    price = player.piggy.data["event"]["price_cents"] // 100
    app = launch(player=player)

    app.slider(key="piggy_save").set_value(10).run()  # everything saved: cannot afford it
    assert app.radio(key="piggy_buy").disabled is True
    assert any("cannot afford it this week" in c.value for c in app.caption)

    app.slider(key="piggy_save").set_value(10 - price).run()
    assert app.radio(key="piggy_buy").disabled is False
    app.radio(key="piggy_buy").set_value("Buy it").run()
    click(app, "Finish the week")
    assert " and bought " in assistant_text(app)
    assert sidebar(app)["Coins"] == str((10 - price) * 10)  # no bonus for resisting


def test_a_whole_piggy_game_ends_with_the_goal_and_can_be_played_again():
    app = launch(player=with_piggy())
    for week in range(4):
        app.slider(key="piggy_save").set_value(10).run()
        click(app, "Finish the week")
        if week < 3:
            click(app, "Next week")
    assert assistant_text(app).endswith("Little drops filled the jar.")
    assert sidebar(app)["Drop streak"] == "4 weeks"
    click(app, "Play again")
    assert "Week 1 of 4" in [s.value for s in app.subheader]
    assert sidebar(app)["Coins"] == "580"  # rewards carry over to the new game


def lemonade_app(player=None):
    app = launch(player=player or with_lemonade())
    app.radio(key="game").set_value("Lemonade Stand").run()
    assert not app.exception
    return app


def test_switching_to_lemonade_shows_the_first_sunny_day():
    app = lemonade_app()
    assert "Day 1 of 3: Sunny and hot" in [s.value for s in app.subheader]
    assert (app.select_slider(key="lemon_price").value, app.slider(key="lemon_cups").value) == (
        75,
        20,
    )
    assert any("Supplies will cost \\$4.00." == c.value for c in app.caption)
    assert any("Play a day to see your profit here." == c.value for c in app.caption)


def test_opening_the_stand_shows_the_result_the_feedback_and_the_chart():
    app = lemonade_app()
    click(app, "Open the stand")
    results = {m.label: m.value for m in app.main.metric}
    assert results == {"Profit": "$11.00", "Sold": "20 of 20", "Money in": "$15.00"}
    assert assistant_text(app) == (
        "You made exactly as many cups as people wanted. That is hard to do. "
        "You kept \\$11.00 as profit."
    )
    assert sidebar(app)["Coins"] == "110"
    assert app.session_state["player"].lemonade_profits == [1100]
    assert not any("Play a day to see your profit here." == c.value for c in app.caption)
    assert any("Bars above zero are profit" in c.value for c in app.caption)


def test_changing_price_and_cups_changes_the_outcome():
    app = lemonade_app()
    app.select_slider(key="lemon_price").set_value(150).run()
    app.slider(key="lemon_cups").set_value(60).run()
    assert any("Supplies will cost \\$12.00." == c.value for c in app.caption)
    click(app, "Open the stand")
    assert {m.label: m.value for m in app.main.metric}["Profit"].startswith("-$")
    assert "You lost money today" in assistant_text(app)


def test_three_lemonade_days_then_play_again():
    app = lemonade_app()
    for day in range(3):
        click(app, "Open the stand")
        if day < 2:
            click(app, "Next day")
    assert "That was the last day." in assistant_text(app)
    assert len(app.session_state["player"].lemonade_profits) == 3
    click(app, "Play again")
    assert "Day 1 of 3: Sunny and hot" in [s.value for s in app.subheader]
    assert app.session_state["player"].lemonade_profits == []


def test_a_game_is_started_automatically_the_first_time_the_tab_is_shown():
    app = launch(player=started())
    assert app.session_state["player"].piggy is not None
    app.radio(key="game").set_value("Lemonade Stand").run()
    assert app.session_state["player"].lemonade is not None


def test_restart_setup_also_clears_the_game_widgets():
    state = {"player": started(), "game": "Lemonade Stand", "piggy_save": 9, "lemon_cups": 50}
    fresh = reset_player(state)
    assert set(state) == {"player"} and fresh.piggy is None and fresh.lemonade is None
