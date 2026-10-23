"""Vercel Python Function entry point for the Django WSGI application."""
from payroll_project.wsgi import application

# Vercel's Python runtime discovers this module and serves the WSGI callable.
