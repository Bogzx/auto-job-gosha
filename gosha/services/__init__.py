"""Service layer (use cases): business rules + transactions.

Services own database access and raise gosha.domain.errors exceptions.
They know nothing about HTTP or Discord — the api/ and bot adapters call
them and translate results/errors for their medium.
"""
