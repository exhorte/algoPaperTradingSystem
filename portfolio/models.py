from decimal import Decimal

from django.db import models


class Portfolio(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    initial_cash = models.DecimalField(max_digits=15, decimal_places=2)
    current_cash = models.DecimalField(max_digits=15, decimal_places=2)
    total_value = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    snaptrade_user_id = models.CharField(max_length=100, blank=True)
    snaptrade_account_id = models.CharField(max_length=100, blank=True)
    snaptrade_user_secret = models.CharField(max_length=200, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "portfolios"
        ordering = ["name"]

    def __str__(self):
        return self.name

    def get_current_positions(self):
        """Open positions (quantity > 0) of this portfolio."""
        return self.positions.filter(quantity__gt=0).select_related("stock")

    def calculate_total_value(self):
        """Recompute total_value = cash + market value of open positions."""
        positions_value = sum(
            (pos.current_value for pos in self.get_current_positions()), Decimal("0")
        )
        self.total_value = self.current_cash + positions_value
        return self.total_value


class Position(models.Model):
    portfolio = models.ForeignKey(
        Portfolio, on_delete=models.CASCADE, related_name="positions"
    )
    stock = models.ForeignKey("trading.Stock", on_delete=models.CASCADE)
    quantity = models.IntegerField(default=0)
    average_cost = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    current_price = models.DecimalField(
        max_digits=12, decimal_places=4, null=True, blank=True
    )
    current_value = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    unrealized_pnl = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    unrealized_pnl_percent = models.DecimalField(
        max_digits=8, decimal_places=4, default=0
    )
    last_updated = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "positions"
        unique_together = ("portfolio", "stock")
        ordering = ["-current_value"]

    def __str__(self):
        return f"{self.portfolio} - {self.stock.ticker} x{self.quantity}"

    def update_current_value(self):
        """Recompute value and unrealized P&L from current_price / average_cost."""
        if self.current_price is None:
            return
        self.current_value = self.current_price * self.quantity
        cost_basis = self.average_cost * self.quantity
        self.unrealized_pnl = self.current_value - cost_basis
        if cost_basis > 0:
            self.unrealized_pnl_percent = (self.unrealized_pnl / cost_basis) * 100
        else:
            self.unrealized_pnl_percent = Decimal("0")


class Trade(models.Model):
    TRADE_TYPES = [
        ("BUY", "Buy"),
        ("SELL", "Sell"),
    ]

    STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("SUBMITTED", "Submitted"),
        ("FILLED", "Filled"),
        ("PARTIALLY_FILLED", "Partially Filled"),
        ("CANCELLED", "Cancelled"),
        ("REJECTED", "Rejected"),
    ]

    portfolio = models.ForeignKey(
        Portfolio, on_delete=models.CASCADE, related_name="trades"
    )
    stock = models.ForeignKey("trading.Stock", on_delete=models.CASCADE)
    trade_type = models.CharField(max_length=4, choices=TRADE_TYPES)
    quantity = models.IntegerField()
    price = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    filled_quantity = models.IntegerField(default=0)
    filled_price = models.DecimalField(
        max_digits=12, decimal_places=4, null=True, blank=True
    )
    order_value = models.DecimalField(
        max_digits=15, decimal_places=2, null=True, blank=True
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="PENDING")
    external_order_id = models.CharField(max_length=100, blank=True)
    snaptrade_order_id = models.CharField(max_length=100, blank=True)
    commission = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    error_message = models.TextField(blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    filled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "trades"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["portfolio", "status"]),
            models.Index(fields=["status", "created_at"]),
        ]

    def __str__(self):
        return f"{self.trade_type} {self.quantity} {self.stock.ticker} ({self.status})"

    def update_position(self):
        """Apply a filled trade to the matching Position of the portfolio."""
        qty = int(self.filled_quantity or 0)
        price = self.filled_price
        if qty <= 0 or price is None:
            return

        position, _ = Position.objects.get_or_create(
            portfolio=self.portfolio, stock=self.stock
        )
        if self.trade_type == "BUY":
            total_cost = position.average_cost * position.quantity + price * qty
            position.quantity += qty
            position.average_cost = total_cost / position.quantity
        else:
            position.quantity = max(0, position.quantity - qty)
        position.current_price = price
        position.update_current_value()
        position.save()


class PerformanceMetric(models.Model):
    portfolio = models.ForeignKey(
        Portfolio, on_delete=models.CASCADE, related_name="performance_metrics"
    )
    date = models.DateField()
    total_value = models.DecimalField(max_digits=15, decimal_places=2)
    cash_value = models.DecimalField(max_digits=15, decimal_places=2)
    positions_value = models.DecimalField(max_digits=15, decimal_places=2)
    daily_return = models.DecimalField(
        max_digits=8, decimal_places=6, null=True, blank=True
    )
    cumulative_return = models.DecimalField(
        max_digits=8, decimal_places=6, null=True, blank=True
    )
    total_trades = models.IntegerField(default=0)
    winning_trades = models.IntegerField(default=0)
    losing_trades = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "performance_metrics"
        unique_together = ("portfolio", "date")
        ordering = ["-date"]
        indexes = [
            models.Index(fields=["portfolio", "date"]),
        ]
