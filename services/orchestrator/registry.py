"""Loads + Pydantic-validates every services/agents/*/manifest.yaml.
A manifest that fails validation makes the agent UNAVAILABLE — never render a
partially-valid agent (spec.md §1). Implemented in T-020.
"""
