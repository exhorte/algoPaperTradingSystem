import logging
from decimal import Decimal

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.crypto import get_random_string
from django.views.decorators.http import require_POST

from portfolio.models import Portfolio

logger = logging.getLogger(__name__)

# Session key holding the portfolio being created while the user is on SnapTrade
PENDING_KEY = "pending_portfolio"


def portfolio_list(request):
    portfolios = Portfolio.objects.prefetch_related("positions")
    return render(request, "portfolio/portfolio_list.html", {"portfolios": portfolios})


def portfolio_detail(request, pk):
    portfolio = get_object_or_404(Portfolio, pk=pk)
    context = {
        "portfolio": portfolio,
        "positions": portfolio.get_current_positions(),
        "trades": portfolio.trades.select_related("stock")[:50],
        "is_connected": bool(
            portfolio.snaptrade_user_id and portfolio.snaptrade_account_id
        ),
    }
    return render(request, "portfolio/portfolio_detail.html", context)


def portfolio_create(request):
    """Steps 1 (details) and 2 (connect brokerage) of the creation wizard."""
    form = {"name": "", "description": ""}

    if request.method == "POST":
        form = {
            "name": request.POST.get("name", "").strip(),
            "description": request.POST.get("description", "").strip(),
        }
        if not form["name"]:
            messages.error(request, "Portfolio name is required.")
        elif Portfolio.objects.filter(name=form["name"]).exists():
            messages.error(request, "A portfolio with this name already exists.")
        else:
            from trading.services.snaptrade_client import get_trading_executor

            try:
                executor = get_trading_executor()
                user_id, user_secret = executor.register_user(
                    f"momentum-{get_random_string(12).lower()}"
                )
                portal_url = executor.get_connection_portal_url(
                    user_id,
                    user_secret,
                    redirect_url=request.build_absolute_uri(
                        reverse("portfolio:create_callback")
                    ),
                )
            except Exception as e:
                logger.exception("SnapTrade connection failed")
                messages.error(request, f"SnapTrade connection failed: {e}")
            else:
                request.session[PENDING_KEY] = {
                    **form,
                    "user_id": user_id,
                    "user_secret": user_secret,
                }
                return redirect(portal_url)

    return render(request, "portfolio/portfolio_create.html", {"form": form})


def portfolio_create_callback(request):
    """Step 3: back from SnapTrade, pick the account and confirm."""
    pending = request.session.get(PENDING_KEY)
    if not pending:
        messages.error(request, "No portfolio creation in progress.")
        return redirect("portfolio:create")

    from trading.services.snaptrade_client import get_trading_executor

    accounts = []
    try:
        accounts = get_trading_executor().list_accounts(
            pending["user_id"], pending["user_secret"]
        )
    except Exception as e:
        logger.exception("Could not list SnapTrade accounts")
        messages.error(request, f"Could not load brokerage accounts: {e}")

    accounts = [
        {
            "id": str(acc.get("id")),
            "name": acc.get("name") or acc.get("number") or acc.get("id"),
            "institution": acc.get("institution_name", ""),
            "number": acc.get("number", ""),
        }
        for acc in accounts
    ]
    return render(
        request,
        "portfolio/portfolio_review.html",
        {"pending": pending, "accounts": accounts},
    )


@require_POST
def portfolio_create_finish(request):
    pending = request.session.get(PENDING_KEY)
    account_id = request.POST.get("account_id", "")
    if not pending or not account_id:
        messages.error(request, "Select a brokerage account to continue.")
        return redirect("portfolio:create_callback" if pending else "portfolio:create")

    portfolio = Portfolio.objects.create(
        name=pending["name"],
        description=pending["description"],
        initial_cash=Decimal("0"),
        current_cash=Decimal("0"),
        snaptrade_user_id=pending["user_id"],
        snaptrade_user_secret=pending["user_secret"],
        snaptrade_account_id=account_id,
    )
    del request.session[PENDING_KEY]

    if _sync(request, portfolio):
        portfolio.initial_cash = portfolio.total_value
        portfolio.save(update_fields=["initial_cash"])
    messages.success(request, f"Portfolio '{portfolio.name}' created.")
    return redirect("portfolio:detail", pk=portfolio.pk)


@require_POST
def portfolio_sync(request, pk):
    portfolio = get_object_or_404(Portfolio, pk=pk)
    if _sync(request, portfolio):
        messages.success(request, "Positions and cash synchronized from the brokerage.")
    return redirect("portfolio:detail", pk=pk)


@require_POST
def portfolio_rebalance(request, pk):
    portfolio = get_object_or_404(Portfolio, pk=pk)
    from trading.services.strategy_engine import get_strategy_engine

    try:
        event = get_strategy_engine(portfolio).execute_rebalance()
    except Exception as e:
        logger.exception("Rebalance failed")
        messages.error(request, f"Rebalance failed: {e}")
    else:
        messages.success(
            request,
            f"Rebalance completed: {event.buy_signals_generated} buys, "
            f"{event.sell_signals_generated} sells.",
        )
    return redirect("portfolio:detail", pk=pk)


def _sync(request, portfolio) -> bool:
    from trading.services.snaptrade_client import get_trading_executor

    try:
        get_trading_executor().sync_portfolio_positions(portfolio)
        return True
    except Exception as e:
        logger.exception("Portfolio sync failed")
        messages.warning(request, f"Could not sync with the brokerage: {e}")
        return False
