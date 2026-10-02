class DefaultAccountAdapter:
    pass


def get_adapter(*args, **kwargs):
    return DefaultAccountAdapter()
