from agents.base import Agent
from agents.insurance import insurance
from agents.loan import loan

# Greets and explains what Sahaj can do. It has no documents, so it can state no facts.
general = Agent(
    name="general",
    role="front desk. You greet the user and say briefly what Sahaj can do: explain insurance policies and loan offers, compare insurance plans, recommend insurance after asking about their needs, work out a loan EMI or the interest saved by prepaying, and connect them to a person. Then ask what they need",
    domain=None,
)

AGENTS = {agent.name: agent for agent in (insurance, loan, general)}
