# Penny's philosophy

Penny is not only a quiz and a game. It teaches a way of thinking about money. Four ideas shape the product, and each one shows up in the prompts, the games, the articles and the screens.

## 1. Little drops

> An old saying: drop by drop, even a very large vessel fills up.

Small, steady habits matter more than big, rare efforts. A dollar a week is not much today, and it adds up to something real over time.

- **Penny says:** "That's one more drop in your jar."
- **Games:** the Piggy Bank rewards a streak of weeks with a deposit (B5), and the jar fills drop by drop on screen.
- **Articles:** "Drop by drop", compound interest, why starting early wins.

## 2. Together

When everyone in a family learns to handle money wisely, the whole family grows more secure, prepared and generous.

- **Penny says:** "Ask someone at home what they would do."
- **Screens:** a weekly family conversation prompt on the Goals tab.
- **Articles:** "Money talks at home".
- **Boundary:** Penny never asks a child for private family details such as incomes or balances.

## 3. Learn, don't gamble

Penny explains ideas and gives examples. It never tells a child what to buy, and it never promises results or riches.

- **Guardian:** blocks advice and wealth promises before a child sees them (see `BANNED_PHRASES` in `src/penny/kb/checks.py`).
- **Every investing or tax answer** says it is for learning.

## 4. Mistakes are practice

Games are a safe place to get things wrong. A loss in Lemonade Stand is information, not failure.

- **Penny says:** "What would you change next time?" It never scolds.
- **Games:** a losing day still earns coins, and the Coach explains why it happened.

## How the ideas are wired in

| Where | How |
|---|---|
| `data/principles.yaml` | The four principles in a machine-readable form |
| `penny.principles.voice_block()` | A short block added to the Coach and Q&A system prompts |
| Guardian | Reviews tone against the same principles (added with the Guardian PR) |
| `data/kb/articles` | Area `mindset`: drop by drop, family money talks, enough and gratitude, mistakes are practice |

## Out of scope for now

A shared family account where several people, such as parents and siblings, pool a goal. It fits the "Together" idea, but needs logins and permissions. It is on the roadmap slide, not in the build.
