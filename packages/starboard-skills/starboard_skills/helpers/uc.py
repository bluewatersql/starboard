"""Unity Catalog domain helper — fetch UC metadata."""
from starboard_skills.helpers.contract import make_client as _client
from starboard_skills.helpers.contract import raise_api_error


def register(subparsers) -> None:
    p = subparsers.add_parser("uc", help="Unity Catalog operations")
    sp = p.add_subparsers(dest="command", required=True)

    catalogs = sp.add_parser("catalogs", help="List catalogs")
    catalogs.set_defaults(func=cmd_catalogs)

    schemas = sp.add_parser("schemas", help="List schemas in a catalog")
    schemas.add_argument("--catalog", required=True, type=str)
    schemas.set_defaults(func=cmd_schemas)

    tables = sp.add_parser("tables", help="List tables in a schema")
    tables.add_argument("--catalog", required=True, type=str)
    tables.add_argument("--schema", required=True, type=str)
    tables.add_argument("--limit", type=int, default=50)
    tables.set_defaults(func=cmd_tables)

    table_info = sp.add_parser("table", help="Get table details")
    table_info.add_argument("--full-name", required=True, type=str, help="catalog.schema.table")
    table_info.set_defaults(func=cmd_table)

    lineage = sp.add_parser("lineage", help="Get table lineage")
    lineage.add_argument("--full-name", required=True, type=str, help="catalog.schema.table")
    lineage.set_defaults(func=cmd_lineage)


def cmd_catalogs(args):  # noqa: ARG001
    w = _client()
    try:
        cats = list(w.catalogs.list())
        return {
            "catalogs": [
                {
                    "name": c.name,
                    "comment": getattr(c, "comment", None),
                    "owner": getattr(c, "owner", None),
                }
                for c in cats
            ],
            "count": len(cats),
        }
    except Exception as e:
        raise_api_error(e)


def cmd_schemas(args):
    w = _client()
    try:
        schemas = list(w.schemas.list(catalog_name=args.catalog))
        return {
            "catalog": args.catalog,
            "schemas": [
                {
                    "name": s.name,
                    "full_name": s.full_name,
                    "comment": getattr(s, "comment", None),
                    "owner": getattr(s, "owner", None),
                }
                for s in schemas
            ],
            "count": len(schemas),
        }
    except Exception as e:
        raise_api_error(e)


def cmd_tables(args):
    w = _client()
    try:
        tables = list(w.tables.list(catalog_name=args.catalog, schema_name=args.schema))
        tables = tables[:args.limit]
        return {
            "catalog": args.catalog,
            "schema": args.schema,
            "tables": [
                {
                    "name": t.name,
                    "full_name": t.full_name,
                    "table_type": str(getattr(t, "table_type", None)),
                    "data_source_format": str(getattr(t, "data_source_format", None)),
                    "comment": getattr(t, "comment", None),
                    "owner": getattr(t, "owner", None),
                    "row_filter": getattr(t, "row_filter", None),
                }
                for t in tables
            ],
            "count": len(tables),
        }
    except Exception as e:
        raise_api_error(e)


def cmd_table(args):
    w = _client()
    try:
        t = w.tables.get(args.full_name)
        return t.as_dict() if hasattr(t, "as_dict") else {
            "name": t.name,
            "full_name": t.full_name,
            "table_type": str(getattr(t, "table_type", None)),
            "columns": [c.as_dict() if hasattr(c, "as_dict") else vars(c) for c in (getattr(t, "columns", None) or [])],
            "storage_location": getattr(t, "storage_location", None),
            "owner": getattr(t, "owner", None),
            "comment": getattr(t, "comment", None),
            "properties": getattr(t, "properties", None),
        }
    except Exception as e:
        raise_api_error(e, not_found_message=f"Table {args.full_name} not found")


def cmd_lineage(args):
    w = _client()
    try:
        lineage = w.lineage_tracking.table_lineage(table_name=args.full_name)
        return lineage.as_dict() if hasattr(lineage, "as_dict") else {
            "table_name": args.full_name,
            "upstream_tables": [],
            "downstream_tables": [],
        }
    except Exception as e:
        raise_api_error(e)
