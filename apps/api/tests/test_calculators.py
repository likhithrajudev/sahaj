"""Authenticated public loan calculators use the same exact arithmetic as text chat."""
import asyncio
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from auth.deps import current_user
from auth.store import User
from main import app

USER = User(id="11111111-1111-1111-1111-111111111111", email="a@example.com", name="Asha", picture=None,
            language="en-IN", platform="web", role="user")


def test_emi_and_prepayment_calculator_endpoints():
    async def run():
        previous = app.dependency_overrides.get(current_user)
        app.dependency_overrides[current_user] = lambda: USER
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                emi = await client.post("/calculators/emi", json={
                    "principal": 500_000, "annual_rate_percent": 11, "tenure_months": 36,
                })
                assert emi.status_code == 200
                assert emi.json()["result"] == {"emi": 16369, "total_payment": 589297, "total_interest": 89297}
                assert emi.json()["method"] == "reducing_balance"

                prepayment = await client.post("/calculators/prepayment", json={
                    "principal": 500_000, "annual_rate_percent": 11, "tenure_months": 36, "prepay_amount": 100_000,
                })
                assert prepayment.status_code == 200 and prepayment.json()["kind"] == "prepayment"
                assert prepayment.json()["result"]["interest_saved"] > 0

                invalid = await client.post("/calculators/prepayment", json={
                    "principal": 500_000, "annual_rate_percent": 11, "tenure_months": 36, "prepay_amount": 500_000,
                })
                assert invalid.status_code == 422
        finally:
            if previous is None:
                app.dependency_overrides.pop(current_user, None)
            else:
                app.dependency_overrides[current_user] = previous

    asyncio.run(run())
