# Trading constitution

No trading is implemented in Phase 01. These are gates for a future proposal.

- Capital preservation outranks return targets; no profit rate is guaranteed.
- Leverage must never be derived directly from model confidence.
- Every order requires pre-trade exposure, liquidity, slippage, fee, funding, drawdown, and venue
  checks plus an explicit kill switch.
- Stop-loss and trailing logic are execution policies, not guarantees against gaps or liquidation.
- Paper trading, historical simulation, walk-forward validation, and a monitored canary must
  precede real funds.
- Credentials are least-privilege, withdrawal-disabled, venue-specific, and never available to
  analytics or Telegram.
- A risk veto cannot be overridden by a vote, news event, or operator notification.

The current repository has no exchange adapter and cannot place or simulate orders.

## Owner-proposed future policy (documented, not enforced)

- Initial capital reference: USD 5,000; maximum simultaneous positions: 3.
- Daily hard loss: -3%; weekly hard loss: -7%.
- Weekly target: +10% is a target, never an obligation to open a trade.
- Daily “jackpot” at +10%: close all and rest.
- Portfolio protection milestones to design and validate: +3%, +6%, +10%.
- Saturday 00:00 Asia/Aqtobe: monitor only; Monday 05:00 Asia/Aqtobe: trading may resume.
- High-impact event mode begins at T-30 minutes.
- Only the owner may change the future Risk Constitution.

These numbers require independent risk review and extensive simulation before implementation;
documentation does not make the return or loss bounds achievable or guaranteed.
