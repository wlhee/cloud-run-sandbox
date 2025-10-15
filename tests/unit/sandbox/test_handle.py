import unittest
from unittest.mock import MagicMock
import json
import tempfile
import os
import time

from src.sandbox.handle import SandboxHandle, GCSArtifact, GCSSandboxMetadata
from src.sandbox.config import GCSConfig
from src.sandbox.interface import SandboxCreationError, SandboxRestoreError


class TestSandboxHandleFactories(unittest.TestCase):
    def test_create_ephemeral_handle(self):
        """
        Tests the `create_ephemeral` factory for a basic, in-memory handle.
        """
        mock_instance = MagicMock()
        
        handle = SandboxHandle.create_ephemeral(
            sandbox_id="ephemeral-sandbox",
            instance=mock_instance,
            idle_timeout=120,
        )

        self.assertEqual(handle.sandbox_id, "ephemeral-sandbox")
        self.assertIs(handle.instance, mock_instance)
        self.assertEqual(handle.idle_timeout, 120)
        self.assertIsNone(handle.gcs_config)
        self.assertIsNone(handle.gcs_metadata)

    def test_create_ephemeral_handle_with_gcs_config_for_snapshotting(self):
        """
        Tests that an ephemeral handle can be created with a GCSConfig for snapshotting.
        """
        mock_instance = MagicMock()
        gcs_config = GCSConfig(filesystem_snapshot_mount_path="/mnt/snapshots")

        handle = SandboxHandle.create_ephemeral(
            sandbox_id="snapshot-sandbox",
            instance=mock_instance,
            idle_timeout=120,
            gcs_config=gcs_config,
        )

        self.assertIs(handle.gcs_config, gcs_config)
        self.assertIsNone(handle.gcs_metadata) # Still not persistent
        self.assertEqual(
            handle.filesystem_snapshot_file_path("my-snapshot"),
            "/mnt/snapshots/filesystem_snapshots/my-snapshot/my-snapshot.tar"
        )

    def test_create_persistent_handle_success_with_temp_dir(self):
        """
        Tests the `create_persistent` factory using a real temporary directory
        to verify file and directory creation.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            mock_instance = MagicMock()
            gcs_config = GCSConfig(
                metadata_mount_path=temp_dir,
                metadata_bucket="my-metadata-bucket",
                sandbox_checkpoint_mount_path=temp_dir,
                sandbox_checkpoint_bucket="my-checkpoints-bucket",
            )

            handle = SandboxHandle.create_persistent(
                sandbox_id="persistent-sandbox",
                instance=mock_instance,
                idle_timeout=300,
                gcs_config=gcs_config,
            )

            # Verify the metadata file was created and has the correct content
            expected_path = os.path.join(temp_dir, "sandboxes", "persistent-sandbox", "metadata.json")
            self.assertTrue(os.path.exists(expected_path))

            with open(expected_path, "r") as f:
                metadata = json.load(f)
            
            self.assertEqual(metadata["sandbox_id"], "persistent-sandbox")
            self.assertEqual(metadata["idle_timeout"], 300)
            self.assertTrue(metadata["enable_sandbox_checkpoint"])

    def test_create_persistent_fails_if_directory_exists(self):
        """
        Tests that `create_persistent` fails if the sandbox directory already exists.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            # Manually create the directory that the handle is supposed to create
            os.makedirs(os.path.join(temp_dir, "sandboxes", "existing-sandbox"))

            mock_instance = MagicMock()
            gcs_config = GCSConfig(
                metadata_mount_path=temp_dir,
                metadata_bucket="my-metadata-bucket",
                sandbox_checkpoint_mount_path=temp_dir,
                sandbox_checkpoint_bucket="my-checkpoints-bucket",
            )

            with self.assertRaises(SandboxCreationError):
                SandboxHandle.create_persistent(
                    sandbox_id="existing-sandbox",
                    instance=mock_instance,
                    idle_timeout=300,
                    gcs_config=gcs_config,
                )

    def test_create_persistent_fails_if_no_metadata_path(self):
        mock_instance = MagicMock()
        gcs_config = GCSConfig(metadata_bucket="b", sandbox_checkpoint_mount_path="c", sandbox_checkpoint_bucket="d")
        with self.assertRaises(SandboxCreationError):
            SandboxHandle.create_persistent("id", mock_instance, 300, gcs_config)

    def test_create_persistent_fails_if_no_metadata_bucket(self):
        mock_instance = MagicMock()
        gcs_config = GCSConfig(metadata_mount_path="a", sandbox_checkpoint_mount_path="c", sandbox_checkpoint_bucket="d")
        with self.assertRaises(SandboxCreationError):
            SandboxHandle.create_persistent("id", mock_instance, 300, gcs_config)

    def test_create_persistent_fails_if_no_checkpoint_path(self):
        mock_instance = MagicMock()
        gcs_config = GCSConfig(metadata_mount_path="a", metadata_bucket="b", sandbox_checkpoint_bucket="d")
        with self.assertRaises(SandboxCreationError):
            SandboxHandle.create_persistent("id", mock_instance, 300, gcs_config)

    def test_create_persistent_fails_if_no_checkpoint_bucket(self):
        mock_instance = MagicMock()
        gcs_config = GCSConfig(metadata_mount_path="a", metadata_bucket="b", sandbox_checkpoint_mount_path="c")
        with self.assertRaises(SandboxCreationError):
            SandboxHandle.create_persistent("id", mock_instance, 300, gcs_config)


class TestAttachPersistentFactory(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.mock_instance = MagicMock()
        self.sandbox_id = "existing-sandbox"
        
        # A valid server configuration
        self.gcs_config = GCSConfig(
            metadata_mount_path=self.temp_dir.name,
            metadata_bucket="my-metadata-bucket",
            sandbox_checkpoint_mount_path=self.temp_dir.name,
            sandbox_checkpoint_bucket="my-checkpoints-bucket",
        )

        # Pre-create a valid metadata file
        self.sandbox_dir = os.path.join(self.temp_dir.name, "sandboxes", self.sandbox_id)
        os.makedirs(self.sandbox_dir)
        self.metadata_path = os.path.join(self.sandbox_dir, "metadata.json")
        
        self.valid_metadata = {
            "sandbox_id": self.sandbox_id,
            "created_timestamp": time.time(),
            "idle_timeout": 450,
            "enable_sandbox_checkpoint": True,
            "latest_sandbox_checkpoint": {
                "bucket": "my-checkpoints-bucket",
                "path": "sandbox_checkpoints/ckpt-xyz/"
            }
        }
        with open(self.metadata_path, "w") as f:
            json.dump(self.valid_metadata, f)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_attach_persistent_success(self):
        """
        Tests the "happy path" for attaching to a valid, existing sandbox.
        """
        handle = SandboxHandle.attach_persistent(
            sandbox_id=self.sandbox_id,
            instance=self.mock_instance,
            gcs_config=self.gcs_config,
        )

        self.assertIsNotNone(handle.gcs_metadata)
        self.assertEqual(handle.gcs_metadata.sandbox_id, self.sandbox_id)
        self.assertEqual(handle.idle_timeout, 450) # Verify it uses the timeout from the file
        self.assertTrue(handle.gcs_metadata.enable_sandbox_checkpoint)
        self.assertIsInstance(handle.gcs_metadata.latest_sandbox_checkpoint, GCSArtifact)

    def test_attach_persistent_fails_if_metadata_not_found(self):
        """
        Tests that attach fails with SandboxRestoreError if metadata.json is missing.
        """
        os.remove(self.metadata_path) # Remove the pre-made file

        with self.assertRaises(SandboxRestoreError):
            SandboxHandle.attach_persistent(
                sandbox_id=self.sandbox_id,
                instance=self.mock_instance,
                gcs_config=self.gcs_config,
            )

    def test_attach_persistent_fails_if_server_lacks_capabilities(self):
        """
        Tests that attach fails if the metadata requires features the server doesn't support.
        """
        # Create a server config that is missing the required checkpointing path
        invalid_gcs_config = GCSConfig(
            metadata_mount_path=self.temp_dir.name,
            metadata_bucket="my-metadata-bucket",
        )

        with self.assertRaisesRegex(SandboxRestoreError, "requires checkpointing, but the server is not configured for it"):
            SandboxHandle.attach_persistent(
                sandbox_id=self.sandbox_id,
                instance=self.mock_instance,
                gcs_config=invalid_gcs_config,
            )

    def test_attach_persistent_fails_on_bucket_mismatch(self):
        """
        Tests that attach fails if the checkpoint bucket in the metadata
        does not match the server's configuration.
        """
        # Create a server config with a different checkpoint bucket name
        mismatched_gcs_config = GCSConfig(
            metadata_mount_path=self.temp_dir.name,
            metadata_bucket="my-metadata-bucket",
            sandbox_checkpoint_mount_path=self.temp_dir.name,
            sandbox_checkpoint_bucket="a-DIFFERENT-bucket-name",
        )

        with self.assertRaisesRegex(SandboxRestoreError, "Mismatched checkpoint bucket"):
            SandboxHandle.attach_persistent(
                sandbox_id=self.sandbox_id,
                instance=self.mock_instance,
                gcs_config=mismatched_gcs_config,
            )


class TestSandboxHandleMethods(unittest.TestCase):
    def test_update_latest_checkpoint(self):
        """
        Tests that the `update_latest_checkpoint` method correctly updates
        and persists the metadata file using its internal checkpoint ID.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            mock_instance = MagicMock()
            gcs_config = GCSConfig(
                metadata_mount_path=temp_dir,
                metadata_bucket="my-metadata-bucket",
                sandbox_checkpoint_mount_path=temp_dir,
                sandbox_checkpoint_bucket="my-checkpoints-bucket",
            )

            handle = SandboxHandle.create_persistent(
                sandbox_id="persistent-sandbox",
                instance=mock_instance,
                idle_timeout=300,
                gcs_config=gcs_config,
            )

            # 1. Generate the internal checkpoint ID and path
            checkpoint_path = handle.sandbox_checkpoint_dir_path()
            self.assertIsNotNone(checkpoint_path)
            checkpoint_id = os.path.basename(checkpoint_path)

            # 2. Now, update the checkpoint metadata
            handle.update_latest_checkpoint()

            # 3. Read the file back and verify the content
            metadata_path = os.path.join(temp_dir, "sandboxes", "persistent-sandbox", "metadata.json")
            with open(metadata_path, "r") as f:
                metadata = json.load(f)

            self.assertIn("latest_sandbox_checkpoint", metadata)
            checkpoint_info = metadata["latest_sandbox_checkpoint"]
            self.assertEqual(checkpoint_info["bucket"], "my-checkpoints-bucket")
            
            # 4. Verify the path matches the structure from the documentation
            expected_path = f"sandbox_checkpoints/{checkpoint_id}"
            self.assertEqual(checkpoint_info["path"], expected_path)


class TestSandboxHandleProperties(unittest.TestCase):
    def test_is_sandbox_checkpointable(self):
        """
        Tests the `is_sandbox_checkpointable` property.
        """
        # 1. A non-persistent handle should not be checkpointable
        eph_handle = SandboxHandle.create_ephemeral("eph", MagicMock(), 120)
        self.assertFalse(eph_handle.is_sandbox_checkpointable)

        # 2. A persistent handle with the flag set to False should not be checkpointable
        meta_false = GCSSandboxMetadata("id", time.time(), enable_sandbox_checkpoint=False)
        pers_handle_false = SandboxHandle.create_ephemeral("pers", MagicMock(), 120)
        pers_handle_false.gcs_metadata = meta_false
        self.assertFalse(pers_handle_false.is_sandbox_checkpointable)

        # 3. A persistent handle with the flag set to True should be checkpointable
        meta_true = GCSSandboxMetadata("id", time.time(), enable_sandbox_checkpoint=True)
        pers_handle_true = SandboxHandle.create_ephemeral("pers", MagicMock(), 120)
        pers_handle_true.gcs_metadata = meta_true
        self.assertTrue(pers_handle_true.is_sandbox_checkpointable)


if __name__ == '__main__':
    unittest.main()
