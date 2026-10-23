"""Shared portable-format caps and conservative transfer disk reservations."""

MAX_MEDIA_BYTES = 512 * 1024 * 1024
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_ARCHIVE_BYTES = MAX_MEDIA_BYTES + MAX_MANIFEST_BYTES
MAX_REBUILT_METADATA_BYTES = 8 * 1024 * 1024

# Upload + extracted media + remapped media + bounded metadata/control records.
IMPORT_PEAK_BYTES = (
    MAX_ARCHIVE_BYTES
    + 2 * MAX_MEDIA_BYTES
    + MAX_REBUILT_METADATA_BYTES
    + MAX_MANIFEST_BYTES
)
# Frozen media + growing archive + the API's frozen project/request record.
EXPORT_PEAK_BYTES = MAX_MEDIA_BYTES + MAX_ARCHIVE_BYTES + MAX_MANIFEST_BYTES
