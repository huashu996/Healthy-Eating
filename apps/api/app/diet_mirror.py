"""Local-only mirror adapter. No receiver, credential, or network transport."""
def mark_dirty(con):
    return None

def after_commit():
    return None

def status(*, token=None):
    return {'configured': False, 'enabled': False, 'status': 'disabled',
            'reason': 'No hosted mirror is configured. Use the local snapshot exporter.'}

def synchronize(*, token=None, refresh=False, verify_receiver=False):
    return status()

def prepare_platform_sync(*, refresh=False):
    return status()

def acknowledge_platform(ack):
    return status()
