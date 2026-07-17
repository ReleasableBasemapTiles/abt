"""
boto_configuration.py

This module configures and initializes the boto3 S3 client and defines
reusable transfer configurations for downloading files from AWS S3.

The primary S3 client is set up for anonymous access, which is required
for downloading data from public buckets like Overture Maps without needing
AWS credentials.
"""

import boto3
from botocore import UNSIGNED
from botocore.client import Config
from boto3.s3.transfer import TransferConfig

# Initialize a boto3 S3 client with anonymous access.
# The `signature_version=UNSIGNED` configuration prevents boto3 from
# looking for or sending AWS credentials with requests. This is essential
# for accessing public S3 buckets.
s3 = boto3.client(
    "s3",
    config=Config(signature_version=UNSIGNED)
)

# A transfer configuration designed to force single-part downloads.
# This can be useful for smaller files or in environments where multipart
# downloads are problematic. The multipart_threshold is set to a very large
# value (1 TB) to ensure it is never triggered for typical files.
single_part_config = TransferConfig(
    multipart_threshold=1024**4,  # 1 TB, effectively disabling multipart
    max_concurrency=1,           # No internal threading per file transfer
    use_threads=False            # Explicitly disable threading
)

# A transfer configuration optimized for efficient multipart downloads.
# This is ideal for downloading large files by splitting them into smaller
# chunks and downloading them concurrently, which can significantly speed up
# the process.
multipart_transfer_config = TransferConfig(
    # Start multipart download for files larger than 4KB.
    # A smaller threshold ensures larger files benefit from multipart.
    multipart_threshold=1024*4,
    # Use up to 4 concurrent threads to download parts of a single file.
    max_concurrency=4,
    # Enable the use of threads.
    use_threads=True
)
