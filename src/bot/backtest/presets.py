"""Strategy preset configurations for backtest parameter pre-fill.

Three preset levels provide quick parameter configuration:
- Conservative: Simple strategy with high thresholds (fewer but safer trades)
- Balanced: Composite strategy with moderate thresholds
- Aggressive: Composite strategy with low thresholds (more trades, higher risk)

Presets apply ONLY to the backtest form. They pre-fill parameters for
experimentation. They do NOT affect live trading parameters.
"""

STRATEGY_PRESETS: dict[str, dict] = {
    "conservative": {
        "label": "Conservative",
        "description": "Fewer trades, higher thresholds. Simple strategy with strict entry/exit.",
        "strategy_mode": "simple",
        "params": {
            "min_funding_rate": "0.0005",
            "exit_funding_rate": "0.0002",
        },
    },
    "balanced": {
        "label": "Balanced",
        "description": "Moderate entry/exit. Composite strategy with balanced signal weights.",
        "strategy_mode": "composite",
        "params": {
            "entry_threshold": "0.35",
            "exit_threshold": "0.2",
            "weight_rate_level": "0.35",
            "weight_trend": "0.25",
            "weight_persistence": "0.25",
            "weight_basis": "0.15",
        },
    },
    "aggressive": {
        "label": "Aggressive",
        "description": "More trades, lower thresholds. Composite strategy favoring rate level.",
        "strategy_mode": "composite",
        "params": {
            "entry_threshold": "0.25",
            "exit_threshold": "0.15",
            "weight_rate_level": "0.40",
            "weight_trend": "0.20",
            "weight_persistence": "0.25",
            "weight_basis": "0.15",
        },
    },
}
