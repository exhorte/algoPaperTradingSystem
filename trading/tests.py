from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from trading.models import MomentumScore, Stock, TradingSignal


class PageSmokeTests(TestCase):
    def test_pages_render_without_data(self):
        for name in ("trading:dashboard", "trading:momentum_scores", "trading:trading_signals"):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)

    def test_pages_render_with_data(self):
        today = date.today()
        for i, ticker in enumerate(["AAA", "BBB", "CCC", "DDD", "EEE"]):
            stock = Stock.objects.create(ticker=ticker)
            score = MomentumScore.objects.create(
                stock=stock,
                calculation_date=today,
                momentum_score=Decimal(str(0.5 - i * 0.2)),
                period_start=today,
                period_end=today,
            )
        MomentumScore.calculate_quintiles_for_date(today)
        TradingSignal.objects.create(
            stock=stock, signal_date=today, signal_type="SELL", momentum_score=score
        )

        response = self.client.get(reverse("trading:dashboard"))
        self.assertContains(response, "AAA")
        self.assertContains(response, "Total Stocks")
        response = self.client.get(reverse("trading:momentum_scores"))
        self.assertContains(response, "Q1")
        response = self.client.get(reverse("trading:trading_signals") + "?type=sell")
        self.assertContains(response, "EEE")

    def test_generate_signals_requires_momentum_data(self):
        response = self.client.post(reverse("trading:generate_signals"))
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["success"])
