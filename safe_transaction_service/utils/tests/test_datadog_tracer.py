# SPDX-License-Identifier: FSL-1.1-MIT
import os
import subprocess
import unittest
from pathlib import Path

DATADOG_TRACER_SCRIPT = (
    Path(__file__).resolve().parents[3] / "docker/web/datadog_tracer.sh"
)


def get_ddtrace_run(dd_apm_enabled: str | None) -> str:
    environment = {"PATH": os.environ["PATH"]}
    if dd_apm_enabled is not None:
        environment["DD_APM_ENABLED"] = dd_apm_enabled
    return subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; printf "%s" "${DDTRACE_RUN[*]}"',
            "bash",
            DATADOG_TRACER_SCRIPT,
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


class TestDatadogTracer(unittest.TestCase):
    def test_true_values_start_ddtrace_run(self):
        """
        Every DD_APM_ENABLED value ddtrace reads as true starts the process with ddtrace-run.
        """
        for dd_apm_enabled in (
            "1",
            "true",
            "True",
            "TRUE",
            "yes",
            "y",
            "t",
            "on",
            "ON",
        ):
            with self.subTest(dd_apm_enabled=dd_apm_enabled):
                self.assertEqual(get_ddtrace_run(dd_apm_enabled), "ddtrace-run")

    def test_other_values_start_without_ddtrace_run(self):
        """
        Unset, empty, false and unknown DD_APM_ENABLED values start the process without ddtrace-run.
        """
        for dd_apm_enabled in (None, "", "0", "false", "off", "no", "enabled", " true"):
            with self.subTest(dd_apm_enabled=dd_apm_enabled):
                self.assertEqual(get_ddtrace_run(dd_apm_enabled), "")
