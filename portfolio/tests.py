from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from portfolio.models import Portfolio


class PortfolioPageTests(TestCase):
    def test_empty_list(self):
        response = self.client.get(reverse("portfolio:list"))
        self.assertContains(response, "No Portfolios Yet")

    def test_create_page(self):
        response = self.client.get(reverse("portfolio:create"))
        self.assertContains(response, "Connect Securely via SnapTrade")

    def test_create_rejects_duplicate_name(self):
        Portfolio.objects.create(name="Growth", initial_cash=0, current_cash=0)
        response = self.client.post(reverse("portfolio:create"), {"name": "Growth"})
        self.assertContains(response, "already exists")

    def test_callback_without_pending_redirects(self):
        response = self.client.get(reverse("portfolio:create_callback"))
        self.assertRedirects(response, reverse("portfolio:create"))

    def test_detail(self):
        portfolio = Portfolio.objects.create(
            name="Growth", initial_cash=Decimal("1000"), current_cash=Decimal("1000")
        )
        response = self.client.get(reverse("portfolio:detail", args=[portfolio.pk]))
        self.assertContains(response, "No open positions")
