"""Broker API adapters for reconciliation and live data.

These are NOT Source subclasses — they are lightweight wrappers around
broker APIs (Zerodha Kite, Dhan) used for:
  1. Reconciliation: compare lakehouse data against broker's historical API
  2. Live data: real-time prices for paper trading / execution

yfinance is acceptable for smoke tests ONLY (AGENTS.md).
"""
