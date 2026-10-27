"""Private HR storage configuration. Credentials use the AWS SDK credential chain."""
from django.core.exceptions import ImproperlyConfigured
from .env import env, require_env


def private_document_storage(base_dir):
    backend = env("DJANGO_DOCUMENT_STORAGE", "filesystem").strip().lower()
    if backend == "filesystem":
        root = env("DJANGO_PRIVATE_DOCUMENT_ROOT", "").strip() or str(base_dir / "private_documents")
        return {"BACKEND": "django.core.files.storage.FileSystemStorage",
                "OPTIONS": {"location": root, "base_url": None}}
    if backend != "s3":
        raise ImproperlyConfigured("DJANGO_DOCUMENT_STORAGE must be filesystem or s3.")
    return {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "bucket_name": require_env("DJANGO_DOCUMENT_BUCKET"),
            "region_name": require_env("DJANGO_DOCUMENT_REGION"),
            "default_acl": None,
            "querystring_auth": True,
            "querystring_expire": 60,
            "signature_version": "s3v4",
            "use_ssl": True,
            "verify": True,
            "custom_domain": None,
            "file_overwrite": False,
            "location": "hr-documents",
            "max_memory_size": 1024 * 1024,
            "object_parameters": {"ServerSideEncryption": "aws:kms",
                                  "SSEKMSKeyId": require_env("DJANGO_DOCUMENT_KMS_KEY_ID"),
                                  "CacheControl": "private, no-store"},
        },
    }
