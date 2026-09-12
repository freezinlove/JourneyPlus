"""Shared normalization for catalog lookup and identity binding."""
import unicodedata


def canonical(value):
    return ' '.join(unicodedata.normalize('NFKC', value).casefold().split())
