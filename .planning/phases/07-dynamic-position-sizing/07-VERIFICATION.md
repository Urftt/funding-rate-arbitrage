---
phase: 07-dynamic-position-sizing
verified: 2026-02-12T22:55:00Z
status: passed
score: 10/10 must-haves verified
re_verification: false
---

# Phase 7: Dynamic Position Sizing Verification Report

**Phase Goal:** Position sizes scale with signal conviction so higher-confidence opportunities get larger allocations, constrained by portfolio-level risk limits

**Verified:** 2026-02-12T22:55:00Z

**Status:** passed

**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| #   | Truth                                                                                                                              | Status     | Evidence                                                                                                                  |
| --- | ---------------------------------------------------------------------------------------------------------------------------------- | ---------- | ------------------------------------------------------------------------------------------------------------------------- |
| 1   | A pair with a strong composite signal (score=0.9) gets a larger budget than a pair with a weak signal (score=0.3)                 | ✓ VERIFIED | Test `test_strong_signal_larger_than_weak` passes; DynamicSizer.compute_signal_budget implements linear interpolation    |
| 2   | Budget is None when current portfolio exposure >= max_portfolio_exposure                                                           | ✓ VERIFIED | Tests `test_budget_none_at_cap` and `test_budget_none_over_cap` pass; portfolio cap logic verified                       |
| 3   | DynamicSizer.calculate_matching_quantity calls PositionSizer.calculate_matching_quantity (delegation, not duplication)            | ✓ VERIFIED | Test `test_delegates_to_position_sizer` verifies delegation via mock; pattern found at line 131 of dynamic_sizer.py      |
| 4   | In composite mode with dynamic sizing enabled, orchestrator computes signal-adjusted budget and passes it as available_balance    | ✓ VERIFIED | Orchestrator lines 501-527: budget computed, min(free, budget) passed to open_position                                    |
| 5   | Portfolio exposure is recomputed after each successful position open within the same cycle                                        | ✓ VERIFIED | Orchestrator line 527: `current_exposure += position.quantity * position.perp_entry_price` after successful open          |
| 6   | When dynamic sizing is disabled or strategy_mode is simple, existing static sizing behavior is unchanged                          | ✓ VERIFIED | Orchestrator lines 537-539: `else` path unchanged; main.py line 172: gated on `sizing.enabled and strategy_mode=="composite"` |
| 7   | BacktestEngine in composite mode uses DynamicSizer when sizing params are provided in BacktestConfig                              | ✓ VERIFIED | BacktestEngine lines 137-142: DynamicSizer created when `strategy_mode=="composite" and sizing_enabled`                  |
| 8   | DynamicSizingSettings exists in config.py with SIZING_ env prefix                                                                 | ✓ VERIFIED | config.py lines 147-161: class with 4 fields, env_prefix="SIZING_", included in AppSettings.sizing                       |
| 9   | BacktestConfig has dynamic sizing parameters and to_sizing_settings() method                                                      | ✓ VERIFIED | models.py lines 50-53: sizing fields; lines 87-103: to_sizing_settings() method                                          |
| 10  | Tests prove SIZE-01 (strong > weak), SIZE-02 (None at cap), SIZE-03 (delegates to PositionSizer)                                  | ✓ VERIFIED | 11 tests in test_dynamic_sizer.py covering all 3 requirements; all tests pass                                            |

**Score:** 10/10 truths verified

### Required Artifacts

| Artifact                                     | Expected                                                                        | Status     | Details                                                                                           |
| -------------------------------------------- | ------------------------------------------------------------------------------- | ---------- | ------------------------------------------------------------------------------------------------- |
| `src/bot/position/dynamic_sizer.py`          | DynamicSizer class with compute_signal_budget and calculate_matching_quantity   | ✓ VERIFIED | 137 lines, exports DynamicSizer, both methods present with full implementation                    |
| `src/bot/config.py`                          | DynamicSizingSettings with SIZING_ env prefix                                   | ✓ VERIFIED | Lines 147-161: class with 4 fields, env_prefix="SIZING_", default enabled=False                  |
| `tests/test_position/test_dynamic_sizer.py`  | Tests proving SIZE-01, SIZE-02, SIZE-03                                         | ✓ VERIFIED | 293 lines, 11 tests across 3 test classes (TestSignalBudget, TestPortfolioCap, TestDelegation)   |
| `src/bot/orchestrator.py`                    | DynamicSizer integration in composite entry flow with portfolio exposure tracking | ✓ VERIFIED | Lines 97, 454-461, 476-539: optional DynamicSizer param, _compute_current_exposure, integrated flow |
| `src/bot/main.py`                            | DynamicSizer creation and injection into orchestrator                          | ✓ VERIFIED | Lines 170-177: creation gated on sizing.enabled + composite mode, injected into Orchestrator     |
| `src/bot/backtest/engine.py`                 | DynamicSizer integration in composite backtest mode                            | ✓ VERIFIED | Lines 135-142: creation, 145: _last_signal_score, 340-359: usage, 440-448: _compute_current_exposure |
| `src/bot/backtest/models.py`                 | Dynamic sizing parameters in BacktestConfig                                     | ✓ VERIFIED | Lines 50-53: sizing fields, 87-103: to_sizing_settings(), 130-133: to_dict() includes sizing params |

### Key Link Verification

| From                               | To                                 | Via                                                                             | Status     | Details                                                                              |
| ---------------------------------- | ---------------------------------- | ------------------------------------------------------------------------------- | ---------- | ------------------------------------------------------------------------------------ |
| `src/bot/position/dynamic_sizer.py` | `src/bot/position/sizing.py`       | PositionSizer injected into DynamicSizer constructor, called in calculate_matching_quantity | ✓ WIRED    | Line 131: `self._sizer.calculate_matching_quantity(...)` delegates to PositionSizer  |
| `src/bot/position/dynamic_sizer.py` | `src/bot/config.py`                | DynamicSizingSettings imported and used for allocation fractions and portfolio cap | ✓ WIRED    | Line 15: import, lines 66-78: settings used in compute_signal_budget                |
| `src/bot/orchestrator.py`          | `src/bot/position/dynamic_sizer.py` | DynamicSizer injected as optional dependency, called in _open_profitable_positions_composite | ✓ WIRED    | Line 46: TYPE_CHECKING import, line 97: param, lines 503-527: usage                 |
| `src/bot/main.py`                  | `src/bot/position/dynamic_sizer.py` | Creates DynamicSizer when sizing.enabled and strategy_mode==composite          | ✓ WIRED    | Line 173: `DynamicSizer(...)` creation, line 186: injected into Orchestrator        |
| `src/bot/backtest/engine.py`       | `src/bot/position/dynamic_sizer.py` | Creates DynamicSizer when config has sizing enabled in composite mode          | ✓ WIRED    | Line 138: `DynamicSizer(...)` creation, lines 346-347: compute_signal_budget usage  |
| `src/bot/orchestrator.py`          | `src/bot/models.py`                | Reads Position.quantity and Position.perp_entry_price for exposure computation | ✓ WIRED    | Lines 457-459: `pos.quantity * pos.perp_entry_price` in _compute_current_exposure   |

### Requirements Coverage

| Requirement | Description                                                                       | Status      | Supporting Truths |
| ----------- | --------------------------------------------------------------------------------- | ----------- | ----------------- |
| SIZE-01     | Position size scales with signal confidence (higher conviction = larger position) | ✓ SATISFIED | Truth #1, #4      |
| SIZE-02     | Total portfolio exposure is capped at configurable limit                          | ✓ SATISFIED | Truth #2, #5      |
| SIZE-03     | Dynamic sizer delegates to existing PositionSizer for exchange constraint validation | ✓ SATISFIED | Truth #3          |

### Anti-Patterns Found

No anti-patterns detected.

Scanned files:
- `src/bot/position/dynamic_sizer.py` - No TODO/FIXME/placeholders, no empty returns, full implementation
- `src/bot/orchestrator.py` - Clean integration, proper null checks, exposure tracking correct
- `src/bot/main.py` - Proper gating on sizing.enabled + composite mode
- `src/bot/backtest/engine.py` - Clean integration, _last_signal_score pattern is simple and effective
- `src/bot/backtest/models.py` - Complete sizing params, to_sizing_settings() method present

### Human Verification Required

None. All observable truths are verified programmatically through:
- Unit tests (11 tests covering SIZE-01, SIZE-02, SIZE-03)
- Code inspection (delegation, wiring, exposure tracking)
- Integration verification (orchestrator, main.py, backtest engine all wired correctly)

### Gaps Summary

No gaps found. All 10 observable truths verified, all 7 artifacts pass all 3 levels (exists, substantive, wired), all 6 key links verified as wired, and all 3 requirements satisfied.

Phase goal achieved: Position sizes scale with signal conviction (SIZE-01), constrained by portfolio-level risk limits (SIZE-02), with proper delegation to existing components (SIZE-03).

## Verification Details

### Plan 07-01: DynamicSizer Core (TDD)

**Artifacts verified:**
- DynamicSizer class: 137 lines with compute_signal_budget (linear interpolation formula) and calculate_matching_quantity (delegation)
- DynamicSizingSettings: 4 fields (enabled, min_allocation_fraction, max_allocation_fraction, max_portfolio_exposure), SIZING_ env prefix, default enabled=False
- Tests: 293 lines, 11 tests proving all 3 SIZE requirements

**Key patterns verified:**
- Linear interpolation: `fraction = min_frac + (max_frac - min_frac) * signal_score`
- Portfolio cap: `remaining = max_portfolio_exposure - current_exposure; return None if remaining <= 0`
- Delegation: `self._sizer.calculate_matching_quantity(...)` — no duplicate logic

**Commits verified:**
- 2324056: feat(07-01): add DynamicSizingSettings to config
- 92b2361: test(07-01): add failing tests for DynamicSizer (RED)
- 11b175b: feat(07-01): implement DynamicSizer (GREEN)

### Plan 07-02: Integration (Orchestrator, Main, Backtest)

**Orchestrator integration verified:**
- Optional DynamicSizer parameter (line 97)
- _compute_current_exposure() method (lines 454-461): sums `pos.quantity * pos.perp_entry_price`
- Pre-compute exposure before loop (line 476-479)
- Signal-adjusted budget computation (lines 503-506)
- Break on portfolio cap (lines 507-513)
- Exposure update after successful open (line 527)
- Unchanged static path when dynamic_sizer is None (lines 537-539)

**Main.py integration verified:**
- DynamicSizer creation gated on `sizing.enabled and strategy_mode=="composite"` (line 172)
- Injected into Orchestrator constructor (line 186)

**BacktestEngine integration verified:**
- DynamicSizer creation when `strategy_mode=="composite" and sizing_enabled` (lines 137-142)
- _last_signal_score tracking (line 145, reset line 495, set line 516)
- _compute_current_exposure() method (lines 440-448)
- Signal-adjusted available_balance (lines 340-359)

**BacktestConfig verified:**
- 4 sizing fields (lines 50-53)
- to_sizing_settings() method (lines 87-103)
- to_dict() includes sizing params (lines 130-133)

**Commits verified:**
- af866b6: feat(07-02): wire DynamicSizer into orchestrator and main.py
- 593e691: feat(07-02): wire DynamicSizer into backtest engine and config

### Test Pass Verification

Summary claims 286/286 tests pass. All key DynamicSizer tests verified:
- TestSignalBudget: 4 tests (strong > weak, max score, min score, linear interpolation)
- TestPortfolioCap: 4 tests (at cap, over cap, capped by remaining, zero exposure)
- TestDelegation: 3 tests (delegates to PositionSizer, returns None when budget None, effective balance is min)

All tests align with SIZE-01, SIZE-02, SIZE-03 requirements.

---

_Verified: 2026-02-12T22:55:00Z_
_Verifier: Claude (gsd-verifier)_
