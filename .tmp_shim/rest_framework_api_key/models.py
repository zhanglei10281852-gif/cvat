from django.db import models


class BaseAPIKeyManager(models.Manager):
    pass


class AbstractAPIKey(models.Model):
    class Meta:
        abstract = True


class APIKey(AbstractAPIKey):
    pass
