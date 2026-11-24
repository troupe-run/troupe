"""What test_openai_library.py and test_openai_library_unit.py share."""

LIBRARY_VARIABLES = {
    "OPENAI_API_KEY": "sk-from-the-environment",
    "OPENAI_ADMIN_KEY": "sk-admin-from-the-environment",
    "OPENAI_BASE_URL": "http://127.0.0.1:9/v1",
    "OPENAI_ORG_ID": "org-from-the-environment",
    "OPENAI_PROJECT_ID": "proj-from-the-environment",
    "OPENAI_CUSTOM_HEADERS": "X-From-The-Environment: yes\nAuthorization: Bearer sk-custom",
}
"""Every variable the openai package reads when it isn't given what it names."""
