from django.core.management.base import BaseCommand
from django.utils import timezone

from trading.services.massive_client import SP500_BASE_TICKERS
from trading.services.momentum_calculator import get_momentum_calculator


class Command(BaseCommand):
    help = (
        "Seed the stock universe (50 S&P 500 stocks by default), backfill their "
        "daily price history from Massive, then compute today's momentum scores."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--tickers", nargs="+", help="Tickers to backfill (default: base universe)"
        )
        parser.add_argument(
            "--limit", type=int, default=50, help="Max number of tickers (default: 50)"
        )
        parser.add_argument(
            "--days", type=int, default=420, help="Days of history (default: 420)"
        )
        parser.add_argument(
            "--skip-momentum",
            action="store_true",
            help="Only backfill prices, do not compute momentum scores",
        )

    def handle(self, *args, **options):
        tickers = (options["tickers"] or SP500_BASE_TICKERS)[: options["limit"]]
        calculator = get_momentum_calculator()

        stocks = calculator.update_stock_universe(tickers)
        self.stdout.write(f"Stock universe: {len(stocks)} stocks")

        total = 0
        for i, stock in enumerate(stocks, start=1):
            # Massive free tier: 5 requests/minute, the client sleeps when needed
            created = calculator.backfill_price_data(stock, days_back=options["days"])
            total += created
            self.stdout.write(f"[{i}/{len(stocks)}] {stock.ticker}: {created} new price records")
        self.stdout.write(self.style.SUCCESS(f"Backfill done: {total} price records"))

        if options["skip_momentum"]:
            return

        calc_date = timezone.now().date()
        scores = calculator.calculate_momentum_scores_bulk(stocks, calc_date)
        calculator.rank_stocks_by_momentum(calc_date)
        self.stdout.write(
            self.style.SUCCESS(f"Momentum scores computed for {len(scores)} stocks ({calc_date})")
        )
