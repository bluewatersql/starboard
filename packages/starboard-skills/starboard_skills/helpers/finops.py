"""FinOps domain helper — fetch Databricks cost and usage data."""
import sys


def register(subparsers) -> None:
    p = subparsers.add_parser("finops", help="FinOps / cost operations")
    sp = p.add_subparsers(dest="command", required=True)

    usage = sp.add_parser("usage", help="Fetch billable usage summary")
    usage.add_argument("--start-date", required=True, type=str, help="YYYY-MM-DD")
    usage.add_argument("--end-date", required=True, type=str, help="YYYY-MM-DD")
    usage.set_defaults(func=cmd_usage)

    budgets = sp.add_parser("budgets", help="List configured budgets")
    budgets.set_defaults(func=cmd_budgets)

    log_delivery = sp.add_parser("log-delivery", help="List log delivery configs")
    log_delivery.set_defaults(func=cmd_log_delivery)


def _account_client():
    try:
        from databricks.sdk import AccountClient
        return AccountClient()
    except Exception as e:
        print(f"Authentication error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_usage(args):
    a = _account_client()
    try:
        logs = list(a.billable_usage.download(
            start_month=args.start_date[:7],
            end_month=args.end_date[:7],
        ))
        return {
            "start_date": args.start_date,
            "end_date": args.end_date,
            "usage_records": [r.as_dict() if hasattr(r, "as_dict") else str(r) for r in logs],
            "count": len(logs),
        }
    except Exception as e:
        print(f"API error: {e}", file=sys.stderr)
        sys.exit(3)


def cmd_budgets(args):
    a = _account_client()
    try:
        budgets = list(a.budgets.list())
        return {
            "budgets": [
                {
                    "budget_id": getattr(b, "budget_id", None),
                    "name": getattr(b, "name", None),
                    "period": str(getattr(b, "period", None)),
                    "target_amount": getattr(b, "target_amount", None),
                    "filter": getattr(b, "filter", None),
                    "alerts": [a.as_dict() if hasattr(a, "as_dict") else vars(a) for a in (getattr(b, "alerts", None) or [])],
                }
                for b in budgets
            ],
            "count": len(budgets),
        }
    except Exception as e:
        print(f"API error: {e}", file=sys.stderr)
        sys.exit(3)


def cmd_log_delivery(args):
    a = _account_client()
    try:
        configs = list(a.log_delivery.list())
        return {
            "log_delivery_configs": [
                c.as_dict() if hasattr(c, "as_dict") else {
                    "config_id": getattr(c, "config_id", None),
                    "config_name": getattr(c, "config_name", None),
                    "log_type": str(getattr(c, "log_type", None)),
                    "status": str(getattr(c, "status", None)),
                }
                for c in configs
            ],
            "count": len(configs),
        }
    except Exception as e:
        print(f"API error: {e}", file=sys.stderr)
        sys.exit(3)
