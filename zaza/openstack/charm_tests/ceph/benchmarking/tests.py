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

import re
import unittest

import zaza.model


class CephBaseBenchmarkTests(unittest.TestCase):
    """Ceph Base Bencharmk Tests."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running ceph benchmark tests."""
        super().setUpClass()
        cls.test_results = {}


class RadosBenchmarkTests(CephBaseBenchmarkTests):
    """Rados Bencharmk Tests."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running ceph benchmark tests."""
        super().setUpClass()
        cls.results_match = "^[A-Z].*"
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

    def rados_bench_action(self, operation, seconds, switches=None):
        """Rados bench action."""
        _params = {
            "seconds": seconds,
            "operation": operation}
        if switches:
            _params["switches"] = switches
        action = zaza.model.run_action_on_leader(
            "ceph-benchmarking",
            "rados-bench",
            action_params=_params)
        assert action.data.get("results") is not None, (
            "Rados-bench action failed: {}"
            .format(action.data))
        if action.data.get("results", {}).get("code") is not None:
            assert action.data.get(
                "results", {}).get("code", "").startswith("0"), (
                "Rados-bench action return code is non-zero: {}"
                .format(action.data))
        return action.data["results"]

    def test_100_rados_bench_write(self):
        """Rados bench write test."""
        self.test_results["write"] = (
            self.parse_bench_results(
                self.rados_bench_action(
                    "write", seconds=self.time_in_secs, switches="--no-cleanup"
                ).get("stdout", "")))

    def test_200_rados_bench_read_seq(self):
        """Rados bench read sequential test."""
        self.test_results["read_seq"] = (
            self.parse_bench_results(
                self.rados_bench_action(
                    "seq", seconds=self.time_in_secs).get("stdout", "")))

    def test_300_rados_bench_read_rand(self):
        """Rados bench read random test."""
        self.test_results["read_rand"] = (
            self.parse_bench_results(
                self.rados_bench_action(
                    "rand", seconds=self.time_in_secs).get("stdout", "")))

    def test_999_print_rados_bench_results(self):
        """Print rados bench results."""
        print("######## Begin Rados Results ########")
        for test, results in self.test_results.items():
            print("##### {} ######".format(test))
            for key, value in results.items():
                print("{}: {}".format(key, value))
        print("######## End Rados Results ########")


class RBDBenchmarkTests(CephBaseBenchmarkTests):
    """RBD Bencharmk Tests."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running ceph benchmark tests."""
        super().setUpClass()

    def rbd_bench_action(self, operation):
        """RBD bench action."""
        _params = {"operation": operation}
        action = zaza.model.run_action_on_leader(
            "ceph-benchmarking",
            "rbd-bench",
            action_params=_params)
        assert action.data.get("results") is not None, (
            "RBD-bench action failed: {}"
            .format(action.data))
        if action.data.get("results", {}).get("code") is not None:
            assert action.data.get(
                "results", {}).get("code", "").startswith("0"), (
                "RBD-bench action return code is non-zero: {}"
                .format(action.data))
        return action.data["results"]

    def test_100_rbd_bench_write(self):
        """RBD bench write test."""
        self.test_results["write"] = (
            self.rbd_bench_action("write").get("stdout", ""))

    def test_999_print_rbd_bench_results(self):
        """Print rbd bench results."""
        print("######## Begin RBD Results ########")
        for test, results in self.test_results.items():
            print("##### {} ######".format(test))
            print(results)
        print("######## End RBD Results ########")


class FIOBenchmarkTests(CephBaseBenchmarkTests):
    """FIO Bencharmk Tests."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running ceph benchmark tests."""
        super().setUpClass()
        cls.block_size = "4k"
        cls.iodepth = 128
        cls.num_jobs = 8

    def fio_action(self, operation):
        """FIO action."""
        _params = {"operation": operation,
                   "block-size": self.block_size,
                   "num-jobs": self.num_jobs}
        action = zaza.model.run_action_on_leader(
            "ceph-benchmarking",
            "fio",
            action_params=_params)
        assert action.data.get("results") is not None, (
            "FIO action failed: {}"
            .format(action.data))
        if action.data.get("results", {}).get("code") is not None:
            assert action.data.get(
                "results", {}).get("code", "").startswith("0"), (
                "FIO action return code is non-zero: {}"
                .format(action.data))
        return action.data["results"]

    def test_100_fio_write(self):
        """FIO write test."""
        self.test_results["write"] = (
            self.fio_action("write").get("stdout", ""))

    def test_200_fio_read(self):
        """FIO read test."""
        self.test_results["read"] = (
            self.fio_action("read").get("stdout", ""))

    def test_999_print_fio_results(self):
        """Print fio results."""
        print("######## Begin FIO Results ########")
        for test, results in self.test_results.items():
            print("##### {} ######".format(test))
            print(results)
        print("######## End FIO Results ########")


class SwiftBenchmarkTests(CephBaseBenchmarkTests):
    """Swift Bencharmk Tests."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running ceph benchmark tests."""
        super().setUpClass()

    def swift_bench_action(self, operation):
        """Swift bench action."""
        _radosgw_ip = zaza.model.get_lead_unit_ip("ceph-radosgw")
        _params = {"swift-address": _radosgw_ip}
        action = zaza.model.run_action_on_leader(
            "ceph-benchmarking",
            "swift-bench",
            action_params=_params)
        assert action.data.get("results") is not None, (
            "Swift bench action failed: {}"
            .format(action.data))
        if action.data.get("results", {}).get("code") is not None:
            assert action.data.get(
                "results", {}).get("code", "").startswith("0"), (
                "Swift bench action return code is non-zero: {}"
                .format(action.data))
        return action.data["results"]

    def test_100_swift_bench(self):
        """Swift bench test."""
        self.test_results["write"] = (
            self.swift_bench_action("write").get("stdout", ""))

    def test_999_print_swift_bench_results(self):
        """Print swift bench results."""
        print("######## Begin Swift Bench Results ########")
        for test, results in self.test_results.items():
            print("##### {} ######".format(test))
            print(results)
        print("######## End Swift Bench Results ########")


class FIO4KBenchmarkTests(FIOBenchmarkTests):
    """FIO 4K Bencharmk Tests."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running ceph benchmark tests."""
        super().setUpClass()
        cls.block_size = "4k"


class FIO64KBenchmarkTests(FIOBenchmarkTests):
    """FIO 64K Bencharmk Tests."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running ceph benchmark tests."""
        super().setUpClass()
        cls.block_size = "64k"


class FIO1024KBenchmarkTests(FIOBenchmarkTests):
    """FIO 1024K Bencharmk Tests."""

    @classmethod
    def setUpClass(cls):
        """Run class setup for running ceph benchmark tests."""
        super().setUpClass()
        cls.block_size = "1024k"
