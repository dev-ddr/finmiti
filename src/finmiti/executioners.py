from typing import List
from .constants import Order, ORDERTYPE


class ExecutionModel:
    """ExecutionModel is a simulator of a real market. Slippage, volume limits, liquidity etc. kind of real-market scenarios should be implemented here. This could have also been done in portfolio handler but we apply it here for separating the responsibilities.

    Thus ExecutionModel introduces real-market noise. And portfolio simply stores the order.
    """

    def __init__(self, brokerage_perc: float = 0.0):
        self.brokerage = 0.0

    def fill_buy_order(self, order: Order, available_cash: float) -> Order:
        total_cost = available_cash * order.value_frac
        ### the total cost includes brokerage cost. Thus the amount available to buy is obtained after deducting brokerage from the total cost.
        ### the formula is total_cost = net_cost * (1 + self.brokerage), thus
        net_cost = total_cost / (1 + self.brokerage)

        order.fill_price = order.price
        order.fill_qty = net_cost / order.fill_price
        order.fill_timestamp = order.timestamp
        order.brokerage_cost = total_cost - net_cost
        order.total_cost = total_cost
        order.fill_remarks = "No added noise"

        return order

    def fill_sell_order(self, order: Order) -> Order:
        gross_receivable = order.fill_qty * order.price
        net_receivable = gross_receivable / (1 + self.brokerage)

        order.fill_price = order.price
        order.fill_timestamp = order.timestamp
        order.brokerage_cost = gross_receivable - net_receivable
        order.total_cost = net_receivable
        order.fill_remarks = "No added noise"

        return order

    def fill_order(self, order: Order, available_cash: float) -> Order:
        """
        Naive execution: fill immediately at order.price
        """
        if order.order_type == ORDERTYPE.buy:
            order = self.fill_buy_order(order=order, available_cash=available_cash)
        elif order.order_type == ORDERTYPE.sell:
            order = self.fill_sell_order(order=order)
        return order
