"""AWS Lambda entrypoint.

Mangum wraps the FastAPI app so it can run inside a Lambda Function URL.
The Lambda receives HTTP events, Mangum translates them to ASGI, FastAPI
handles them, Mangum translates the response back to Lambda format.

lifespan="off" because Lambda manages its own lifecycle.
The DB pool is initialised lazily on first request (see deps.py).
"""
from mangum import Mangum

from vyom.api.app import app

handler = Mangum(app, lifespan="off")