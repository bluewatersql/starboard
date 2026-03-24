#!/usr/bin/env python3
"""
Export API Schemas for Contract Testing.

Exports Pydantic models to JSON Schema format for frontend validation.
Part of Option 1: Enhanced API Contract Testing.
"""

import json
from pathlib import Path

from pydantic import BaseModel


def export_schema(model: type[BaseModel], name: str, output_dir: Path) -> None:
    """
    Export a Pydantic model to JSON Schema.

    Args:
        model: Pydantic model class to export
        name: Schema name (filename)
        output_dir: Output directory for schema files
    """
    schema = model.model_json_schema()

    # Add metadata
    schema["$schema"] = "http://json-schema.org/draft-07/schema#"
    schema["$id"] = f"starboard://{name}"

    # Write to file
    output_file = output_dir / f"{name}.json"
    with open(output_file, "w") as f:
        json.dump(schema, f, indent=2)

    print(f"✓ Exported {name} → {output_file}")


def main() -> None:
    """Export all API schemas for contract testing."""
    from starboard_server.api.models import (
        ChatEvent,
        ConversationResponse,
        CreateConversationRequest,
        MessageResponse,
        SendMessageRequest,
        SubmitFeedbackRequest,
    )

    # Determine output directory
    workspace_root = Path(__file__).parent.parent
    output_dir = workspace_root / "tests" / "contract" / "schemas"
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Exporting API schemas to: {output_dir}")
    print("=" * 60)

    # Export core API models
    models = [
        (CreateConversationRequest, "CreateConversationRequest"),
        (ConversationResponse, "ConversationResponse"),
        (SendMessageRequest, "SendMessageRequest"),
        (MessageResponse, "MessageResponse"),
        (SubmitFeedbackRequest, "SubmitFeedbackRequest"),
        (ChatEvent, "ChatEvent"),
    ]

    for model, name in models:
        export_schema(model, name, output_dir)

    print("=" * 60)
    print(f"✓ Exported {len(models)} schemas")
    print("\nNext steps:")
    print("  1. Review schemas in tests/contract/schemas/")
    print("  2. Run backend contract tests: pytest tests/contract/")
    print("  3. Run frontend contract tests: npm run test:contract")


if __name__ == "__main__":
    main()
