# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

from __future__ import annotations


class CloudStorageMissingError(Exception):
    pass


class BackingCSMigrationConflictError(Exception):
    """
    Raised when a backing cloud storage migration cannot be started because
    an incompatible migration (e.g. in the opposite direction) is in progress.
    """

    pass
