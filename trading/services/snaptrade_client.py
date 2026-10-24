from django.conf import settings
from snaptrade_client import SnapTrade, SnapTradeAuth
from portfolio.models import Portfolio
from typing import List, Optional, Tuple
from portfolio.models import Position
from trading.models import Stock
from portfolio.models import Trade
from decimal import Decimal
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)

# SnapTrade order states -> Trade.STATUS_CHOICES
ORDER_STATUS_MAP = {
    "NONE": "PENDING",
    "PENDING": "SUBMITTED",
    "ACCEPTED": "SUBMITTED",
    "QUEUED": "SUBMITTED",
    "OPEN": "SUBMITTED",
    "SUBMITTED": "SUBMITTED",
    "PARTIAL": "PARTIALLY_FILLED",
    "PARTIALLY_FILLED": "PARTIALLY_FILLED",
    "PARTIAL_CANCELED": "PARTIALLY_FILLED",
    "EXECUTED": "FILLED",
    "FILLED": "FILLED",
    "CANCELED": "CANCELLED",
    "CANCELLED": "CANCELLED",
    "EXPIRED": "CANCELLED",
    "REJECTED": "REJECTED",
    "FAILED": "REJECTED",
}


def _body(response):
    """SDK responses expose the parsed payload on `.body`."""
    return response.body if hasattr(response, "body") else response


def _get(data, *keys, default=None):
    """Safe nested `.get` over dict-like objects (the SDK returns frozendicts)."""
    for key in keys:
        if data is None or not hasattr(data, "get"):
            return default
        data = data.get(key)
    return default if data is None else data


class TradingExecutor:
    """SnapTrade (Alpaca) integration: OAuth connection, positions, orders."""

    def __init__(self):
        client_id = settings.SNAPTRADE_CLIENT_ID
        consumer_key = settings.SNAPTRADE_CLIENT_SECRET
        if not client_id or not consumer_key:
            raise ValueError("SnapTrade client ID and client secret are required")

        # SnapTrade "Personal" API keys have a client id starting with PERS-,
        # every other key is a "Commercial" key. The SDK needs to know which.
        if client_id.upper().startswith("PERS"):
            auth = SnapTradeAuth.personal_api_key(
                consumer_key=consumer_key, client_id=client_id
            )
        else:
            auth = SnapTradeAuth.commercial_api_key(
                consumer_key=consumer_key, client_id=client_id
            )
        self.snaptrade = SnapTrade(auth=auth)

    # ------------------------------------------------------------------
    # OAuth / connection flow
    # ------------------------------------------------------------------
    def register_user(self, user_id: str) -> Tuple[str, str]:
        """
        Register a SnapTrade user and return (user_id, user_secret).
        Personal API keys cannot register users: in that case set
        SNAPTRADE_USER_ID / SNAPTRADE_USER_SECRET in .env.
        """
        if settings.SNAPTRADE_USER_ID and settings.SNAPTRADE_USER_SECRET:
            return settings.SNAPTRADE_USER_ID, settings.SNAPTRADE_USER_SECRET

        response = self.snaptrade.authentication.register_snap_trade_user(
            user_id=user_id
        )
        data = _body(response)
        return data["userId"], data["userSecret"]

    def get_connection_portal_url(
        self,
        user_id: str,
        user_secret: str,
        redirect_url: str,
        broker: str = "ALPACA",
    ) -> str:
        """URL of the SnapTrade connection portal (OAuth) for the given broker."""
        response = self.snaptrade.authentication.login_snap_trade_user(
            user_id=user_id,
            user_secret=user_secret,
            broker=broker,
            custom_redirect=redirect_url,
            connection_type="trade",
        )
        data = _body(response)
        url = _get(data, "redirectURI") or _get(data, "redirect_uri")
        if not url:
            raise ValueError("SnapTrade did not return a connection portal URL")
        return url

    def list_accounts(self, user_id: str, user_secret: str) -> list:
        response = self.snaptrade.account_information.list_user_accounts(
            user_id=user_id, user_secret=user_secret
        )
        return list(_body(response))

    # ------------------------------------------------------------------
    # Portfolio synchronisation
    # ------------------------------------------------------------------
    def sync_portfolio_positions(
        self, portfolio: Portfolio, user_secret: str = None
    ) -> List[Position]:
        user_secret = user_secret or portfolio.snaptrade_user_secret

        if not portfolio.snaptrade_user_id or not portfolio.snaptrade_account_id:
            raise ValueError("Portfolio must have SnapTrade user and account IDs")

        if not user_secret:
            raise ValueError("SnapTrade user secret is required for API operations")

        try:
            positions_response = (
                self.snaptrade.account_information.get_all_account_positions(
                    user_id=portfolio.snaptrade_user_id,
                    user_secret=user_secret,
                    account_id=portfolio.snaptrade_account_id,
                )
            )

            positions_data = _body(positions_response)
            # Current API wraps the list in {"results": [...]}; legacy returned a list.
            if hasattr(positions_data, "get") and positions_data.get("results") is not None:
                positions_data = positions_data.get("results")

            synced_positions = []

            for pos_data in positions_data:
                symbol = (
                    _get(pos_data, "instrument", "symbol")
                    or _get(pos_data, "symbol", "symbol", "raw_symbol")
                    or _get(pos_data, "symbol", "raw_symbol")
                    or ""
                )
                if not isinstance(symbol, str):
                    symbol = str(_get(symbol, "raw_symbol", default=""))
                quantity = float(
                    _get(pos_data, "quantity", default=_get(pos_data, "units", default=0))
                )
                average_cost = float(
                    _get(pos_data, "average_purchase_price", default=0)
                )
                current_price = float(_get(pos_data, "price", default=0))

                if not symbol or quantity <= 0:
                    continue

                stock, _ = Stock.objects.get_or_create(
                    ticker=symbol, defaults={"name": symbol, "is_active": True}
                )

                position, created = Position.objects.update_or_create(
                    portfolio=portfolio,
                    stock=stock,
                    defaults={
                        "quantity": int(quantity),
                        "average_cost": Decimal(str(average_cost)),
                        "current_price": Decimal(str(current_price)),
                    },
                )

                position.update_current_value()
                position.save()
                synced_positions.append(position)

                logger.info(
                    f"{'Created' if created else 'Updated'} position: {symbol} - {quantity} shares"
                )

            # Update portfolio cash balance
            balance_response = (
                self.snaptrade.account_information.get_user_account_balance(
                    user_id=portfolio.snaptrade_user_id,
                    user_secret=user_secret,
                    account_id=portfolio.snaptrade_account_id,
                )
            )

            balance_data = _body(balance_response)
            if balance_data and not isinstance(balance_data, (str, bytes)):
                balance_item = balance_data[0] if isinstance(balance_data, (list, tuple)) else balance_data
                cash_balance = float(_get(balance_item, "cash", default=0))
                portfolio.current_cash = Decimal(str(cash_balance))
                portfolio.calculate_total_value()
                portfolio.save()
                logger.info(f"Updated portfolio cash balance to ${cash_balance}")

            return synced_positions

        except (ValueError, TypeError, KeyError) as e:
            logger.error(f"Error syncing portfolio positions: {str(e)}")
            raise

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------
    def execute_buy_orders(
        self,
        portfolio: Portfolio,
        buy_list: List[Stock],
        total_value: Decimal,
        user_secret: str = None,
    ) -> List[Trade]:
        if not buy_list:
            return []

        user_secret = user_secret or portfolio.snaptrade_user_secret
        if not user_secret:
            raise ValueError("SnapTrade user secret is required for trading operations")

        # Equal weight allocation
        allocation_per_stock = total_value / len(buy_list)
        executed_trades = []

        for stock in buy_list:
            trade = None
            try:
                # Quantity is determined by the broker from the notional value
                trade = Trade.objects.create(
                    portfolio=portfolio,
                    stock=stock,
                    trade_type="BUY",
                    quantity=0,
                    price=allocation_per_stock,  # dollar amount, for reference
                    order_value=allocation_per_stock,
                    status="PENDING",
                )

                order_response = self.snaptrade.trading.place_force_order(
                    user_id=portfolio.snaptrade_user_id,
                    user_secret=user_secret,
                    account_id=portfolio.snaptrade_account_id,
                    action="BUY",
                    order_type="Market",
                    time_in_force="Day",
                    notional_value=float(allocation_per_stock),
                    symbol=stock.ticker,
                )

                order_result = _body(order_response)
                order_id = _get(order_result, "brokerage_order_id") or _get(
                    order_result, "id", default=""
                )
                trade.external_order_id = str(order_id)
                trade.snaptrade_order_id = str(order_id)
                trade.status = "SUBMITTED"
                trade.submitted_at = timezone.now()
                trade.save()

                executed_trades.append(trade)
                logger.info(
                    f"Submitted buy order: ${float(allocation_per_stock)} notional value of {stock.ticker}"
                )

            except Exception as e:
                logger.error(f"Error executing buy order for {stock.ticker}: {str(e)}")
                if trade is not None:
                    trade.status = "REJECTED"
                    trade.error_message = str(e)
                    trade.save()
                # Surface SnapTrade errors to the UI
                raise Exception(f"Buy order failed for {stock.ticker}: {str(e)}")

        return executed_trades

    def execute_sell_orders(
        self, portfolio: Portfolio, sell_list: List[Stock], user_secret: str = None
    ) -> List[Trade]:
        if not sell_list:
            return []

        user_secret = user_secret or portfolio.snaptrade_user_secret
        if not user_secret:
            raise ValueError("SnapTrade user secret is required for trading operations")

        executed_trades = []
        current_positions = {
            pos.stock.ticker: pos for pos in portfolio.get_current_positions()
        }

        for stock in sell_list:
            if stock.ticker not in current_positions:
                continue

            position = current_positions[stock.ticker]
            if position.quantity <= 0:
                continue

            trade = None
            try:
                trade = Trade.objects.create(
                    portfolio=portfolio,
                    stock=stock,
                    trade_type="SELL",
                    quantity=position.quantity,
                    price=position.current_price,
                    status="PENDING",
                )

                order_response = self.snaptrade.trading.place_force_order(
                    user_id=portfolio.snaptrade_user_id,
                    user_secret=user_secret,
                    account_id=portfolio.snaptrade_account_id,
                    action="SELL",
                    order_type="Market",
                    time_in_force="Day",
                    units=int(position.quantity),
                    symbol=stock.ticker,
                )

                order_result = _body(order_response)
                order_id = _get(order_result, "brokerage_order_id") or _get(
                    order_result, "id", default=""
                )
                trade.external_order_id = str(order_id)
                trade.snaptrade_order_id = str(order_id)
                trade.status = "SUBMITTED"
                trade.submitted_at = timezone.now()
                trade.save()

                executed_trades.append(trade)
                logger.info(
                    f"Submitted sell order: {position.quantity} shares of {stock.ticker}"
                )

            except Exception as e:
                logger.error(f"Error executing sell order for {stock.ticker}: {str(e)}")
                if trade is not None:
                    trade.status = "REJECTED"
                    trade.error_message = str(e)
                    trade.save()
                raise Exception(f"Sell order failed for {stock.ticker}: {str(e)}")

        return executed_trades

    def update_trade_status(self, trade: Trade, user_secret: str = None) -> bool:
        if not trade.external_order_id or trade.status in [
            "FILLED",
            "CANCELLED",
            "REJECTED",
        ]:
            return False

        user_secret = user_secret or trade.portfolio.snaptrade_user_secret
        if not user_secret:
            raise ValueError(
                "SnapTrade user secret is required for trade status updates"
            )

        try:
            response = self.snaptrade.account_information.get_user_account_order_detail(
                user_id=trade.portfolio.snaptrade_user_id,
                user_secret=user_secret,
                account_id=trade.portfolio.snaptrade_account_id,
                brokerage_order_id=trade.external_order_id,
            )
            order_status = _body(response)

            old_status = trade.status
            raw_state = str(_get(order_status, "status", default=_get(order_status, "state", default=""))).upper()
            trade.status = ORDER_STATUS_MAP.get(raw_state, trade.status)

            filled = _get(order_status, "filled_quantity", default=_get(order_status, "filled_units"))
            if filled:
                trade.filled_quantity = int(float(filled))

            executed_price = _get(order_status, "execution_price", default=_get(order_status, "executed_price"))
            if executed_price:
                trade.filled_price = Decimal(str(executed_price))

            if trade.status == "FILLED":
                trade.filled_at = timezone.now()
                trade.update_position()

            trade.save()

            if old_status != trade.status:
                logger.info(
                    f"Trade {trade.id} status updated: {old_status} -> {trade.status}"
                )

            return True

        except (ValueError, TypeError, KeyError) as e:
            logger.error(f"Error updating trade status for trade {trade.id}: {str(e)}")
            return False

    def _get_current_stock_price(self, ticker: str) -> Optional[Decimal]:
        # Simplified implementation - in production, use real-time price feed
        try:
            from trading.services.massive_client import get_massive_client
            from datetime import datetime

            massive_client = get_massive_client()
            price = massive_client.get_price_on_date(ticker, datetime.now())
            return Decimal(str(price)) if price else None
        except (ValueError, TypeError) as e:
            logger.error(f"Error getting current price for {ticker}: {str(e)}")
            return None

    def get_available_cash_for_trading(self, portfolio: Portfolio) -> Decimal:
        # Reserve 5% cash buffer
        return portfolio.current_cash * Decimal("0.95")


def get_trading_executor() -> TradingExecutor:
    return TradingExecutor()
