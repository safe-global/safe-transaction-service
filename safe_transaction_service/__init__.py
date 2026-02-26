# SPDX-License-Identifier: FSL-1.1-MIT
__version__ = "6.0.2"
__version_info__ = tuple(
    int(num) if num.isdigit() else num
    for num in __version__.replace("-", ".", 1).split(".")
)
