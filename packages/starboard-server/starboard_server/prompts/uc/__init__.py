"""Unity Catalog (UC) domain prompts package.

The UC agent replaces the deprecated "table" agent with extended capabilities
for data governance, lineage analysis, schema intelligence, access control,
and storage optimization.
"""

from .v1 import PROMPT_VERSION, UC_SYSTEM_PROMPT

__all__ = ["PROMPT_VERSION", "UC_SYSTEM_PROMPT"]
