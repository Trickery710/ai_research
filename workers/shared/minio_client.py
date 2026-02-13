"""MinIO object storage client for document content."""
import io
from minio import Minio
from shared.config import Config

_client = None


def get_minio():
    """Lazily initialize MinIO client and ensure bucket exists."""
    global _client
    if _client is None:
        _client = Minio(
            Config.MINIO_ENDPOINT,
            access_key=Config.MINIO_ACCESS_KEY,
            secret_key=Config.MINIO_SECRET_KEY,
            secure=False
        )
        if not _client.bucket_exists(Config.MINIO_BUCKET):
            _client.make_bucket(Config.MINIO_BUCKET)
    return _client


def store_content(key, content, content_type="text/plain"):
    """Store text content as a MinIO object.

    Args:
        key: Object key (e.g. "raw/{doc_id}").
        content: Text string to store.
        content_type: MIME type.

    Returns:
        str: The object key.
    """
    client = get_minio()
    data = content.encode("utf-8")
    client.put_object(
        Config.MINIO_BUCKET,
        key,
        io.BytesIO(data),
        length=len(data),
        content_type=content_type
    )
    return key


def store_bytes(key, data, content_type="application/octet-stream"):
    """Store binary content as a MinIO object.

    Args:
        key: Object key.
        data: Bytes to store.
        content_type: MIME type.

    Returns:
        str: The object key.
    """
    client = get_minio()
    client.put_object(
        Config.MINIO_BUCKET,
        key,
        io.BytesIO(data),
        length=len(data),
        content_type=content_type
    )
    return key


def get_content(key):
    """Retrieve text content from MinIO.

    Args:
        key: Object key.

    Returns:
        str: The decoded UTF-8 text content.
    """
    client = get_minio()
    response = client.get_object(Config.MINIO_BUCKET, key)
    try:
        return response.read().decode("utf-8")
    finally:
        response.close()
        response.release_conn()


def get_bytes(key):
    """Retrieve binary content from MinIO.

    Args:
        key: Object key.

    Returns:
        bytes: The raw bytes.
    """
    client = get_minio()
    response = client.get_object(Config.MINIO_BUCKET, key)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()
