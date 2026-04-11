"""Lumina microservice packages.

Each sub-package represents an independently runnable service boundary.
In development all services are mounted on the gateway (``lumina.api.server``).
In production each can be launched as its own ``uvicorn`` process.
"""
