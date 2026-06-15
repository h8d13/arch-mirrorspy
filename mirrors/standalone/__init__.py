"""Django-free reimplementation of the mirrors JSON API.

Reads the same SQLite schema as the Django app (table names match
Django's `mirrors_*` convention) and serves the three public JSON
endpoints with no Django, django_countries, or main.utils dependency.
"""
