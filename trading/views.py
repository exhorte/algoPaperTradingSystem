import logging
import statistics
from datetime import date

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from portfolio.models import Portfolio
from trading.models import MomentumScore, PriceData, RebalanceEvent, TradingSignal

logger = logging.getLogger(__name__)


def _latest_calculation_date():
    return (
        MomentumScore.objects.order_by("-calculation_date")
        .values_list("calculation_date", flat=True)
        .first()
    )


def dashboard(request):
    calc_date = _latest_calculation_date()
    scores = (
        MomentumScore.objects.filter(calculation_date=calc_date)
        .select_related("stock")
        .order_by("rank", "-momentum_score")
        if calc_date
        else MomentumScore.objects.none()
    )
    values = [float(s.momentum_score) for s in scores]
    active_portfolios = Portfolio.objects.filter(is_active=True)

    context = {
        "calc_date": calc_date,
        "top_stocks": scores[:10],
        "bottom_stocks": list(scores.order_by("-rank", "momentum_score")[:10]),
        "stats": {
            "total_stocks": len(values),
            "mean_momentum": statistics.fmean(values) if values else None,
            "median_momentum": statistics.median(values) if values else None,
        },
        "rebalance_events": RebalanceEvent.objects.order_by("-date", "-created_at")[:10],
        "active_portfolios": active_portfolios,
        "today": date.today(),
    }
    return render(request, "trading/dashboard.html", context)


def momentum_scores(request):
    dates = list(
        MomentumScore.objects.order_by("-calculation_date")
        .values_list("calculation_date", flat=True)
        .distinct()
    )
    selected = request.GET.get("date")
    calc_date = None
    if selected:
        try:
            calc_date = date.fromisoformat(selected)
        except ValueError:
            calc_date = None
    if calc_date is None and dates:
        calc_date = dates[0]

    scores = (
        MomentumScore.objects.filter(calculation_date=calc_date)
        .select_related("stock")
        .order_by("rank", "-momentum_score")
    )
    context = {
        "dates": dates,
        "calc_date": calc_date,
        "scores": scores,
        "total_stocks": scores.count(),
        "top_quintile_count": scores.filter(is_top_quintile=True).count(),
    }
    return render(request, "trading/momentum_scores.html", context)


def trading_signals(request):
    signal_type = request.GET.get("type", "").upper()
    signals = TradingSignal.objects.select_related("stock", "momentum_score")
    all_signals = signals
    if signal_type in ("BUY", "SELL", "HOLD"):
        signals = signals.filter(signal_type=signal_type)

    signals = list(signals[:200])
    # Latest known close per stock, for the Price column
    latest_close = {}
    for price in PriceData.objects.filter(
        stock__in={s.stock_id for s in signals}
    ).order_by("stock_id", "-date"):
        latest_close.setdefault(price.stock_id, price.close)
    for signal in signals:
        signal.price = latest_close.get(signal.stock_id)

    context = {
        "signals": signals,
        "signal_type": signal_type,
        "total_count": all_signals.count(),
        "buy_count": all_signals.filter(signal_type="BUY").count(),
        "sell_count": all_signals.filter(signal_type="SELL").count(),
    }
    return render(request, "trading/trading_signals.html", context)


@require_POST
def recalculate_momentum(request):
    from trading.services.momentum_calculator import get_momentum_calculator

    try:
        calculator = get_momentum_calculator()
        stocks = calculator.update_stock_universe()
        calc_date = date.today()
        scores = calculator.calculate_momentum_scores_bulk(stocks, calc_date)
        calculator.rank_stocks_by_momentum(calc_date)
    except Exception as e:
        logger.exception("Momentum recalculation failed")
        return JsonResponse({"success": False, "error": str(e)}, status=500)

    return JsonResponse(
        {
            "success": True,
            "count": len(scores),
            "message": f"Successfully recalculated momentum scores for {len(scores)} stocks",
        }
    )


@require_POST
def generate_signals(request):
    from trading.services.strategy_engine import get_strategy_engine

    calc_date = _latest_calculation_date()
    if calc_date is None:
        return JsonResponse(
            {
                "success": False,
                "error": "No momentum data available. Recalculate momentum first.",
            },
            status=400,
        )

    try:
        portfolio = Portfolio.objects.filter(is_active=True).first()
        strategy = get_strategy_engine(portfolio)
        buy_signals, sell_signals = strategy.generate_trading_signals(calc_date)
    except Exception as e:
        logger.exception("Signal generation failed")
        return JsonResponse({"success": False, "error": str(e)}, status=500)

    return JsonResponse(
        {
            "success": True,
            "message": (
                f"Generated {len(buy_signals)} buy signals and "
                f"{len(sell_signals)} sell signals"
            ),
        }
    )
