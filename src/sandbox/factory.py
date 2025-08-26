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
        platform=os.environ.get('RUNSC_PLATFORM', 'systrap'),
        network='none' if os.environ.get('RUNSC_DISABLE_NETWORKING', 'false').lower() in ['true', '1'] else 'host',
        writable_filesystem=os.environ.get('RUNSC_READONLY_FILESYSTEM', 'false').lower() not in ['true', '1'],
        debug=os.environ.get('GVISOR_DEBUG', 'false').lower() in ['true', '1'],
        strace=os.environ.get('GVISOR_STRACE', 'false').lower() in ['true', '1'],
        debug_log_dir=os.environ.get('GVISOR_DEBUG_LOG_DIR', '/tmp/runsc')
    )
    return GVisorSandbox(sandbox_id, config=config)