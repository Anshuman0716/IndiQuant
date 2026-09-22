from datetime import date
from indiquant.costs.statutory import StatutoryCostModel
from indiquant.costs.slippage import SlippageModel
from indiquant.costs.constraints import ExecutionConstraints
from indiquant.engine.execution import ExecutionModel

statutory = StatutoryCostModel(brokerage_rate=0.0001, flat_brokerage=0.0)
slippage = SlippageModel()
constraints = ExecutionConstraints(enforce_circuits=False, enforce_whole_shares=True)

exec_model = ExecutionModel(statutory, slippage, constraints)

# 1 Crore total volume per trade, for a representative round trip
res_buy = exec_model.simulate_fill(
    trade_date=date(2024,1,15),
    side="BUY",
    target_qty=10000,
    mkt_open=1000,
    mkt_high=1020,
    mkt_low=980,
    mkt_close=1000,
    mkt_prev_close=1000,
    mkt_volume=1000000,
)

res_sell = exec_model.simulate_fill(
    trade_date=date(2024,1,15),
    side="SELL",
    target_qty=10000,
    mkt_open=1000,
    mkt_high=1020,
    mkt_low=980,
    mkt_close=1000,
    mkt_prev_close=1000,
    mkt_volume=1000000,
)

print(f'cost_breakdown={{')
print(f'    "Brokerage": {res_buy["cost_brokerage"] + res_sell["cost_brokerage"]},')
print(f'    "STT": {res_buy["cost_stt"] + res_sell["cost_stt"]},')
print(f'    "Exchange Charges": {res_buy["cost_exchange"] + res_sell["cost_exchange"]},')
print(f'    "GST": {res_buy["cost_gst"] + res_sell["cost_gst"]},')
print(f'    "Stamp Duty": {res_buy["cost_stamp"] + res_sell["cost_stamp"]},')
print(f'    "Slippage": {res_buy["slippage_cost"] + res_sell["slippage_cost"]}')
print(f'}}')
