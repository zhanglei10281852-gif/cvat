class DirtyFieldsMixin:
    def is_dirty(self, *args, **kwargs):
        return False

    def save_dirty_fields(self, *args, **kwargs):
        return []
