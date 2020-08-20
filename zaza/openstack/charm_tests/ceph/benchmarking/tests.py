# Copyright 2020 Canonical Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Ceph Benchmark Tests."""

import logging
import re
import unittest

import zaza.model


class BenchmarkTests(unittest.TestCase):
    """Ceph Bencharmk Tests."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running ceph benchmark tests."""
        super().setUpClass()
        cls.results_match = "^[A-Z].*"
        cls.pool = "zaza_benchmarks"
        cls.test_results = {}
        cls.time_in_secs = 30

    def parse_bench_results(self, results_string):
        """Parse bench results from string.

        :param results string: Output from rados bench command.
                               With newlines due to juju run's output.
        :type results_string: string
        :returns: Dictionary of results summary
        :rtype: dict
        """
        _results = {}
        _lines = results_string.split("\n")
        for _line in _lines:
            _line = _line.strip()
            if re.match(self.results_match, _line):
                _keyvalues = _line.split(":")
                try:
                    _results[_keyvalues[0].strip()] = _keyvalues[1].strip()
                except IndexError:
                    # Skipping detailed output for summary details
                    pass
        return _results

    def run_rados_bench(self, action, params=None):
        """Run rados bench.

        :param action: String rados bench command i.e. write, rand, seq
        :type action: string
        :param params: List of string extra parameters to rados bench command
        :type params: List[strings]
        :returns: Unit run dict result
        :rtype: dict
        """
        _cmd = "rados bench -p {} {} {}".format(
            self.pool, self.time_in_secs, action)
        if params:
            _cmd += " "
            _cmd += " ".join(params)
        logging.info(
            "Running '{}' for {} seconds ...".format(_cmd, self.time_in_secs))
        _result = zaza.model.run_on_leader(
            "ceph-mon", _cmd, timeout=self.time_in_secs + 60)
        return _result

    def test_001_create_pool(self):
        """Create ceph pool."""
        _cmd = "ceph osd pool create {} 100 100".format(self.pool)
        _result = zaza.model.run_on_leader(
            "ceph-mon", _cmd)
        if _result.get("Code") and not _result.get("Code").startswith('0'):
            if "already exists" in _result.get("Stderr", ""):
                logging.warning(
                    "Ceph osd pool {} already exits.".format(self.pool))
            else:
                logging.error("Ceph osd pool create failed")
                raise Exception(_result.get("Stderr", ""))

    def test_100_rados_bench_write(self):
        """Rados bench write test."""
        _result = self.run_rados_bench("write", params=["--no-cleanup"])
        self.test_results["write"] = (
            self.parse_bench_results(_result.get("Stdout", "")))

    def test_200_rados_bench_read_seq(self):
        """Rados bench read sequential test."""
        _result = self.run_rados_bench("seq")
        self.test_results["read_seq"] = (
            self.parse_bench_results(_result.get("Stdout", "")))

    def test_300_rados_bench_read_rand(self):
        """Rados bench read random test."""
        _result = self.run_rados_bench("rand")
        self.test_results["read_rand"] = (
            self.parse_bench_results(_result.get("Stdout", "")))

    def test_998_rados_cleanup(self):
        """Cleanup rados bench data."""
        _cmd = "rados -p {} cleanup".format(self.pool)
        _result = zaza.model.run_on_leader("ceph-mon", _cmd)
        if _result.get("Code") and not _result.get("Code").startswith('0'):
            logging.warning("rados cleanup failed")

    def test_999_print_rados_bench_results(self):
        """Print rados bench results."""
        print("######## Begin Ceph Results ########")
        for test, results in self.test_results.items():
            print("##### {} ######".format(test))
            for key, value in results.items():
                print("{}: {}".format(key, value))
        print("######## End Ceph Results ########")
