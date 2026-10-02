### Fixed

- Cloud storage manifest refreshes are now published as complete, versioned generations: browsing tokens, cloud storage previews and task file selection are bound to the same manifest generation, so paging after a remote manifest replacement can no longer mix files from different versions.
- A failed remote manifest download or parsing no longer exposes a half-written file, concurrent refreshes converge to a single complete version and can be safely retried.
- Removing a manifest from the cloud storage settings now drops its local snapshot copies and invalidates the corresponding preview cache entry.
