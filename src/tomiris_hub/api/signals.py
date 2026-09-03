from __future__ import annotations

import logging
from uuid import uuid4

from fastapi import APIRouter, Request
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.exc import SQLAlchemyError

from tomiris_hub.core.errors import AuthenticationError, HubError, ValidationError
from tomiris_hub.schemas.signals import SignalEnvelope
from tomiris_hub.services.authentication import AuthHeaders

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1", tags=["signals"])

_HEADER_NAMES = {
    "agent_id": "X-Tomiris-Agent-ID",
    "timestamp": "X-Tomiris-Timestamp",
    "nonce": "X-Tomiris-Nonce",
    "key_id": "X-Tomiris-Key-ID",
    "signature": "X-Tomiris-Signature",
}


@router.post("/signals", status_code=202)
async def ingest_signal(request: Request) -> dict[str, str]:
    request_id = uuid4()
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > request.app.state.settings.max_signal_request_bytes:
        return await _reject(
            request, request_id, b"", None, ValidationError("REQUEST_TOO_LARGE", 413)
        )
    body = await request.body()
    agent_claim = request.headers.get(_HEADER_NAMES["agent_id"])
    if len(body) > request.app.state.settings.max_signal_request_bytes:
        return await _reject(
            request, request_id, body, agent_claim, ValidationError("REQUEST_TOO_LARGE", 413)
        )
    try:
        values = {key: request.headers.get(header) for key, header in _HEADER_NAMES.items()}
        if any(value is None for value in values.values()):
            raise AuthenticationError("MISSING_AUTH_HEADERS", 401)
        auth = AuthHeaders(**values)  # type: ignore[arg-type]
        request.app.state.authenticator.verify(request.method, request.url.path, auth, body)
        envelope = SignalEnvelope.model_validate_json(body)
        if envelope.agent_id != auth.agent_id:
            raise ValidationError("AGENT_ID_MISMATCH", 403)
        async with request.app.state.session_factory() as session:
            await request.app.state.ingestion.ingest(
                session, envelope, auth.nonce, body, request_id
            )
        return {
            "status": "ACCEPTED",
            "request_id": str(request_id),
            "message_id": str(envelope.message_id),
        }
    except PydanticValidationError:
        return await _reject(
            request, request_id, body, agent_claim, ValidationError("INVALID_SCHEMA", 422)
        )
    except HubError as error:
        return await _reject(request, request_id, body, agent_claim, error)
    except SQLAlchemyError:
        return await _reject(
            request,
            request_id,
            body,
            agent_claim,
            ValidationError("DATABASE_UNAVAILABLE", 503),
        )


async def _reject(
    request: Request, request_id: object, body: bytes, agent_id: str | None, error: HubError
) -> dict[str, str]:
    logger.warning(
        "signal_rejected", extra={"reason_code": error.code, "request_id": str(request_id)}
    )
    try:
        async with request.app.state.session_factory() as session:
            await request.app.state.ingestion.record_rejection(
                session, request_id, error.code, body, agent_id
            )
    except SQLAlchemyError:
        logger.error("rejection_audit_unavailable", extra={"request_id": str(request_id)})
    from fastapi import HTTPException

    raise HTTPException(
        status_code=error.status_code, detail={"code": error.code, "request_id": str(request_id)}
    )
