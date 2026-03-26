# starboard-sdk

Thin SDK for notebook and programmatic use.

## Key Modules
- `client.py` -- StarboardClient factory and ConversationSession
- `events.py` -- Event type re-exports (facade over server events)
- `event_types.py` -- Event type definitions
- `exceptions.py` -- StarboardError hierarchy
- `models.py` -- AgentResponse dataclass
- `_event_mapper.py` -- Internal event mapping logic
