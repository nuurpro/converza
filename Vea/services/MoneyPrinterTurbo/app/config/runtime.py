"""Server-only environment overrides for the approved campaign renderer."""
import os


def apply_runtime_environment(settings, environ=None):
    environ = os.environ if environ is None else environ
    key = environ.get('PEXELS_API_KEY', '').strip()
    if key:
        settings['pexels_api_keys'] = [key]
    approved_only = environ.get('MPT_APPROVED_ONLY', '').strip().lower() in ('1', 'true', 'yes')
    settings['approved_only'] = approved_only
    if approved_only:
        settings['llm_provider'] = 'disabled'
        settings['upload_post_enabled'] = False
        settings['upload_post_auto_upload'] = False
    return settings
