"""FinOps domain helper — fetch Databricks cost and usage data."""
import datetime
import re

from starboard_skills.helpers.contract import ArgError, HelperError, raise_api_error
from starboard_skills.helpers.contract import make_account_client as _account_client
from starboard_skills.helpers.contract import make_client as _client

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_USAGE_SQL = (
    "SELECT billing_origin_product, workspace_id, "
    "ROUND(SUM(usage_quantity), 2) AS total_dbus, COUNT(*) AS records "
    "FROM system.billing.usage "
    "WHERE usage_date >= :start_date AND usage_date <= :end_date "
    "GROUP BY billing_origin_product, workspace_id "
    "ORDER BY total_dbus DESC"
)

_USAGE_SQL_WS = (
    "SELECT billing_origin_product, workspace_id, "
    "ROUND(SUM(usage_quantity), 2) AS total_dbus, COUNT(*) AS records "
    "FROM system.billing.usage "
    "WHERE usage_date >= :start_date AND usage_date <= :end_date "
    "AND workspace_id = :workspace_id "
    "GROUP BY billing_origin_product, workspace_id "
    "ORDER BY total_dbus DESC"
)


def register(subparsers) -> None:
    p = subparsers.add_parser("finops", help="FinOps / cost operations")
    sp = p.add_subparsers(dest="command", required=True)

    usage = sp.add_parser(
        "usage",
        help="Billable DBU-by-product summary from system.billing.usage (read-only)",
    )
    usage.add_argument("--start-date", required=True, type=str, help="YYYY-MM-DD")
    usage.add_argument("--end-date", required=True, type=str, help="YYYY-MM-DD")
    usage.add_argument(
        "--warehouse-id",
        required=True,
        type=str,
        help="SQL warehouse to run on (explicit — never auto-selected)",
    )
    usage.add_argument(
        "--workspace-id",
        required=False,
        default=None,
        type=str,
        help="Filter to a single workspace_id (optional; omit for account-wide results)",
    )
    usage.set_defaults(func=cmd_usage)

    budgets = sp.add_parser("budgets", help="List configured budgets")
    budgets.set_defaults(func=cmd_budgets)

    log_delivery = sp.add_parser("log-delivery", help="List log delivery configs")
    log_delivery.set_defaults(func=cmd_log_delivery)


def cmd_usage(args):
    if not _DATE_RE.match(args.start_date):
        raise ArgError(f"--start-date must be YYYY-MM-DD, got {args.start_date!r}")
    if not _DATE_RE.match(args.end_date):
        raise ArgError(f"--end-date must be YYYY-MM-DD, got {args.end_date!r}")
    try:
        datetime.date.fromisoformat(args.start_date)
    except ValueError as exc:
        raise ArgError(f"--start-date is not a valid calendar date: {args.start_date!r}") from exc
    try:
        datetime.date.fromisoformat(args.end_date)
    except ValueError as exc:
        raise ArgError(f"--end-date is not a valid calendar date: {args.end_date!r}") from exc

    workspace_id: str | None = getattr(args, "workspace_id", None)

    w = _client()
    try:
        from databricks.sdk.service.sql import StatementParameterListItem

        params = [
            StatementParameterListItem(name="start_date", value=args.start_date),
            StatementParameterListItem(name="end_date", value=args.end_date),
        ]
        if workspace_id is not None:
            params.append(StatementParameterListItem(name="workspace_id", value=workspace_id))
            sql = _USAGE_SQL_WS
        else:
            sql = _USAGE_SQL
        resp = w.statement_execution.execute_statement(
            warehouse_id=args.warehouse_id,
            statement=sql,
            parameters=params,
            wait_timeout="50s",
        )
        status = getattr(resp, "status", None)
        state = getattr(status, "state", None)
        state_val = getattr(state, "value", state)
        if state_val != "SUCCEEDED":
            err = getattr(status, "error", None)
            detail = (
                getattr(err, "message", None) or err or "did not finish within the wait window"
            )
            raise_api_error(
                RuntimeError(
                    f"usage query did not complete (state={state_val}): {detail}. "
                    "Narrow the date range or use a larger warehouse."
                )
            )
        manifest = getattr(resp, "manifest", None)
        schema = getattr(manifest, "schema", None) if manifest else None
        columns = [c.name for c in (getattr(schema, "columns", None) or [])]
        result = getattr(resp, "result", None)
        data_array = getattr(result, "data_array", None) if result else None
        rows = [list(r) for r in data_array] if data_array else []
        result_dict: dict = {
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
            "warehouse_id": args.warehouse_id,
            "state": state_val,
            "start_date": args.start_date,
            "end_date": args.end_date,
        }
        if workspace_id is not None:
            result_dict["workspace_id_filter"] = workspace_id
        return result_dict
    except HelperError:
        raise
    except Exception as e:
        raise_api_error(e)


def cmd_budgets(args):  # noqa: ARG001
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
        raise_api_error(e)


def cmd_log_delivery(args):  # noqa: ARG001
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
        raise_api_error(e)
