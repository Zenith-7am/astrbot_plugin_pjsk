# PJSK AstrBot

This repository will host the platform-independent PJSK score service and its
AstrBot integration. It is currently an engineering scaffold: no bot, OCR,
rating, database, rendering, or gateway behavior has been implemented.

## Architecture boundaries

The core is built inward from stable business rules:

- `pjsk_core.domain` will contain synchronous, I/O-free business rules.
- `pjsk_core.application` will orchestrate use cases through ports.
- `pjsk_core.ports` will define interfaces implemented by outer adapters.

The domain must not import application code, ports, adapters, or plugin code.
That dependency direction is checked by the test suite.

## Development

Python 3.11 or newer is required.

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m pytest
```

