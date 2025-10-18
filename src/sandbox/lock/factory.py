from typing import Optional, Callable, Awaitable
from uuid import uuid4
from google.cloud import storage

from .interface import LockInterface
from .gcs import GCSLock
from .fake import FakeLock

class LockFactory:
    def __init__(self, gcs_bucket_name: Optional[str] = None, client: Optional[storage.Client] = None):
        if gcs_bucket_name:
            self._client = client or storage.Client()
            self._bucket = self._client.bucket(gcs_bucket_name)
        else:
            self._bucket = None

    def create_lock(
        self,
        sandbox_id: str,
        blob_name: str,
        on_release_requested: Optional[Callable[[str], Awaitable[None]]] = None,
        on_renewal_error: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> LockInterface:
        owner_id = str(uuid4())
        if self._bucket:
            return GCSLock(
                bucket=self._bucket,
                blob_name=blob_name,
                owner_id=owner_id,
                on_release_requested=on_release_requested,
                on_renewal_error=on_renewal_error,
            )
        else:
            # Return a fake lock if GCS is not configured
            return FakeLock(
                lock_id=sandbox_id,
                owner_id=owner_id,
                on_release_requested=on_release_requested,
                on_renewal_error=on_renewal_error,
            )
