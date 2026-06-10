"""Scraper plugin architecture: one adapter per job board.

Each adapter turns (keyword, location) into a list of RawJob records that
feed the same upsert path as JobSpy results. Adapters must never raise out
of search() — a broken source logs and returns [] so the cycle continues.
"""
