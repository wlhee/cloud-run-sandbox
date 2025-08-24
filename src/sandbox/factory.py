import os
from .gvisor import GVisorSandbox, GVisorConfig

def create_sandbox_instance(sandbox_id: str):
    """
    Factory function to create a sandbox instance based on configuration.
    """
    # Create GVisorConfig from environment variables
    config = GVisorConfig(
        use_sudo=os.environ.get('RUNSC_USE_SUDO', 'false').lower() in ['true', '1'],
        rootless=os.environ.get('RUNSC_ROOTLESS', 'false').lower() in ['true', '1'],
        root_dir_base=os.environ.get('RUNSC_ROOT_DIR_BASE', '/tmp'),
        bundle_dir_base=os.environ.get('RUNSC_BUNDLE_DIR_BASE', '/tmp'),
        ignore_cgroups=os.environ.get('RUNSC_IGNORE_CGROUPS', 'true').lower() in ['true', '1'],
        platform=os.environ.get('RUNSC_PLATFORM', 'ptrace')
    )
    return GVisorSandbox(sandbox_id, config=config)