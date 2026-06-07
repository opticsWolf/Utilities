"""Global Package Management dock.

The functionality is split across four focused mixins, composed here into the
public :class:`GlobalPackagesMixin`. Existing imports keep working unchanged:

    from global_packages_pane import GlobalPackagesMixin

Mixins:
    * GlobalPackagesUIMixin   -- dock/tab construction + settings load/save
    * PyPIBuildMixin          -- PyPI search/install + advanced build / wheels
    * CondaInstalledMixin     -- Conda search/install + installed-list ops
    * CudaAuditMixin          -- CUDA/MSVC detection, system audit, toolkit prep
"""

from gpm_ui_builder import GlobalPackagesUIMixin
from pypi_build_ops import PyPIBuildMixin
from conda_installed_ops import CondaInstalledMixin
from cuda_audit import CudaAuditMixin


class GlobalPackagesMixin(
    GlobalPackagesUIMixin,
    PyPIBuildMixin,
    CondaInstalledMixin,
    CudaAuditMixin,
):
    """Manages the global packages functionality (PyPI, Conda Search, Multi-Uninstall, Update)."""


__all__ = ["GlobalPackagesMixin"]
