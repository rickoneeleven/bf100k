"""
repositories/__init__.py

Package initialization for repository classes.
Exposes repository implementations to make imports cleaner.
"""

from src.repositories.account_repository import AccountRepository
from src.repositories.bet_repository import BetRepository

# This makes the classes available as:
# from src.repositories import AccountRepository, BetRepository
# Instead of:
# from src.repositories.account_repository import AccountRepository
# from src.repositories.bet_repository import BetRepository