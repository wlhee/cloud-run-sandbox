import os
from .gvisor import GVisorSandbox, GVisorConfig

def create_sandbox_instance(sandbox_id: str):
    """
    Factory function to create a sandbox instance based on configuration.
    """
    # Create GVisorConfig from environment variables
    config = GVisorConfig(
        rootless=os.environ.get('RUNSC_ROOTLESS') in ['true', '1'],
        root_dir=os.environ.get('RUNSC_ROOT_DIR'),
        bundle_dir_base=os.environ.get('RUNSC_BUNDLE_DIR_BASE', '/tmp'),
        systemd_cgroup=os.environ.get('RUNSC_SYSTEMD_CGROUP') in ['true', '1']
    )
    return GVisorSandbox(sandbox_id, config=config)