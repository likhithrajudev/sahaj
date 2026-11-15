"""Every table the app creates at startup, for tests that run against a real Postgres."""


async def init_all() -> None:
    from auth import feedback, store
    from desk import store as desk
    from financial import inventory
    from marketing import store as marketing
    from memory import episodic, procedural, semantic
    from storage import files, index
    from usage import ledger
    for init in (store.init_schema, files.init_schema, feedback.init_schema, index.init_schema, ledger.init_schema,
                 desk.init_schema, inventory.init_schema, episodic.init_schema, semantic.init_schema, procedural.init_schema, marketing.init_schema):
        await init()
