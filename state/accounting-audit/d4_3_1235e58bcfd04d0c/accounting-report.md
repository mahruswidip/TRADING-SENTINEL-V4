# D4.3 Accounting and Breakout Regime Audit

The prior `net_return` is aggregate normalized trade return, not portfolio equity return. The prior `max_drawdown` is a cumulative fixed-notional PnL decline normalized by one $1,000 trade, not standard equity drawdown. Values beyond 100% are therefore mathematically possible but were misleadingly named.

The research-only $10,000 reference equity applies fixed $1,000 trade PnL chronologically at exit, does not compound or model margin reservation, floors equity at zero, and stops applying later trades after bankruptcy.

BREAKOUT_RETEST_V2 high-volatility/expansion: 155 trades, expectancy 0.7174, PF 1.1526, 6 profitable symbols, top-symbol share 31.3%.

Decision: `REGIME_HYPOTHESIS_NOT_JUSTIFIED`. V3 was not created. Locked OOS was not accessed.
