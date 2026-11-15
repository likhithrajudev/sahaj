"""Who is connected right now, so a case can be relayed live: the customer's open conversations and the executives
watching the desk. In memory, per process (run one worker, or put a pub/sub such as Redis behind these two functions).
When the customer is not connected, nothing is lost: every message is stored on the case and shown when they come back."""
import logging
from typing import Dict, Set

log = logging.getLogger("sahaj.desk")

customers: Dict[str, Set] = {}   # user id -> their live Session objects (user ids are unique across tenants)
executives: Dict[str, Dict[str, Set]] = {}  # tenant -> executive id -> their desk WebSockets


def join_customer(user_id: str, session) -> None:
    customers.setdefault(user_id, set()).add(session)


def leave_customer(user_id: str, session) -> None:
    customers.get(user_id, set()).discard(session)
    if not customers.get(user_id):
        customers.pop(user_id, None)


def online(user_id: str) -> bool:
    return bool(customers.get(user_id))


async def to_customer(user_id: str, event: dict) -> int:
    """Send to every conversation the person has open; let each session react (for example leave human mode).
    Returns how many received it."""
    sent = 0
    for session in list(customers.get(user_id, ())):
        try:
            await session.on_desk_event(event)
            sent += 1
        except Exception as e:   # one dead connection must not stop the others
            log.debug("Could not reach a customer session: %s", e)
    return sent


def join_executive(tenant: str, executive_id: str, ws) -> None:
    executives.setdefault(tenant, {}).setdefault(executive_id, set()).add(ws)


def leave_executive(tenant: str, executive_id: str, ws) -> None:
    executives.get(tenant, {}).get(executive_id, set()).discard(ws)


async def to_executives(event: dict, only: str = None, tenant: str = None) -> None:
    """Send to the executives of one tenant only (the caller's, by default): another tenant's desk never sees it."""
    import tenancy
    tenant = tenant or tenancy.get()
    if not tenant:
        return
    targets = [ws for exec_id, sockets in list(executives.get(tenant, {}).items()) if only is None or exec_id == only
               for ws in list(sockets)]
    for ws in targets:
        try:
            await ws.send_json(event)
        except Exception as e:
            log.debug("Could not reach an executive: %s", e)
