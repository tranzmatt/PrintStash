"""Configuration builders shared by preset API, transport and workflow contracts.

They build configuration values, not database entities. Network service setup is
explicit and used only by contract/E2E callers.
"""

from __future__ import annotations

from uuid import uuid4

from app.modules.storage.storage_providers import PRESETS


def preset_configuration(provider: str, root: str = "presets") -> dict[str, object]:
    transport = PRESETS[provider]["transport"]
    options = {
        "local": {"data_dir": "/tmp/preset-models", "thumb_dir": "/tmp/preset-thumbs"},
        "s3": {
            "bucket": "models",
            "endpoint_url": "https://s3.example.test",
            "access_key": "test-access",
            "secret_key": "test-secret",
        },
        "webdav": {
            "endpoint_url": "https://dav.example.test",
            "username": "test-user",
            "password": "test-password",
        },
        "sftp": {
            "host": "sftp.example.test",
            "username": "test-user",
            "password": "test-password",
            "host_key": "/run/known_hosts",
        },
    }
    return {"provider": provider, "root": root, **options[transport]}


def real_preset_configuration(provider: str) -> dict[str, object]:
    """Point a named remote preset at the pinned real transport test service."""
    from tests.containers import (
        S3_ACCESS_KEY,
        S3_SECRET_KEY,
        nextcloud_endpoint,
        openssh_endpoint,
        s3_endpoint,
    )

    configuration = preset_configuration(provider, f"preset-{uuid4().hex}")
    transport = PRESETS[provider]["transport"]
    if transport == "s3":
        import boto3
        from botocore.config import Config

        endpoint = s3_endpoint()
        bucket = f"presets-{uuid4().hex[:12]}"
        boto3.client(
            "s3",
            endpoint_url=endpoint,
            region_name="us-east-1",
            aws_access_key_id=S3_ACCESS_KEY,
            aws_secret_access_key=S3_SECRET_KEY,
            config=Config(s3={"addressing_style": "path"}),
        ).create_bucket(Bucket=bucket)
        configuration.update(
            endpoint_url=endpoint,
            bucket=bucket,
            region="us-east-1",
            access_key=S3_ACCESS_KEY,
            secret_key=S3_SECRET_KEY,
        )
    elif transport == "webdav":
        configuration.update(
            endpoint_url=f"{nextcloud_endpoint()}/remote.php/dav/files/admin",
            username="admin",
            password="contract-only",
        )
    elif transport == "sftp":
        host, port, host_key = openssh_endpoint()
        configuration.update(
            host=host,
            port=port,
            host_key=host_key,
            username="contract",
            password="contract-only",
        )
    else:
        raise ValueError("mounted presets use the local filesystem fixture")
    return configuration
