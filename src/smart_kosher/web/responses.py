"""Uniform JSON response factories for all API routes."""


def ok(data=None, status=200):
    return {"ok": True, "data": data}, status


def err(message, status=400):
    return {"ok": False, "error": message}, status


def not_found(message="not found"):
    return err(message, 404)
